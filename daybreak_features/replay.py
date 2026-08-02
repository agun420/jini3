"""Feature-context replay and deterministic snapshot verification."""

from __future__ import annotations

from dataclasses import dataclass

from .canonical import canonical_json_bytes
from .engine import build_feature_snapshot
from .persistence import FeatureArtifactRepository


@dataclass(frozen=True, slots=True)
class FeatureReplayResult:
    context_hash: str
    expected_snapshot_id: str | None
    actual_snapshot_id: str
    byte_identical: bool | None


async def replay_context(
    repository: FeatureArtifactRepository,
    *,
    context_hash: str,
    expected_snapshot_id: str | None = None,
) -> FeatureReplayResult:
    context = await repository.get_context(context_hash)
    if context is None:
        raise KeyError(f"feature context not found: {context_hash}")
    actual = build_feature_snapshot(context)
    byte_identical: bool | None = None
    if expected_snapshot_id is not None:
        expected = await repository.get_snapshot(expected_snapshot_id)
        if expected is None:
            raise KeyError(f"feature snapshot not found: {expected_snapshot_id}")
        byte_identical = canonical_json_bytes(actual) == canonical_json_bytes(expected)
        if not byte_identical:
            raise ValueError("feature replay mismatch")
    return FeatureReplayResult(
        context_hash=context_hash,
        expected_snapshot_id=expected_snapshot_id,
        actual_snapshot_id=actual.snapshot_id,
        byte_identical=byte_identical,
    )
