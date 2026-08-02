from __future__ import annotations

from pathlib import Path

from daybreak_analytics.acceptance import (
    build_deployment_evidence_report,
    build_paper_acceptance_ledger,
)
from daybreak_analytics.analytics import analyze_session
from daybreak_analytics.models import (
    DeploymentEvidenceReport,
    DeploymentEvidenceRequest,
    FullSessionReplayReport,
    PaperAcceptanceLedger,
    PaperAcceptanceRequest,
    SessionEvidence,
    SessionPerformance,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "analytics"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_analytics_fixtures_are_current_and_reproducible():
    session = SessionEvidence.model_validate_json(_read("session_evidence.json"))
    performance = SessionPerformance.model_validate_json(_read("session_performance.json"))
    FullSessionReplayReport.model_validate_json(_read("replay_report.json"))
    ledger_request = PaperAcceptanceRequest.model_validate_json(_read("paper_ledger_request.json"))
    ledger = PaperAcceptanceLedger.model_validate_json(_read("paper_ledger.json"))
    deployment_request = DeploymentEvidenceRequest.model_validate_json(
        _read("deployment_request_offline.json")
    )
    deployment = DeploymentEvidenceReport.model_validate_json(
        _read("deployment_report_offline.json")
    )

    assert analyze_session(session) == performance
    assert build_paper_acceptance_ledger(ledger_request) == ledger
    assert build_deployment_evidence_report(deployment_request) == deployment
