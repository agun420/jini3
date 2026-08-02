from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from daybreak import SPEC_VERSION, __version__
from daybreak.core.hashing import canonical_sha256
from daybreak.dashboard_snapshot import DashboardSnapshotSources, build_dashboard_snapshot
from daybreak_analytics.acceptance import (
    build_deployment_evidence_report,
    build_paper_acceptance_ledger,
)
from daybreak_analytics.analytics import analyze_session
from daybreak_analytics.canonical import canonical_json_text as analytics_canonical_json_text
from daybreak_analytics.models import (
    DeploymentEvidenceRequest,
    FullSessionReplayRequest,
    PaperAcceptanceRequest,
    SessionEvidence,
)
from daybreak_analytics.persistence import PostgresAnalyticsRepository
from daybreak_analytics.replay import build_full_session_replay_report
from daybreak_analytics.schema import (
    analytics_policy_schema,
    deployment_evidence_report_schema,
    deployment_evidence_request_schema,
    paper_acceptance_ledger_schema,
    paper_acceptance_request_schema,
    replay_report_schema,
    replay_request_schema,
    session_evidence_schema,
    session_performance_schema,
)
from daybreak_contracts.input_models import DaybreakInput
from daybreak_contracts.validation.runner import validate_daybreak_run
from daybreak_evaluator.models import EvaluationEvidence, EvaluationRequest, EvaluatorPolicy
from daybreak_evaluator.persistence import (
    EvaluatorRepository,
    NullEvaluatorRepository,
    PostgresEvaluatorRepository,
)
from daybreak_evaluator.schema import daybreak_output_json_schema
from daybreak_evaluator.service import EvaluatorService
from daybreak_evaluator.transport import OpenAIResponsesTransport
from daybreak_execution.alpaca import AlpacaPaperBroker
from daybreak_execution.canonical import canonical_json_text as execution_canonical_json_text
from daybreak_execution.models import BrokerOrderSnapshot, BrokerPositionSnapshot, ExecutionRequest
from daybreak_execution.order_builder import build_entry_command
from daybreak_execution.persistence import (
    ExecutionRepository,
    MemoryExecutionRepository,
    PostgresExecutionRepository,
)
from daybreak_execution.reservations import (
    NullReservationEventSink,
    PostgresReservationEventSink,
    ReservationEventSink,
)
from daybreak_execution.schema import (
    broker_order_command_schema,
    execution_policy_schema,
    execution_request_schema,
    execution_result_schema,
    reconciliation_report_schema,
    trade_update_schema,
)
from daybreak_execution.service import ExecutionService
from daybreak_features.canonical import canonical_json_text
from daybreak_features.engine import build_feature_snapshot
from daybreak_features.models import FeatureContext, FeatureSnapshot
from daybreak_operations.acceptance import build_target_acceptance_report
from daybreak_operations.backup import build_backup_manifest, validate_restore
from daybreak_operations.canonical import canonical_json_text as operations_canonical_json_text
from daybreak_operations.drills import run_failure_drill
from daybreak_operations.enums import DrillType
from daybreak_operations.models import (
    BackupManifest,
    DrillResult,
    OperationsPolicy,
    RecoveryPlan,
    RestartState,
    RestoreValidation,
)
from daybreak_operations.observability import build_observability_snapshot
from daybreak_operations.persistence import PostgresOperationsRepository
from daybreak_operations.recovery import build_recovery_plan
from daybreak_operations.schema import (
    backup_manifest_schema,
    drill_result_schema,
    observability_snapshot_schema,
    operations_policy_schema,
    recovery_plan_schema,
    restart_state_schema,
    restore_validation_schema,
    target_acceptance_schema,
)
from daybreak_orchestration.acceptance import build_acceptance_report, system_ntp_probe
from daybreak_orchestration.alpaca_ops import AlpacaPaperOperations
from daybreak_orchestration.canonical import (
    canonical_json_text as orchestration_canonical_json_text,
)
from daybreak_orchestration.clock import build_session_plan
from daybreak_orchestration.enums import KillSwitchReason
from daybreak_orchestration.flatten import FlattenService
from daybreak_orchestration.kill_switch import activate_kill_switch
from daybreak_orchestration.models import OrchestrationPolicy
from daybreak_orchestration.persistence import (
    MemoryOrchestrationRepository,
    OrchestrationRepository,
    PostgresOrchestrationRepository,
)
from daybreak_orchestration.schema import (
    acceptance_report_schema,
    flatten_result_schema,
    health_snapshot_schema,
    orchestration_policy_schema,
    session_plan_schema,
    session_result_schema,
)
from daybreak_release.canonical import canonical_json_text as release_canonical_json_text
from daybreak_release.evidence import build_evidence_manifest
from daybreak_release.freeze import build_configuration_freeze
from daybreak_release.models import ProductionCandidateRequest
from daybreak_release.persistence import PostgresReleaseRepository
from daybreak_release.review import review_production_candidate
from daybreak_release.schema import (
    approval_attestation_schema,
    artifact_evidence_schema,
    build_attestation_schema,
    configuration_freeze_schema,
    evidence_manifest_schema,
    production_candidate_report_schema,
    production_candidate_request_schema,
    production_policy_schema,
    review_finding_schema,
    rollback_evidence_schema,
)
from daybreak_risk.canonical import canonical_json_text as risk_canonical_json_text
from daybreak_risk.engine import size_approved_batch, size_position
from daybreak_risk.models import BatchSizingRequest, SizingRequest
from daybreak_risk.persistence import PostgresRiskRepository
from daybreak_risk.schema import (
    batch_sizing_request_schema,
    batch_sizing_result_schema,
    risk_decision_schema,
    risk_sizing_request_schema,
)

