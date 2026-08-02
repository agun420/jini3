from datetime import UTC, datetime
from decimal import Decimal

from daybreak_analytics.acceptance import (
    build_deployment_evidence_report,
    build_paper_acceptance_ledger,
)
from daybreak_analytics.models import (
    AnalyticsPolicy,
    DeploymentEvidenceRequest,
    PaperAcceptanceRequest,
)
from daybreak_operations.enums import DrillType

from .helpers import H, make_replay, make_session


def _request(count: int = 2, clean: bool = True) -> PaperAcceptanceRequest:
    sessions = tuple(make_session(index=i, clean=clean) for i in range(count))
    reports = tuple(make_replay(item, passed=clean) for item in sessions)
    return PaperAcceptanceRequest(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        policy=AnalyticsPolicy(
            minimum_sessions=2,
            minimum_filled_orders=4,
            minimum_clean_session_rate=Decimal("1"),
            required_drill_count=2,
        ),
        sessions=sessions,
        replay_reports=reports,
        target_acceptance_verified=True,
        restore_validation_verified=True,
        passed_drills=(DrillType.DATABASE_DISCONNECT, DrillType.PROCESS_RESTART),
        configuration_hash=H,
    )


def test_paper_ledger_qualifies_only_operational_evidence():
    ledger = build_paper_acceptance_ledger(_request())
    assert ledger.paper_ready is True
    assert ledger.live_ready is False
    assert ledger.blockers == ()
    assert ledger.filled_order_count == 4


def test_profitability_is_not_an_acceptance_gate():
    request = _request()
    ledger = build_paper_acceptance_ledger(request)
    assert ledger.performance.net_pnl < 0
    assert ledger.paper_ready is True
    assert ledger.policy.performance_is_acceptance_gate is False


def test_dirty_session_blocks_ledger():
    ledger = build_paper_acceptance_ledger(_request(clean=False))
    assert ledger.paper_ready is False
    assert "CLEAN_SESSION_RATE_NOT_MET" in ledger.blockers


def test_collecting_status_when_sample_size_is_short():
    request = _request(count=1)
    ledger = build_paper_acceptance_ledger(request)
    assert ledger.status.value == "collecting"
    assert "MINIMUM_SESSION_COUNT_NOT_MET" in ledger.blockers


def test_deployment_report_requires_online_evidence():
    ledger = build_paper_acceptance_ledger(_request())
    request = DeploymentEvidenceRequest(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        release_version="1.0.2",
        configuration_hash=H,
        source_archive_sha256="b" * 64,
        wheel_sha256="c" * 64,
        migrations_sha256="d" * 64,
        schemas_bundle_sha256="e" * 64,
        verification_report_sha256="f" * 64,
        specification_sha256="1" * 64,
        migration_head="0009_phase9_release",
        tests_collected=10,
        tests_passed=10,
        schema_count=10,
        secret_findings=0,
        paper_ledger=ledger,
        target_acceptance_verified=True,
        restore_validation_verified=True,
        required_drills_verified=True,
        online_paper_account_verified=False,
        postgres_verified=True,
        ntp_verified=True,
    )
    report = build_deployment_evidence_report(request)
    assert report.paper_deployment_ready is False
    assert report.live_deployment_ready is False
    assert "ONLINE_PAPER_ACCOUNT_NOT_VERIFIED" in report.blockers


def test_complete_deployment_evidence_can_certify_paper_only():
    ledger = build_paper_acceptance_ledger(_request())
    request = DeploymentEvidenceRequest(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        release_version="1.0.2",
        configuration_hash=H,
        source_archive_sha256="b" * 64,
        wheel_sha256="c" * 64,
        migrations_sha256="d" * 64,
        schemas_bundle_sha256="e" * 64,
        verification_report_sha256="f" * 64,
        specification_sha256="1" * 64,
        migration_head="0009_phase9_release",
        tests_collected=10,
        tests_passed=10,
        schema_count=10,
        secret_findings=0,
        paper_ledger=ledger,
        target_acceptance_verified=True,
        restore_validation_verified=True,
        required_drills_verified=True,
        online_paper_account_verified=True,
        postgres_verified=True,
        ntp_verified=True,
    )
    report = build_deployment_evidence_report(request)
    assert report.paper_deployment_ready is True
    assert report.live_deployment_ready is False
    assert report.status.value == "paper_ready"
