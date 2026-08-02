from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from daybreak.core.hashing import file_sha256

from .canonical import canonical_sha256
from .models import ArtifactEvidence, EvidenceManifest


def build_evidence_manifest(
    files: Mapping[str, str | Path],
    *,
    generated_at: datetime | None = None,
) -> EvidenceManifest:
    timestamp = generated_at or datetime.now(UTC)
    artifacts = []
    for name, raw_path in sorted(files.items()):
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        artifacts.append(
            ArtifactEvidence(
                name=name,
                sha256=file_sha256(path),
                size_bytes=path.stat().st_size,
                required=True,
            )
        )
    body = {"generated_at": timestamp, "artifacts": tuple(artifacts)}
    return EvidenceManifest.model_validate({**body, "manifest_hash": canonical_sha256(body)})