from .core.config import DaybreakSettings, load_settings
from .core.errors import ConfigurationError
from .core.hashing import file_sha256
from .core.health import required_checks_pass, run_health_checks
from .core.manifest import build_release_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daybreak")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="Show release and specification versions")

    doctor = sub.add_parser("doctor", help="Run local platform health checks")
    doctor.add_argument("--config", default="config/daybreak.example.toml")
    doctor.add_argument("--json", action="store_true", dest="as_json")

    manifest = sub.add_parser("manifest", help="Generate deterministic release metadata")
    manifest.add_argument("--config", default="config/daybreak.example.toml")

    hash_file = sub.add_parser("hash-file", help="Calculate a file SHA-256 hash")
    hash_file.add_argument("path")

    validate = sub.add_parser(
        "validate-contract", help="Validate one evaluator input/output fixture pair"
    )
    validate.add_argument("input_path")
    validate.add_argument("output_path")

    features = sub.add_parser(
        "build-features",
        help="Build a deterministic feature snapshot from a FeatureContext JSON file",
    )
    features.add_argument("context_path")
    features.add_argument("--output", "-o")

    evaluate = sub.add_parser(
        "evaluate",
        help="Run the v6.3 Structured Outputs evaluator on a feature snapshot or input payload",
    )
    evaluate.add_argument("input_path")
    evaluate.add_argument("--config", default="config/daybreak.example.toml")
    evaluate.add_argument(
        "--cutoff", help="UTC ISO-8601 response cutoff; defaults to configured ET cutoff"
    )
    evaluate.add_argument("--run-id")
    evaluate.add_argument(
        "--await-shadow",
        action="store_true",
        help="Research mode only: wait for shadow comparison after the primary result",
    )
    evaluate.add_argument("--output", "-o")

    schema = sub.add_parser(
        "evaluator-schema", help="Print the provider Structured Outputs JSON Schema"
    )
    schema.add_argument("--output", "-o")

    risk_size = sub.add_parser(
        "risk-size", help="Run deterministic position sizing for one approved setup"
    )
    risk_size.add_argument("request_path")
    risk_size.add_argument("--output", "-o")

    risk_batch = sub.add_parser(
        "risk-size-batch", help="Size up to three approved setups in rank order"
    )
    risk_batch.add_argument("request_path")
    risk_batch.add_argument("--output", "-o")

    risk_schema = sub.add_parser("risk-schema", help="Print a risk-engine JSON Schema")
    risk_schema.add_argument(
        "kind", choices=("request", "decision", "batch-request", "batch-result")
    )
    risk_schema.add_argument("--output", "-o")

    execution_build = sub.add_parser(
        "execution-build-order", help="Build a paper DAY bracket command without contacting Alpaca"
    )
    execution_build.add_argument("request_path")
    execution_build.add_argument("--output", "-o")

    execution_submit = sub.add_parser(
        "execution-submit-paper", help="Submit one validated order to Alpaca paper trading"
    )
    execution_submit.add_argument("request_path")
    execution_submit.add_argument("--config", default="config/daybreak.example.toml")
    execution_submit.add_argument("--confirm-paper", action="store_true")
    execution_submit.add_argument("--output", "-o")

    execution_schema = sub.add_parser("execution-schema", help="Print an execution JSON Schema")
    execution_schema.add_argument(
        "kind", choices=("policy", "request", "command", "result", "trade-update", "reconciliation")
    )
    execution_schema.add_argument("--output", "-o")

    orchestration_plan = sub.add_parser(
        "orchestration-plan", help="Build a deterministic paper-session plan"
    )
    orchestration_plan.add_argument("trading_date", help="Exchange date in YYYY-MM-DD")
    orchestration_plan.add_argument("--run-id")
    orchestration_plan.add_argument("--config", default="config/daybreak.example.toml")
    orchestration_plan.add_argument("--output", "-o")

    orchestration_schema = sub.add_parser(
        "orchestration-schema", help="Print an orchestration JSON Schema"
    )
    orchestration_schema.add_argument(
        "kind", choices=("policy", "plan", "health", "flatten", "acceptance", "result")
    )
    orchestration_schema.add_argument("--output", "-o")

    acceptance = sub.add_parser(
        "acceptance-check", help="Validate the target paper-trading environment"
    )
    acceptance.add_argument("--config", default="config/daybreak.example.toml")
    acceptance.add_argument("--online-paper", action="store_true")
    acceptance.add_argument("--confirm-paper", action="store_true")
    acceptance.add_argument("--output", "-o")

    operations_schema = sub.add_parser(
        "operations-schema", help="Print an operational-resilience JSON Schema"
    )
    operations_schema.add_argument(
        "kind",
        choices=(
            "policy",
            "observability",
            "restart-state",
            "recovery-plan",
            "backup",
            "restore",
            "drill",
            "acceptance",
        ),
    )
    operations_schema.add_argument("--output", "-o")

    recovery_plan = sub.add_parser(
        "operations-recovery-plan", help="Build a fail-closed restart recovery plan from JSON state"
    )
    recovery_plan.add_argument("state_path")
    recovery_plan.add_argument("--output", "-o")

    observability = sub.add_parser(
        "operations-observability",
        help="Build an operational health snapshot from numeric metrics JSON",
    )
    observability.add_argument("metrics_path")
    observability.add_argument("--config", default="config/daybreak.example.toml")
    observability.add_argument("--session-id")
    observability.add_argument("--output", "-o")

    backup = sub.add_parser(
        "operations-backup-manifest", help="Hash and describe one PostgreSQL backup artifact"
    )
    backup.add_argument("artifact_path")
    backup.add_argument("--source-database", required=True)
    backup.add_argument("--schema-revision", required=True)
    backup.add_argument(
        "--table-counts", required=True, help="JSON object mapping table names to counts"
    )
    backup.add_argument("--encrypted", action="store_true")
    backup.add_argument("--complete", action="store_true")
    backup.add_argument("--output", "-o")

    restore = sub.add_parser(
        "operations-restore-validate",
        help="Validate a restored backup using supplied replay evidence",
    )
    restore.add_argument("manifest_path")
    restore.add_argument("--target-database", required=True)
    restore.add_argument("--schema-revision", required=True)
    restore.add_argument("--table-counts", required=True)
    restore.add_argument("--replay-verified", action="store_true")
    restore.add_argument("--output", "-o")

    drill = sub.add_parser(
        "operations-drill-simulate",
        help="Run a deterministic, non-network failure-drill simulation",
    )
    drill.add_argument("kind", choices=tuple(item.value for item in DrillType))
    drill.add_argument("--confirm-simulation", action="store_true")
    drill.add_argument("--output", "-o")

    target_acceptance = sub.add_parser(
        "operations-acceptance", help="Validate target-VM operational evidence for paper readiness"
    )
    target_acceptance.add_argument("--config", default="config/daybreak.example.toml")
    target_acceptance.add_argument("--state-dir")
    target_acceptance.add_argument("--restore-validation")
    target_acceptance.add_argument("--recovery-plan")
    target_acceptance.add_argument("--drill-result", action="append", default=[])
    target_acceptance.add_argument("--online-paper", action="store_true")
    target_acceptance.add_argument("--confirm-paper", action="store_true")
    target_acceptance.add_argument("--output", "-o")

    analytics_schema = sub.add_parser(
        "analytics-schema", help="Print a Phase 8 analytics or evidence JSON Schema"
    )
    analytics_schema.add_argument(
        "kind",
        choices=(
            "policy",
            "session-evidence",
            "session-performance",
            "replay-request",
            "replay-report",
            "ledger-request",
            "ledger",
            "deployment-request",
            "deployment-report",
        ),
    )
    analytics_schema.add_argument("--output", "-o")

    analytics_session = sub.add_parser(
        "analytics-session",
        help="Calculate deterministic performance attribution for one paper session",
    )
    analytics_session.add_argument("evidence_path")
    analytics_session.add_argument("--output", "-o")

    analytics_replay = sub.add_parser(
        "analytics-replay-report", help="Build a six-component full-session replay report"
    )
    analytics_replay.add_argument("request_path")
    analytics_replay.add_argument("--output", "-o")

    analytics_ledger = sub.add_parser(
        "analytics-paper-ledger", help="Build the immutable paper-acceptance ledger"
    )
    analytics_ledger.add_argument("request_path")
    analytics_ledger.add_argument("--output", "-o")

    analytics_deployment = sub.add_parser(
        "analytics-deployment-report", help="Build a paper deployment-evidence report"
    )
    analytics_deployment.add_argument("request_path")
    analytics_deployment.add_argument("--output", "-o")

    production_schema = sub.add_parser(
        "production-schema", help="Print a v1.0 production-candidate JSON Schema"
    )
    production_schema.add_argument(
        "kind",
        choices=(
            "policy",
            "artifact",
            "manifest",
            "build",
            "freeze",
            "finding",
            "approval",
            "rollback",
            "request",
            "report",
        ),
    )
    production_schema.add_argument("--output", "-o")

    production_manifest = sub.add_parser(
        "production-evidence-manifest",
        help="Hash release artifacts into a deterministic evidence manifest",
    )
    production_manifest.add_argument(
        "--file",
        action="append",
        required=True,
        help="Artifact mapping in canonical_name=/path/to/file form",
    )
    production_manifest.add_argument("--output", "-o")

    production_freeze = sub.add_parser(
        "production-freeze", help="Freeze one paper-only v1.0 configuration"
    )
    production_freeze.add_argument("--config", default="config/daybreak.example.toml")
    production_freeze.add_argument("--output", "-o")

    production_review = sub.add_parser(
        "production-review", help="Build the deterministic v1.0 production-candidate report"
    )
    production_review.add_argument("request_path")
    production_review.add_argument("--output", "-o")

    emergency_flatten = sub.add_parser(
        "paper-emergency-flatten",
        help="Cancel and flatten only positions owned by the current Daybreak paper session",
    )
    emergency_flatten.add_argument("trading_date", help="Exchange date in YYYY-MM-DD")
    emergency_flatten.add_argument("--run-id", required=True)
    emergency_flatten.add_argument("--config", default="config/daybreak.example.toml")
    emergency_flatten.add_argument("--confirm-paper", action="store_true")
    emergency_flatten.add_argument("--output", "-o")

    dashboard_snapshot = sub.add_parser(
        "dashboard-snapshot",
        help=(
            "Export a private dashboard.schema.json-shaped snapshot of real system state. "
            "Never commit the output; load it via the dashboard's 'Load private snapshot' control."
        ),
    )
    dashboard_snapshot.add_argument("session_id")
    dashboard_snapshot.add_argument("trading_date", help="Exchange date in YYYY-MM-DD")
    dashboard_snapshot.add_argument("--config", default="config/daybreak.example.toml")
    dashboard_snapshot.add_argument(
        "--run-id", help="Evaluator run_id to look up signals for; defaults to session_id"
    )
    dashboard_snapshot.add_argument(
        "--include-broker",
        action="store_true",
        help="Also fetch live positions/orders/account from Alpaca paper trading",
    )
    dashboard_snapshot.add_argument("--output", "-o", required=True)
    return parser


