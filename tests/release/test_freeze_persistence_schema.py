from datetime import timedelta
from pathlib import Path

import pytest

from daybreak.core.config import load_settings
from daybreak_release.freeze import build_configuration_freeze
from daybreak_release.persistence import MemoryReleaseRepository
from daybreak_release.review import review_production_candidate
from daybreak_release.schema import production_candidate_report_schema

from .helpers import NOW, make_request


def test_freeze_requires_paper_environment(tmp_path: Path):
    config = tmp_path / "daybreak.toml"
    original = Path("config/daybreak.example.toml").read_text(encoding="utf-8")
    config.write_text(
        original.replace('environment = "development"', 'environment = "paper"'), encoding="utf-8"
    )
    settings = load_settings(config)
    value = build_configuration_freeze(
        settings,
        specification_path="docs/spec/Project_Daybreak_v6.3_Final.md",
        component_versions={"platform": "1.0.2"},
    )
    assert value.environment == "paper"
    assert value.live_execution_enabled is False


def test_freeze_rejects_development_environment():
    settings = load_settings("config/daybreak.example.toml")
    with pytest.raises(ValueError, match="paper environment"):
        build_configuration_freeze(
            settings,
            specification_path="docs/spec/Project_Daybreak_v6.3_Final.md",
            component_versions={"platform": "1.0.2"},
        )


def test_memory_repository_is_idempotent():
    request = make_request()
    report = review_production_candidate(request)
    repo = MemoryReleaseRepository()
    repo.save_evidence_manifest(request.evidence_manifest)
    repo.save_evidence_manifest(request.evidence_manifest)
    repo.save_candidate_report(report)
    repo.save_candidate_report(report)
    assert len(repo.evidence_manifests) == 1
    assert len(repo.candidate_reports) == 1


def test_report_schema_is_strict_object():
    schema = production_candidate_report_schema()
    assert schema["additionalProperties"] is False
    assert "live_capital_eligible" in schema["properties"]


def test_get_latest_candidate_report_and_build_attestation():
    request = make_request()
    report = review_production_candidate(request)
    repo = MemoryReleaseRepository()
    assert repo.get_latest_candidate_report() is None
    assert repo.get_build_attestation(request.build_attestation.attestation_hash) is None

    repo.save_evidence_manifest(request.evidence_manifest)
    repo.save_build_attestation(request.build_attestation)
    repo.save_candidate_report(report)

    assert repo.get_latest_candidate_report() == report
    assert (
        repo.get_build_attestation(request.build_attestation.attestation_hash)
        == request.build_attestation
    )
    assert repo.get_build_attestation("f" * 64) is None

    later_request = make_request(generated_at=NOW + timedelta(days=1))
    later_report = review_production_candidate(later_request)
    repo.save_build_attestation(later_request.build_attestation)
    repo.save_candidate_report(later_report)
    assert repo.get_latest_candidate_report() == later_report


def test_phase9_migration_exists_and_is_append_only():
    text = Path("migrations/versions/0009_phase9_release.py").read_text(encoding="utf-8")
    assert 'revision = "0009_phase9_release"' in text
    assert 'down_revision = "0008_phase8_analytics"' in text
    assert "append-only" in text
