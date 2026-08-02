from __future__ import annotations

from .models import (
    AcceptanceReport,
    FlattenResult,
    HealthSnapshot,
    OrchestrationPolicy,
    SessionPlan,
    SessionResult,
)


def orchestration_policy_schema() -> dict[str, object]:
    return OrchestrationPolicy.model_json_schema()


def session_plan_schema() -> dict[str, object]:
    return SessionPlan.model_json_schema()


def health_snapshot_schema() -> dict[str, object]:
    return HealthSnapshot.model_json_schema()


def flatten_result_schema() -> dict[str, object]:
    return FlattenResult.model_json_schema()


def acceptance_report_schema() -> dict[str, object]:
    return AcceptanceReport.model_json_schema()


def session_result_schema() -> dict[str, object]:
    return SessionResult.model_json_schema()
