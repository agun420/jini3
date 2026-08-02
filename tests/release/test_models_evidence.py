from datetime import UTC, datetime
from pathlib import Path

import pytest

from daybreak_release.evidence import build_evidence_manifest
from daybreak_release.models import ArtifactEvidence, EvidenceManifest, ProductionCandidateRequest

from .helpers import make_request


def test_request_round_trip():
    request = make_request()
    assert ProductionCandidateRequest.model_validate_json(request.model_dump_json()) == request


def test_manifest_builder_hashes_real_files(tmp_path: Path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    value = build_evidence_manifest(
        {"source_archive": first, "wheel": second},
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert [item.name for item in value.artifacts] == ["source_archive", "wheel"]
    assert len(value.manifest_hash) == 64


def test_manifest_allows_distinct_artifacts_with_identical_content():
    artifacts = (
        ArtifactEvidence(name="source_archive", sha256="a" * 64, size_bytes=1),
        ArtifactEvidence(name="wheel", sha256="a" * 64, size_bytes=2),
    )
    manifest = EvidenceManifest(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        artifacts=artifacts,
        manifest_hash="b" * 64,
    )
    assert len(manifest.artifacts) == 2


def test_request_rejects_manifest_build_mismatch():
    request = make_request()
    build = request.build_attestation.model_copy(update={"wheel_sha256": "8" * 64})
    with pytest.raises(ValueError, match="evidence manifest hash mismatch for wheel"):
        ProductionCandidateRequest(
            **request.model_dump(mode="python", exclude={"build_attestation"}),
            build_attestation=build,
        )
