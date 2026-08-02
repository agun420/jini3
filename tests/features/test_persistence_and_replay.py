import pytest

from daybreak_features.engine import build_feature_snapshot
from daybreak_features.persistence import InMemoryFeatureArtifactRepository
from daybreak_features.replay import replay_context

from .helpers import candidate, context


@pytest.mark.asyncio
async def test_context_snapshot_persistence_and_replay():
    repository = InMemoryFeatureArtifactRepository()
    ctx = context(candidate())
    context_hash = await repository.save_context(ctx)
    snapshot = build_feature_snapshot(ctx)
    await repository.save_snapshot(snapshot)

    result = await replay_context(
        repository,
        context_hash=context_hash,
        expected_snapshot_id=snapshot.snapshot_id,
    )
    assert result.byte_identical is True
    assert result.actual_snapshot_id == snapshot.snapshot_id


@pytest.mark.asyncio
async def test_missing_context_replay_fails():
    repository = InMemoryFeatureArtifactRepository()
    with pytest.raises(KeyError):
        await replay_context(repository, context_hash="0" * 64)


def test_phase2_migration_declares_append_only_tables():
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0002_phase2_features.py"
    ).read_text()
    assert "CREATE TABLE feature_contexts" in sql
    assert "CREATE TABLE feature_snapshots" in sql
    assert "feature_snapshots_append_only" in sql
