from datetime import UTC, datetime

from daybreak_operations.backup import build_backup_manifest, validate_restore

NOW = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)


def test_backup_manifest_and_restore_validation(tmp_path):
    artifact = tmp_path / "daybreak.dump"
    artifact.write_bytes(b"deterministic-backup")
    manifest = build_backup_manifest(
        artifact,
        source_database="daybreak",
        schema_revision="0007",
        table_counts={"raw_events": 10, "sessions": 1},
        encrypted=True,
        complete=True,
        created_at=NOW,
    )
    validation = validate_restore(
        manifest,
        target_database="daybreak_restore",
        restored_schema_revision="0007",
        restored_table_counts={"sessions": 1, "raw_events": 10},
        replay_probe=lambda: True,
        restored_at=NOW,
    )
    assert validation.passed is True


def test_tampered_backup_fails_hash(tmp_path):
    artifact = tmp_path / "daybreak.dump"
    artifact.write_bytes(b"first")
    manifest = build_backup_manifest(
        artifact,
        source_database="daybreak",
        schema_revision="0007",
        table_counts={"raw_events": 1},
        encrypted=True,
        complete=True,
        created_at=NOW,
    )
    artifact.write_bytes(b"tampered")
    validation = validate_restore(
        manifest,
        target_database="restore",
        restored_schema_revision="0007",
        restored_table_counts={"raw_events": 1},
        replay_probe=lambda: True,
        restored_at=NOW,
    )
    assert validation.passed is False
    assert "ARTIFACT_HASH_MISMATCH" in validation.errors


def test_incomplete_backup_cannot_pass(tmp_path):
    artifact = tmp_path / "daybreak.dump"
    artifact.write_bytes(b"content")
    manifest = build_backup_manifest(
        artifact,
        source_database="daybreak",
        schema_revision="0007",
        table_counts={},
        encrypted=False,
        complete=False,
        created_at=NOW,
    )
    validation = validate_restore(
        manifest,
        target_database="restore",
        restored_schema_revision="0007",
        restored_table_counts={},
        replay_probe=lambda: True,
        restored_at=NOW,
    )
    assert validation.passed is False
    assert "BACKUP_MARKED_INCOMPLETE" in validation.errors
