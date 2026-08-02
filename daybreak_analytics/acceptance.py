from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from .analytics import analyze_session, summarize_sessions
from .canonical import canonical_sha256
from .enums import AcceptanceStatus, DeploymentStatus
from .models import (
    AggregatePerformance,
    DeploymentEvidenceReport,
    DeploymentEvidenceRequest,
    PaperAcceptanceLedger,
    PaperAcceptanceRequest,
    SessionAcceptance,
)

Q = Decimal("0.0000000001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Q, rounding=ROUND_HALF_EVEN)


def paper_ledger_body(ledger: PaperAcceptanceLedger) -> dict[str, object]:
    """Return the complete canonical ledger body covered by ``ledger_hash``."""
    return ledger.model_dump(mode="python", exclude={"ledger_id", "ledger_hash"})


def deployment_report_body(report: DeploymentEvidenceReport) -> dict[str, object]:
    """Return the complete canonical deployment body covered by ``report_hash``."""
    return report.model_dump(mode="python", exclude={"report_id", "report_hash"})


def build_paper_acceptance_ledger(request: PaperAcceptanceRequest) -> PaperAcceptanceLedger:
    request_hash = canonical_sha256(request)
    replay_by_session = {item.session_id: item for item in request.replay_reports}
    session_records: list[SessionAcceptance] = []
    analytics_values = []
    for session in request.sessions:
        analytics = analyze_session(session)
        analytics_values.append(analytics)
        replay = replay_by_session.get(session.session_id)
        reasons: list[str] = []
        if not session.full_session_recorded:
            reasons.append("SESSION_NOT_FULLY_RECORDED")
        if session.invariant_violations > request.policy.maximum_invariant_violations:
            reasons.append("INVARIANT_VIOLATIONS")
        if session.unresolved_reconciliations > request.policy.maximum_unresolved_reconciliations:
            reasons.append("UNRESOLVED_RECONCILIATIONS")
        if session.duplicate_order_count > request.policy.maximum_duplicate_orders:
            reasons.append("DUPLICATE_ORDERS")
        if session.late_primary_response_count > request.policy.maximum_late_primary_responses:
            reasons.append("LATE_PRIMARY_RESPONSES")
        if request.policy.require_all_positions_flat and not session.all_positions_flat:
            reasons.append("POSITIONS_NOT_FLAT")
        if request.policy.require_complete_replay and (replay is None or not replay.passed):
            reasons.append("REPLAY_NOT_VERIFIED")
        session_records.append(
            SessionAcceptance(
                session_id=session.session_id,
                trading_date=session.trading_date,
                clean=not reasons,
                reasons=tuple(reasons),
                analytics_id=analytics.analytics_id,
                replay_id=replay.replay_id if replay else None,
            )
        )
    session_count = len(request.sessions)
    clean_count = sum(item.clean for item in session_records)
    filled_orders = sum(item.orders_filled for item in request.sessions)
    clean_rate = (
        _q(Decimal(clean_count) / Decimal(session_count)) if session_count else Decimal("0")
    )
    blockers: list[str] = []
    if session_count < request.policy.minimum_sessions:
        blockers.append("MINIMUM_SESSION_COUNT_NOT_MET")
    if filled_orders < request.policy.minimum_filled_orders:
        blockers.append("MINIMUM_FILLED_ORDER_COUNT_NOT_MET")
    if clean_rate < request.policy.minimum_clean_session_rate:
        blockers.append("CLEAN_SESSION_RATE_NOT_MET")
    if request.policy.require_target_acceptance and not request.target_acceptance_verified:
        blockers.append("TARGET_ACCEPTANCE_NOT_VERIFIED")
    if request.policy.require_restore_validation and not request.restore_validation_verified:
        blockers.append("RESTORE_VALIDATION_NOT_VERIFIED")
    if len(request.passed_drills) < request.policy.required_drill_count:
        blockers.append("REQUIRED_DRILLS_NOT_VERIFIED")
    if (
        session_count < request.policy.minimum_sessions
        or filled_orders < request.policy.minimum_filled_orders
    ):
        status = AcceptanceStatus.COLLECTING
    elif blockers:
        status = AcceptanceStatus.BLOCKED
    else:
        status = AcceptanceStatus.PAPER_QUALIFIED
    summary = summarize_sessions(
        analytics_values, (trade for session in request.sessions for trade in session.trades)
    )
    performance = AggregatePerformance.model_validate(summary)
    body = {
        "generated_at": request.generated_at,
        "status": status,
        "paper_ready": status is AcceptanceStatus.PAPER_QUALIFIED,
        "live_ready": False,
        "session_count": session_count,
        "clean_session_count": clean_count,
        "filled_order_count": filled_orders,
        "clean_session_rate": clean_rate,
        "sessions": tuple(session_records),
        "performance": performance,
        "blockers": tuple(blockers),
        "policy": request.policy,
        "configuration_hash": request.configuration_hash,
        "request_hash": request_hash,
    }
    ledger_hash = canonical_sha256(body)
    return PaperAcceptanceLedger.model_validate(
        {
            **body,
            "ledger_id": f"PL-{ledger_hash[:20]}",
            "ledger_hash": ledger_hash,
        }
    )


def build_deployment_evidence_report(
    request: DeploymentEvidenceRequest,
) -> DeploymentEvidenceReport:
    request_hash = canonical_sha256(request)
    blockers: list[str] = []
    if request.tests_passed != request.tests_collected:
        blockers.append("TEST_SUITE_NOT_GREEN")
    if request.secret_findings != 0:
        blockers.append("SECRET_FINDINGS_PRESENT")
    if (
        canonical_sha256(paper_ledger_body(request.paper_ledger))
        != request.paper_ledger.ledger_hash
    ):
        blockers.append("PAPER_LEDGER_HASH_INVALID")
    if not request.paper_ledger.paper_ready:
        blockers.append("PAPER_LEDGER_NOT_QUALIFIED")
    if not request.target_acceptance_verified:
        blockers.append("TARGET_ACCEPTANCE_NOT_VERIFIED")
    if not request.restore_validation_verified:
        blockers.append("RESTORE_VALIDATION_NOT_VERIFIED")
    if not request.required_drills_verified:
        blockers.append("REQUIRED_DRILLS_NOT_VERIFIED")
    if not request.online_paper_account_verified:
        blockers.append("ONLINE_PAPER_ACCOUNT_NOT_VERIFIED")
    if not request.postgres_verified:
        blockers.append("POSTGRES_NOT_VERIFIED")
    if not request.ntp_verified:
        blockers.append("NTP_NOT_VERIFIED")
    status = DeploymentStatus.PAPER_READY if not blockers else DeploymentStatus.INCOMPLETE
    evidence_hashes = tuple(
        sorted(
            (
                ("configuration", request.configuration_hash),
                ("migrations", request.migrations_sha256),
                ("paper_ledger", request.paper_ledger.ledger_hash),
                ("schemas_bundle", request.schemas_bundle_sha256),
                ("source_archive", request.source_archive_sha256),
                ("specification", request.specification_sha256),
                ("verification_report", request.verification_report_sha256),
                ("wheel", request.wheel_sha256),
            )
        )
    )
    body = {
        "generated_at": request.generated_at,
        "status": status,
        "paper_deployment_ready": status is DeploymentStatus.PAPER_READY,
        "live_deployment_ready": False,
        "blockers": tuple(blockers),
        "release_version": request.release_version,
        "specification_version": request.specification_version,
        "migration_head": request.migration_head,
        "configuration_hash": request.configuration_hash,
        "paper_ledger_id": request.paper_ledger.ledger_id,
        "paper_ledger_hash": request.paper_ledger.ledger_hash,
        "tests_collected": request.tests_collected,
        "tests_passed": request.tests_passed,
        "schema_count": request.schema_count,
        "secret_findings": request.secret_findings,
        "evidence_hashes": evidence_hashes,
        "request_hash": request_hash,
    }
    report_hash = canonical_sha256(body)
    return DeploymentEvidenceReport.model_validate(
        {
            **body,
            "report_id": f"DE-{report_hash[:20]}",
            "report_hash": report_hash,
        }
    )