def _parse_iso_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _configured_cutoff(payload: DaybreakInput, cutoff_time_et: str) -> datetime:
    et = ZoneInfo("America/New_York")
    evaluation_et = _parse_iso_timestamp(payload.evaluation_timestamp).astimezone(et)
    local = datetime.combine(evaluation_et.date(), _parse_hms(cutoff_time_et), tzinfo=et)
    return local.astimezone(UTC)


def _load_evaluator_input(
    path: Path, configuration_hash: str
) -> tuple[DaybreakInput, EvaluationEvidence]:
    raw_text = path.read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    if isinstance(raw, dict) and "payload" in raw and "snapshot_id" in raw:
        snapshot = FeatureSnapshot.model_validate(raw)
        prequalified = frozenset(
            item.ticker for item in snapshot.prequalification if not item.accepted
        )
        omitted = frozenset(item.ticker for item in snapshot.capacity_omissions)
        evidence = EvaluationEvidence(
            snapshot_id=snapshot.snapshot_id,
            context_hash=snapshot.context_hash,
            payload_hash=snapshot.payload_hash,
            feature_hash=snapshot.feature_hash,
            audit_hash=snapshot.audit_hash,
            configuration_hash=snapshot.configuration_hash,
            prequalified_out_tickers=prequalified,
            capacity_omitted_tickers=omitted,
            capacity_omissions_logged=omitted,
            preselection_policy_version=(
                snapshot.capacity_omissions[0].policy_version
                if snapshot.capacity_omissions
                else "prequal_rank_v1"
            ),
        )
        return snapshot.payload, evidence
    payload = DaybreakInput.model_validate(raw)
    evidence = EvaluationEvidence(
        payload_hash=canonical_sha256(payload.model_dump(mode="json")),
        configuration_hash=configuration_hash,
    )
    return payload, evidence


