from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .canonical import canonical_sha256
from .models import BackupManifest, RestoreValidation


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_backup_manifest(
    artifact_path: str | Path,
    *,
    source_database: str,
    schema_revision: str,
    table_counts: Mapping[str, int],
    encrypted: bool,
    complete: bool,
    created_at: datetime | None = None,
) -> BackupManifest:
    path = Path(artifact_path).resolve()
    created_at = (created_at or datetime.now(UTC)).astimezone(UTC)
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("backup artifact is empty")
    core = {
        "created_at": created_at,
        "source_database": source_database,
        "artifact_path": path,
        "artifact_size_bytes": size,
        "artifact_sha256": file_sha256(path),
        "schema_revision": schema_revision,
        "table_counts": tuple(
            sorted((str(name), int(count)) for name, count in table_counts.items())
        ),
        "encrypted": encrypted,
        "complete": complete,
    }
    manifest_hash = canonical_sha256(core)
    backup_id = uuid5(NAMESPACE_URL, f"daybreak-backup:{manifest_hash}").hex
    return BackupManifest.model_validate(
        {**core, "backup_id": backup_id, "manifest_hash": manifest_hash}
    )


def validate_restore(
    manifest: BackupManifest,
    *,
    target_database: str,
    restored_schema_revision: str,
    restored_table_counts: Mapping[str, int],
    replay_probe: Callable[[], bool],
    restored_at: datetime | None = None,
) -> RestoreValidation:
    restored_at = (restored_at or datetime.now(UTC)).astimezone(UTC)
    errors: list[str] = []
    artifact_hash_verified = (
        manifest.artifact_path.is_file()
        and file_sha256(manifest.artifact_path) == manifest.artifact_sha256
    )
    schema_revision_match = restored_schema_revision == manifest.schema_revision
    table_counts_match = tuple(sorted(restored_table_counts.items())) == manifest.table_counts
    try:
        replay_verified = bool(replay_probe())
    except Exception as exc:
        replay_verified = False
        errors.append(f"REPLAY_PROBE_FAILED:{type(exc).__name__}:{exc}")
    if not manifest.complete:
        errors.append("BACKUP_MARKED_INCOMPLETE")
    if not artifact_hash_verified:
        errors.append("ARTIFACT_HASH_MISMATCH")
    if not schema_revision_match:
        errors.append("SCHEMA_REVISION_MISMATCH")
    if not table_counts_match:
        errors.append("TABLE_COUNTS_MISMATCH")
    if not replay_verified and not any(item.startswith("REPLAY_PROBE_FAILED") for item in errors):
        errors.append("REPLAY_VERIFICATION_FAILED")
    passed = not errors
    core = {
        "backup_id": manifest.backup_id,
        "restored_at": restored_at,
        "target_database": target_database,
        "artifact_hash_verified": artifact_hash_verified,
        "schema_revision_match": schema_revision_match,
        "table_counts_match": table_counts_match,
        "replay_verified": replay_verified,
        "passed": passed,
        "errors": tuple(errors),
    }
    validation_hash = canonical_sha256(core)
    validation_id = uuid5(NAMESPACE_URL, f"daybreak-restore:{validation_hash}").hex
    return RestoreValidation.model_validate(
        {**core, "validation_id": validation_id, "validation_hash": validation_hash}
    )
