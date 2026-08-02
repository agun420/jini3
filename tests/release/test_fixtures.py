from __future__ import annotations

from pathlib import Path

from daybreak_release.models import ProductionCandidateReport, ProductionCandidateRequest
from daybreak_release.review import review_production_candidate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "release"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_release_fixtures_are_current_and_reproducible():
    for suffix in ("", "_blocked"):
        request = ProductionCandidateRequest.model_validate_json(
            _read(f"production_candidate_request{suffix}.json")
        )
        report = ProductionCandidateReport.model_validate_json(
            _read(f"production_candidate_report{suffix}.json")
        )
        assert review_production_candidate(request) == report