def _parse_hms(value: str) -> time:
    raw_parts = value.split(":")
    if len(raw_parts) != 3:
        raise ValueError(f"expected HH:MM:SS, received {value!r}")
    hour, minute, second = (int(part) for part in raw_parts)
    return time(hour, minute, second)


def _operations_policy(settings: DaybreakSettings) -> OperationsPolicy:
    source = settings.operations
    return OperationsPolicy(
        heartbeat_interval_seconds=source.heartbeat_interval_seconds,
        max_heartbeat_gap_seconds=source.max_heartbeat_gap_seconds,
        minimum_free_disk_bytes=source.minimum_free_disk_bytes,
        minimum_file_descriptor_limit=source.minimum_file_descriptor_limit,
        required_backup_retention_count=source.required_backup_retention_count,
    )


def _orchestration_policy(settings: DaybreakSettings) -> OrchestrationPolicy:
    source = settings.orchestration
    return OrchestrationPolicy(
        recorder_warmup_time_et=_parse_hms(source.recorder_warmup_time_et),
        feature_window_start_time_et=_parse_hms(source.feature_window_start_time_et),
        feature_snapshot_time_et=_parse_hms(source.feature_snapshot_time_et),
        evaluator_cutoff_time_et=_parse_hms(source.evaluator_cutoff_time_et),
        eligibility_lock_time_et=_parse_hms(source.eligibility_lock_time_et),
        regular_session_open_time_et=_parse_hms(source.regular_session_open_time_et),
        new_entry_cutoff_time_et=_parse_hms(source.new_entry_cutoff_time_et),
        mandatory_flatten_time_et=_parse_hms(source.mandatory_flatten_time_et),
        final_flatten_deadline_et=_parse_hms(source.final_flatten_deadline_et),
        leadership_ttl_seconds=source.leadership_ttl_seconds,
        leadership_renew_interval_seconds=source.leadership_renew_interval_seconds,
        flatten_poll_interval_seconds=source.flatten_poll_interval_seconds,
        flatten_verification_timeout_seconds=source.flatten_verification_timeout_seconds,
        alert_dedup_window_seconds=source.alert_dedup_window_seconds,
    )


ProbeResult = tuple[bool, str, dict[str, object]]
Probe = Callable[[], ProbeResult]


