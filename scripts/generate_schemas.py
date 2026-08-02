from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daybreak_analytics.models import (
    AnalyticsPolicy,
    DeploymentEvidenceReport,
    DeploymentEvidenceRequest,
    FullSessionReplayReport,
    FullSessionReplayRequest,
    PaperAcceptanceLedger,
    PaperAcceptanceRequest,
    SessionEvidence,
    SessionPerformance,
)
from daybreak_contracts.input_models import DaybreakInput
from daybreak_contracts.output_models import DaybreakOutput
from daybreak_evaluator.models import (
    EvaluationAttempt,
    EvaluationRequest,
    EvaluationRunResult,
    ShadowComparison,
)
from daybreak_evaluator.schema import daybreak_output_json_schema
from daybreak_execution.models import (
    BrokerOrderCommand,
    ExecutionPolicy,
    ExecutionRequest,
    ExecutionResult,
    ReconciliationReport,
    TradeUpdate,
)
from daybreak_features.models import FeatureContext, FeatureSnapshot
from daybreak_operations.models import (
    BackupManifest,
    DrillResult,
    ObservabilitySnapshot,
    OperationsPolicy,
    RecoveryPlan,
    RestartState,
    RestoreValidation,
    TargetAcceptanceReport,
)
from daybreak_orchestration.models import (
    AcceptanceReport,
    FlattenResult,
    HealthSnapshot,
    OrchestrationPolicy,
    SessionPlan,
    SessionResult,
)
from daybreak_recorder.models import (
    IngestSession,
    RawEvent,
    RawIngestFailure,
    SubscriptionManifest,
)
from daybreak_release.models import (
    ApprovalAttestation,
    ArtifactEvidence,
    BuildAttestation,
    ConfigurationFreeze,
    EvidenceManifest,
    ProductionCandidatePolicy,
    ProductionCandidateReport,
    ProductionCandidateRequest,
    ReviewFinding,
    RollbackEvidence,
)
from daybreak_risk.models import (
    BatchSizingRequest,
    BatchSizingResult,
    RiskDecision,
    RiskPolicyConfig,
    SizingRequest,
)

SCHEMAS = {
    "evaluator_input.schema.json": DaybreakInput,
    "evaluator_output.schema.json": DaybreakOutput,
    "raw_event.schema.json": RawEvent,
    "raw_ingest_failure.schema.json": RawIngestFailure,
    "subscription_manifest.schema.json": SubscriptionManifest,
    "ingest_session.schema.json": IngestSession,
    "feature_context.schema.json": FeatureContext,
    "feature_snapshot.schema.json": FeatureSnapshot,
    "evaluation_request.schema.json": EvaluationRequest,
    "evaluation_attempt.schema.json": EvaluationAttempt,
    "evaluation_run_result.schema.json": EvaluationRunResult,
    "shadow_comparison.schema.json": ShadowComparison,
    "risk_policy.schema.json": RiskPolicyConfig,
    "risk_sizing_request.schema.json": SizingRequest,
    "risk_decision.schema.json": RiskDecision,
    "risk_batch_request.schema.json": BatchSizingRequest,
    "risk_batch_result.schema.json": BatchSizingResult,
    "execution_policy.schema.json": ExecutionPolicy,
    "execution_request.schema.json": ExecutionRequest,
    "execution_order_command.schema.json": BrokerOrderCommand,
    "execution_result.schema.json": ExecutionResult,
    "execution_trade_update.schema.json": TradeUpdate,
    "execution_reconciliation.schema.json": ReconciliationReport,
    "orchestration_policy.schema.json": OrchestrationPolicy,
    "orchestration_session_plan.schema.json": SessionPlan,
    "orchestration_health_snapshot.schema.json": HealthSnapshot,
    "orchestration_flatten_result.schema.json": FlattenResult,
    "orchestration_acceptance_report.schema.json": AcceptanceReport,
    "orchestration_session_result.schema.json": SessionResult,
    "operations_policy.schema.json": OperationsPolicy,
    "operations_observability.schema.json": ObservabilitySnapshot,
    "operations_restart_state.schema.json": RestartState,
    "operations_recovery_plan.schema.json": RecoveryPlan,
    "operations_backup_manifest.schema.json": BackupManifest,
    "operations_restore_validation.schema.json": RestoreValidation,
    "operations_drill_result.schema.json": DrillResult,
    "operations_target_acceptance.schema.json": TargetAcceptanceReport,
    "analytics_policy.schema.json": AnalyticsPolicy,
    "analytics_session_evidence.schema.json": SessionEvidence,
    "analytics_session_performance.schema.json": SessionPerformance,
    "analytics_replay_request.schema.json": FullSessionReplayRequest,
    "analytics_replay_report.schema.json": FullSessionReplayReport,
    "analytics_paper_ledger_request.schema.json": PaperAcceptanceRequest,
    "analytics_paper_ledger.schema.json": PaperAcceptanceLedger,
    "analytics_deployment_request.schema.json": DeploymentEvidenceRequest,
    "analytics_deployment_report.schema.json": DeploymentEvidenceReport,
    "production_policy.schema.json": ProductionCandidatePolicy,
    "production_artifact_evidence.schema.json": ArtifactEvidence,
    "production_evidence_manifest.schema.json": EvidenceManifest,
    "production_build_attestation.schema.json": BuildAttestation,
    "production_configuration_freeze.schema.json": ConfigurationFreeze,
    "production_review_finding.schema.json": ReviewFinding,
    "production_approval_attestation.schema.json": ApprovalAttestation,
    "production_rollback_evidence.schema.json": RollbackEvidence,
    "production_candidate_request.schema.json": ProductionCandidateRequest,
    "production_candidate_report.schema.json": ProductionCandidateReport,
}


def main() -> int:
    destination = Path(__file__).resolve().parents[1] / "schemas"
    destination.mkdir(parents=True, exist_ok=True)
    for filename, model in SCHEMAS.items():
        path = destination / filename
        path.write_text(
            json.dumps(
                model.model_json_schema(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    (destination / "evaluator_provider_output.schema.json").write_text(
        json.dumps(daybreak_output_json_schema(), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
