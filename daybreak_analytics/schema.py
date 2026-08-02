from typing import Any

from .models import (
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


def analytics_policy_schema() -> dict[str, Any]:
    return AnalyticsPolicy.model_json_schema()


def session_evidence_schema() -> dict[str, Any]:
    return SessionEvidence.model_json_schema()


def session_performance_schema() -> dict[str, Any]:
    return SessionPerformance.model_json_schema()


def replay_request_schema() -> dict[str, Any]:
    return FullSessionReplayRequest.model_json_schema()


def replay_report_schema() -> dict[str, Any]:
    return FullSessionReplayReport.model_json_schema()


def paper_acceptance_request_schema() -> dict[str, Any]:
    return PaperAcceptanceRequest.model_json_schema()


def paper_acceptance_ledger_schema() -> dict[str, Any]:
    return PaperAcceptanceLedger.model_json_schema()


def deployment_evidence_request_schema() -> dict[str, Any]:
    return DeploymentEvidenceRequest.model_json_schema()


def deployment_evidence_report_schema() -> dict[str, Any]:
    return DeploymentEvidenceReport.model_json_schema()