def _database_probe(dsn: str) -> Probe:
    def probe() -> ProbeResult:
        try:
            import psycopg
        except ImportError as exc:
            return False, f"psycopg unavailable: {exc}", {}
        normalized = dsn.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(normalized, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            value = cur.fetchone()
        return value == (1,), "PostgreSQL connectivity check passed.", {}

    return probe


def _migration_head_probe(dsn: str, expected_revision: str = "0009_phase9_release") -> Probe:
    def probe() -> ProbeResult:
        try:
            import psycopg
        except ImportError as exc:
            return False, f"psycopg unavailable: {exc}", {}
        normalized = dsn.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(normalized, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            row = cur.fetchone()
        actual = row[0] if row else None
        passed = actual == expected_revision
        return (
            passed,
            (
                "Database migration head matches."
                if passed
                else f"Expected {expected_revision}, found {actual}."
            ),
            {"expected": expected_revision, "actual": actual},
        )

    return probe


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "version":
            print(
                json.dumps(
                    {
                        "release_version": __version__,
                        "specification_version": SPEC_VERSION,
                    },
                    sort_keys=True,
                )
            )
            return 0

        if args.command == "hash-file":
            print(file_sha256(Path(args.path)))
            return 0

        if args.command == "doctor":
            settings = load_settings(args.config)
            checks = run_health_checks(settings)
            payload = {
                "ok": required_checks_pass(checks),
                "configuration_hash": settings.configuration_hash(),
                "checks": [check.as_dict() for check in checks],
            }
            if args.as_json:
                print(json.dumps(payload, sort_keys=True))
            else:
                for check in checks:
                    status = "PASS" if check.ok else "FAIL"
                    requirement = "required" if check.required else "optional"
                    print(f"{status:4} {check.name} ({requirement}): {check.detail}")
            return 0 if payload["ok"] else 2

        if args.command == "manifest":
            settings = load_settings(args.config)
            release_manifest = build_release_manifest(settings)
            payload = release_manifest.model_dump(mode="json")
            payload["manifest_sha256"] = release_manifest.canonical_hash()
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0

        if args.command == "production-schema":
            schemas = {
                "policy": production_policy_schema,
                "artifact": artifact_evidence_schema,
                "manifest": evidence_manifest_schema,
                "build": build_attestation_schema,
                "freeze": configuration_freeze_schema,
                "finding": review_finding_schema,
                "approval": approval_attestation_schema,
                "rollback": rollback_evidence_schema,
                "request": production_candidate_request_schema,
                "report": production_candidate_report_schema,
            }
            rendered = json.dumps(schemas[args.kind](), ensure_ascii=False, sort_keys=True) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "production-evidence-manifest":
            files = {}
            for item in args.file:
                if "=" not in item:
                    raise ValueError("--file must use canonical_name=/path/to/file")
                name, raw_path = item.split("=", 1)
                if not name or not raw_path or name in files:
                    raise ValueError("artifact names and paths must be nonempty and unique")
                files[name] = raw_path
            evidence_manifest = build_evidence_manifest(files)
            rendered = release_canonical_json_text(evidence_manifest) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "production-freeze":
            settings = load_settings(args.config)
            components = {
                "analytics_engine": "0.8.0",
                "contracts": "0.1.0",
                "evaluator": "0.3.0",
                "execution_engine": "0.5.0",
                "feature_engine": "0.2.0",
                "operations_engine": "0.7.0",
                "orchestration_engine": "0.6.0",
                "platform": "1.0.2",
                "recorder": "0.2.0",
                "release_engine": "1.0.2",
                "risk_engine": "0.4.0",
            }
            configuration_freeze = build_configuration_freeze(
                settings,
                specification_path=settings.paths.spec_path,
                component_versions=components,
            )
            rendered = release_canonical_json_text(configuration_freeze) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "production-review":
            production_request = ProductionCandidateRequest.model_validate_json(
                Path(args.request_path).read_text(encoding="utf-8")
            )
            production_report = review_production_candidate(production_request)
            rendered = release_canonical_json_text(production_report) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if production_report.paper_release_candidate else 14

        if args.command == "analytics-schema":
            schemas = {
                "policy": analytics_policy_schema,
                "session-evidence": session_evidence_schema,
                "session-performance": session_performance_schema,
                "replay-request": replay_request_schema,
                "replay-report": replay_report_schema,
                "ledger-request": paper_acceptance_request_schema,
                "ledger": paper_acceptance_ledger_schema,
                "deployment-request": deployment_evidence_request_schema,
                "deployment-report": deployment_evidence_report_schema,
            }
            rendered = json.dumps(schemas[args.kind](), ensure_ascii=False, sort_keys=True) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "analytics-session":
            evidence = SessionEvidence.model_validate_json(
                Path(args.evidence_path).read_text(encoding="utf-8")
            )
            session_performance = analyze_session(evidence)
            rendered = analytics_canonical_json_text(session_performance) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "analytics-replay-report":
            replay_request = FullSessionReplayRequest.model_validate_json(
                Path(args.request_path).read_text(encoding="utf-8")
            )
            replay_report = build_full_session_replay_report(replay_request)
            rendered = analytics_canonical_json_text(replay_report) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if replay_report.passed else 11

        if args.command == "analytics-paper-ledger":
            paper_request = PaperAcceptanceRequest.model_validate_json(
                Path(args.request_path).read_text(encoding="utf-8")
            )
            paper_ledger = build_paper_acceptance_ledger(paper_request)
            rendered = analytics_canonical_json_text(paper_ledger) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if paper_ledger.paper_ready else 12

        if args.command == "analytics-deployment-report":
            deployment_request = DeploymentEvidenceRequest.model_validate_json(
                Path(args.request_path).read_text(encoding="utf-8")
            )
            deployment_report = build_deployment_evidence_report(deployment_request)
            rendered = analytics_canonical_json_text(deployment_report) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if deployment_report.paper_deployment_ready else 13

        if args.command == "operations-schema":
            schemas = {
                "policy": operations_policy_schema,
                "observability": observability_snapshot_schema,
                "restart-state": restart_state_schema,
                "recovery-plan": recovery_plan_schema,
                "backup": backup_manifest_schema,
                "restore": restore_validation_schema,
                "drill": drill_result_schema,
                "acceptance": target_acceptance_schema,
            }
            rendered = json.dumps(schemas[args.kind](), ensure_ascii=False, sort_keys=True) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "operations-recovery-plan":
            state = RestartState.model_validate_json(
                Path(args.state_path).read_text(encoding="utf-8")
            )
            recovery_plan = build_recovery_plan(state)
            rendered = operations_canonical_json_text(recovery_plan) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "operations-observability":
            settings = load_settings(args.config)
            metrics = json.loads(Path(args.metrics_path).read_text(encoding="utf-8"))
            observability = build_observability_snapshot(
                metrics=metrics,
                configuration_hash=settings.configuration_hash(),
                session_id=args.session_id,
                policy=_operations_policy(settings),
            )
            rendered = operations_canonical_json_text(observability) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if observability.healthy else 9

        if args.command == "operations-backup-manifest":
            backup_manifest = build_backup_manifest(
                args.artifact_path,
                source_database=args.source_database,
                schema_revision=args.schema_revision,
                table_counts=json.loads(args.table_counts),
                encrypted=args.encrypted,
                complete=args.complete,
            )
            rendered = operations_canonical_json_text(backup_manifest) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "operations-restore-validate":
            backup_to_restore = BackupManifest.model_validate_json(
                Path(args.manifest_path).read_text(encoding="utf-8")
            )
            restore_validation = validate_restore(
                backup_to_restore,
                target_database=args.target_database,
                restored_schema_revision=args.schema_revision,
                restored_table_counts=json.loads(args.table_counts),
                replay_probe=lambda: args.replay_verified,
            )
            rendered = operations_canonical_json_text(restore_validation) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if restore_validation.passed else 10

        if args.command == "operations-drill-simulate":
            if not args.confirm_simulation:
                raise ConfigurationError("--confirm-simulation is required")
            drill_result = run_failure_drill(
                DrillType(args.kind),
                inject_failure=lambda: None,
                detect_failure=lambda: True,
                entries_blocked=lambda: True,
                recovery_probe=lambda: True,
                kill_switch_probe=lambda: True,
            )
            rendered = operations_canonical_json_text(drill_result) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if drill_result.status.value == "passed" else 11

        if args.command == "operations-acceptance":
            settings = load_settings(args.config)
            operations_probes: dict[str, Probe] = {}
            paper_operations: AlpacaPaperOperations | None = None
            if args.online_paper:
                if not args.confirm_paper:
                    raise ConfigurationError("--confirm-paper is required with --online-paper")
                api_key = os.environ.get(settings.execution.api_key_env)
                secret_key = os.environ.get(settings.execution.secret_key_env)
                if not api_key or not secret_key:
                    raise ConfigurationError("missing Alpaca paper credentials")
                paper_operations = AlpacaPaperOperations(
                    api_key=api_key,
                    secret_key=secret_key,
                    base_url=settings.execution.base_url,
                    timeout_seconds=settings.execution.request_timeout_seconds,
                )
                operations_probes["alpaca_account"] = paper_operations.account_probe
                operations_probes["alpaca_clock"] = paper_operations.clock_probe
                operations_probes["system_ntp"] = system_ntp_probe
                dsn = (
                    os.environ.get(settings.database.dsn_env) if settings.database.enabled else None
                )
                if dsn:
                    operations_probes["postgresql"] = _database_probe(dsn)
                    operations_probes["migration_head"] = _migration_head_probe(dsn)
            try:
                restore_value = (
                    RestoreValidation.model_validate_json(
                        Path(args.restore_validation).read_text(encoding="utf-8")
                    )
                    if args.restore_validation
                    else None
                )
                recovery_value = (
                    RecoveryPlan.model_validate_json(
                        Path(args.recovery_plan).read_text(encoding="utf-8")
                    )
                    if args.recovery_plan
                    else None
                )
                drills = tuple(
                    DrillResult.model_validate_json(Path(path).read_text(encoding="utf-8"))
                    for path in args.drill_result
                )
                target_acceptance = build_target_acceptance_report(
                    configuration_hash=settings.configuration_hash(),
                    state_dir=args.state_dir or settings.paths.state_dir,
                    policy=_operations_policy(settings),
                    probes=operations_probes,
                    restore_validation=restore_value,
                    recovery_plan=recovery_value,
                    drill_results=drills,
                )
            finally:
                if paper_operations is not None:
                    paper_operations.close()
            rendered = operations_canonical_json_text(target_acceptance) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if target_acceptance.paper_ready else 12

        if args.command == "orchestration-schema":
            schemas = {
                "policy": orchestration_policy_schema,
                "plan": session_plan_schema,
                "health": health_snapshot_schema,
                "flatten": flatten_result_schema,
                "acceptance": acceptance_report_schema,
                "result": session_result_schema,
            }
            rendered = json.dumps(schemas[args.kind](), ensure_ascii=False, sort_keys=True) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "orchestration-plan":
            settings = load_settings(args.config)
            plan = build_session_plan(
                trading_date=date.fromisoformat(args.trading_date),
                run_id=args.run_id or uuid4().hex,
                configuration_hash=settings.configuration_hash(),
                policy=_orchestration_policy(settings),
            )
            rendered = orchestration_canonical_json_text(plan) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "paper-emergency-flatten":
            if not args.confirm_paper:
                raise ConfigurationError("--confirm-paper is required for emergency flatten")
            settings = load_settings(args.config)
            if not settings.execution.enabled or not settings.orchestration.enabled:
                raise ConfigurationError(
                    "execution.enabled and orchestration.enabled must both be true"
                )
            api_key = os.environ.get(settings.execution.api_key_env)
            secret_key = os.environ.get(settings.execution.secret_key_env)
            if not api_key or not secret_key:
                raise ConfigurationError("missing Alpaca paper credentials")
            plan = build_session_plan(
                trading_date=date.fromisoformat(args.trading_date),
                run_id=args.run_id,
                configuration_hash=settings.configuration_hash(),
                policy=_orchestration_policy(settings),
            )
            orchestration_repository: OrchestrationRepository = MemoryOrchestrationRepository()
            if settings.database.enabled:
                dsn = os.environ.get(settings.database.dsn_env)
                if not dsn:
                    raise ConfigurationError(
                        f"Database enabled but {settings.database.dsn_env} is missing"
                    )
                orchestration_repository = PostgresOrchestrationRepository(dsn)
            orchestration_repository.save_plan(plan)
            now = datetime.now(UTC)
            kill_switch = activate_kill_switch(
                plan.session_id,
                KillSwitchReason.MANUAL,
                now=now,
                details={"source": "paper-emergency-flatten CLI"},
            )
            orchestration_repository.save_kill_switch(kill_switch)
            emergency_operations = AlpacaPaperOperations(
                api_key=api_key,
                secret_key=secret_key,
                base_url=settings.execution.base_url,
                timeout_seconds=settings.execution.request_timeout_seconds,
            )
            try:
                flatten_result = FlattenService(emergency_operations).flatten(plan, now=now)
            finally:
                emergency_operations.close()
            orchestration_repository.save_flatten(flatten_result)
            rendered = (
                orchestration_canonical_json_text(
                    {
                        "kill_switch": kill_switch,
                        "flatten_result": flatten_result,
                    }
                )
                + "\n"
            )
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if flatten_result.complete else 8

        if args.command == "dashboard-snapshot":
            settings = load_settings(args.config)
            trading_date_value = date.fromisoformat(args.trading_date)
            run_id = args.run_id or args.session_id
            if not settings.database.enabled:
                raise ConfigurationError(
                    "database.enabled must be true to export a dashboard snapshot"
                )
            dsn = os.environ.get(settings.database.dsn_env)
            if not dsn:
                raise ConfigurationError(
                    f"Database enabled but {settings.database.dsn_env} is missing"
                )
            snapshot_orchestration_repository = PostgresOrchestrationRepository(dsn)
            snapshot_risk_repository = PostgresRiskRepository(dsn)
            snapshot_evaluator_repository = PostgresEvaluatorRepository(dsn)
            snapshot_analytics_repository = PostgresAnalyticsRepository(dsn)
            snapshot_operations_repository = PostgresOperationsRepository(dsn)
            snapshot_release_repository = PostgresReleaseRepository(dsn)

            candidate_report = snapshot_release_repository.get_latest_candidate_report()
            build_attestation = (
                snapshot_release_repository.get_build_attestation(
                    candidate_report.build_attestation_hash
                )
                if candidate_report is not None
                else None
            )

            positions: tuple[BrokerPositionSnapshot, ...] = ()
            orders: tuple[BrokerOrderSnapshot, ...] = ()
            account: dict[str, Any] = {}
            market_status_normal: bool | None = None
            if args.include_broker:
                api_key = os.environ.get(settings.execution.api_key_env)
                secret_key = os.environ.get(settings.execution.secret_key_env)
                if not api_key or not secret_key:
                    raise ConfigurationError(
                        "missing Alpaca paper credentials for --include-broker"
                    )
                snapshot_broker = AlpacaPaperBroker(
                    api_key=api_key,
                    secret_key=secret_key,
                    base_url=settings.execution.base_url,
                    timeout_seconds=settings.execution.request_timeout_seconds,
                )
                snapshot_operations = AlpacaPaperOperations(
                    api_key=api_key,
                    secret_key=secret_key,
                    base_url=settings.execution.base_url,
                    timeout_seconds=settings.execution.request_timeout_seconds,
                )
                try:
                    positions = snapshot_broker.list_positions()
                    orders = snapshot_broker.list_orders(status="all")
                    account = snapshot_operations.get_account()
                    market_status_normal = bool(snapshot_operations.get_clock().get("is_open"))
                finally:
                    snapshot_broker.close()
                    snapshot_operations.close()

            sources = DashboardSnapshotSources(
                session_id=args.session_id,
                trading_date=trading_date_value,
                kill_switch=snapshot_orchestration_repository.get_latest_kill_switch(
                    args.session_id
                ),
                phases=snapshot_orchestration_repository.list_phases(args.session_id),
                alerts=snapshot_orchestration_repository.list_alerts(args.session_id),
                decisions=snapshot_risk_repository.list_decisions(trading_date_value),
                run_result=snapshot_evaluator_repository.get_result(run_id),
                session_performance=snapshot_analytics_repository.get_session_performance(
                    args.session_id
                ),
                paper_ledger=snapshot_analytics_repository.get_latest_paper_ledger(),
                observability=snapshot_operations_repository.get_latest_observability(),
                candidate_report=candidate_report,
                build_attestation=build_attestation,
                positions=positions,
                orders=orders,
                account=account,
                market_status_normal=market_status_normal,
            )
            dashboard_payload = build_dashboard_snapshot(sources)
            rendered = json.dumps(dashboard_payload, ensure_ascii=False, sort_keys=True) + "\n"
            Path(args.output).write_text(rendered, encoding="utf-8")
            print(
                f"daybreak: wrote a private dashboard snapshot to {args.output}. "
                "It may contain real account data: never commit it, and load it only via "
                "the dashboard's 'Load private snapshot' control.",
                file=sys.stderr,
            )
            return 0

        if args.command == "acceptance-check":
            settings = load_settings(args.config)
            acceptance_probes: dict[str, Probe] = {}
            acceptance_operations: AlpacaPaperOperations | None = None
            if args.online_paper:
                if not args.confirm_paper:
                    raise ConfigurationError("--confirm-paper is required with --online-paper")
                api_key = os.environ.get(settings.execution.api_key_env)
                secret_key = os.environ.get(settings.execution.secret_key_env)
                if not api_key or not secret_key:
                    raise ConfigurationError("missing Alpaca paper credentials")
                acceptance_operations = AlpacaPaperOperations(
                    api_key=api_key,
                    secret_key=secret_key,
                    base_url=settings.execution.base_url,
                    timeout_seconds=settings.execution.request_timeout_seconds,
                )
                acceptance_probes["alpaca_account"] = acceptance_operations.account_probe
                acceptance_probes["alpaca_clock"] = acceptance_operations.clock_probe
                if settings.safety.require_ntp_sync:
                    acceptance_probes["system_ntp"] = system_ntp_probe
                if settings.database.enabled:
                    dsn = os.environ.get(settings.database.dsn_env)
                    if dsn:
                        acceptance_probes["postgresql"] = _database_probe(dsn)
            try:
                acceptance_report = build_acceptance_report(settings, probes=acceptance_probes)
            finally:
                if acceptance_operations is not None:
                    acceptance_operations.close()
            if settings.database.enabled:
                dsn = os.environ.get(settings.database.dsn_env)
                if dsn:
                    try:
                        PostgresOrchestrationRepository(dsn).save_acceptance(acceptance_report)
                    except Exception as exc:
                        print(
                            f"daybreak: unable to persist acceptance report: {exc}", file=sys.stderr
                        )
            rendered = orchestration_canonical_json_text(acceptance_report) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if acceptance_report.paper_ready else 7

        if args.command == "validate-contract":
            input_payload = json.loads(Path(args.input_path).read_text(encoding="utf-8"))
            output_payload = json.loads(Path(args.output_path).read_text(encoding="utf-8"))
            validation_report = validate_daybreak_run(input_payload, output_payload)
            print(validation_report.model_dump_json())
            return 0 if validation_report.valid else 3

        if args.command == "build-features":
            context = FeatureContext.model_validate_json(
                Path(args.context_path).read_text(encoding="utf-8")
            )
            snapshot = build_feature_snapshot(context)
            rendered = canonical_json_text(snapshot) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "evaluator-schema":
            rendered = (
                json.dumps(daybreak_output_json_schema(), ensure_ascii=False, sort_keys=True) + "\n"
            )
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "risk-schema":
            schemas = {
                "request": risk_sizing_request_schema,
                "decision": risk_decision_schema,
                "batch-request": batch_sizing_request_schema,
                "batch-result": batch_sizing_result_schema,
            }
            rendered = json.dumps(schemas[args.kind](), ensure_ascii=False, sort_keys=True) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "risk-size":
            sizing_request = SizingRequest.model_validate_json(
                Path(args.request_path).read_text(encoding="utf-8")
            )
            decision = size_position(sizing_request)
            rendered = risk_canonical_json_text(decision) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if decision.decision.value == "approved" else 5

        if args.command == "risk-size-batch":
            batch_request = BatchSizingRequest.model_validate_json(
                Path(args.request_path).read_text(encoding="utf-8")
            )
            batch_result = size_approved_batch(batch_request)
            rendered = risk_canonical_json_text(batch_result) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "execution-schema":
            schemas = {
                "policy": execution_policy_schema,
                "request": execution_request_schema,
                "command": broker_order_command_schema,
                "result": execution_result_schema,
                "trade-update": trade_update_schema,
                "reconciliation": reconciliation_report_schema,
            }
            rendered = json.dumps(schemas[args.kind](), ensure_ascii=False, sort_keys=True) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "execution-build-order":
            execution_request = ExecutionRequest.model_validate_json(
                Path(args.request_path).read_text(encoding="utf-8")
            )
            command = build_entry_command(execution_request, now=execution_request.requested_at)
            rendered = execution_canonical_json_text(command) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0

        if args.command == "execution-submit-paper":
            if not args.confirm_paper:
                raise ConfigurationError("--confirm-paper is required for paper submission")
            settings = load_settings(args.config)
            if not settings.execution.enabled:
                raise ConfigurationError("execution.enabled must be true")
            execution_request = ExecutionRequest.model_validate_json(
                Path(args.request_path).read_text(encoding="utf-8")
            )
            api_key = os.environ.get(settings.execution.api_key_env)
            secret_key = os.environ.get(settings.execution.secret_key_env)
            if not api_key or not secret_key:
                raise ConfigurationError("missing Alpaca paper credentials")
            broker = AlpacaPaperBroker(
                api_key=api_key,
                secret_key=secret_key,
                base_url=settings.execution.base_url,
                timeout_seconds=settings.execution.request_timeout_seconds,
            )
            try:
                execution_repository: ExecutionRepository = MemoryExecutionRepository()
                reservation_sink: ReservationEventSink = NullReservationEventSink()
                if settings.database.enabled:
                    dsn = os.environ.get(settings.database.dsn_env)
                    if not dsn:
                        raise ConfigurationError(
                            f"Database enabled but {settings.database.dsn_env} is missing"
                        )
                    execution_repository = PostgresExecutionRepository(dsn)
                    reservation_sink = PostgresReservationEventSink(dsn)
                execution_service = ExecutionService(
                    broker=broker,
                    repository=execution_repository,
                    reservation_events=reservation_sink,
                )
                execution_result = execution_service.submit(execution_request)
            finally:
                broker.close()
            rendered = execution_canonical_json_text(execution_result) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return (
                0 if execution_result.outcome.value in {"submitted", "existing_reconciled"} else 6
            )

        if args.command == "evaluate":
            settings = load_settings(args.config)
            evaluator_payload, evaluator_evidence = _load_evaluator_input(
                Path(args.input_path), settings.configuration_hash()
            )
            requested_at = datetime.now(UTC)
            cutoff = (
                _parse_iso_timestamp(args.cutoff)
                if args.cutoff
                else _configured_cutoff(
                    evaluator_payload, settings.evaluator.response_cutoff_time_et
                )
            )
            evaluation_request = EvaluationRequest(
                run_id=args.run_id or uuid4().hex,
                input_payload=evaluator_payload,
                evidence=evaluator_evidence,
                requested_at=requested_at,
                response_cutoff_timestamp=cutoff,
            )
            api_key = os.environ.get(settings.evaluator.api_key_env)
            if not api_key:
                raise ConfigurationError(
                    f"Missing OpenAI API key environment variable: {settings.evaluator.api_key_env}"
                )
            policy = EvaluatorPolicy(
                primary_model=settings.evaluator.primary_model,
                shadow_model=settings.evaluator.shadow_model,
                reasoning_effort=settings.evaluator.reasoning_effort,
                max_output_tokens=settings.evaluator.max_output_tokens,
                max_attempts=settings.evaluator.max_attempts,
                max_evaluator_candidates_hard=settings.features.hard_max_evaluator_candidates,
                request_timeout_seconds=settings.evaluator.request_timeout_seconds,
                shadow_timeout_seconds=settings.evaluator.shadow_timeout_seconds,
                store_raw_provider_response=settings.evaluator.store_raw_provider_response,
            )
            evaluator_repository: EvaluatorRepository = NullEvaluatorRepository()
            if settings.database.enabled:
                dsn = os.environ.get(settings.database.dsn_env)
                if not dsn:
                    raise ConfigurationError(
                        f"Database enabled but {settings.database.dsn_env} is missing"
                    )
                evaluator_repository = PostgresEvaluatorRepository(dsn)
            evaluator_service = EvaluatorService(
                transport=OpenAIResponsesTransport(api_key=api_key),
                spec_path=str(settings.paths.spec_path),
                policy=policy,
                repository=evaluator_repository,
            )
            evaluation_result = asyncio.run(
                evaluator_service.evaluate(
                    evaluation_request,
                    run_shadow=settings.evaluator.run_shadow and args.await_shadow,
                )
            )
            rendered = (
                json.dumps(
                    evaluation_result.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                sys.stdout.write(rendered)
            return 0 if evaluation_result.status.value == "primary_valid" else 4

        return 64
    except (ConfigurationError, FileNotFoundError, ValueError) as exc:
        print(f"daybreak: {exc}", file=sys.stderr)
        return 2
