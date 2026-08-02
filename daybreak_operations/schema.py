from typing import Any

from .models import (
    BackupManifest,
    DrillResult,
    ObservabilitySnapshot,
    OperationsPolicy,
    RecoveryPlan,
    RestartState,
    RestoreValidation,
    TargetAcceptanceReport,
)


def operations_policy_schema() -> dict[str, Any]:
    return OperationsPolicy.model_json_schema()


def observability_snapshot_schema() -> dict[str, Any]:
    return ObservabilitySnapshot.model_json_schema()


def restart_state_schema() -> dict[str, Any]:
    return RestartState.model_json_schema()


def recovery_plan_schema() -> dict[str, Any]:
    return RecoveryPlan.model_json_schema()


def backup_manifest_schema() -> dict[str, Any]:
    return BackupManifest.model_json_schema()


def restore_validation_schema() -> dict[str, Any]:
    return RestoreValidation.model_json_schema()


def drill_result_schema() -> dict[str, Any]:
    return DrillResult.model_json_schema()


def target_acceptance_schema() -> dict[str, Any]:
    return TargetAcceptanceReport.model_json_schema()
