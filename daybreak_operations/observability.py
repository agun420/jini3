from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from .canonical import canonical_sha256
from .models import MetricSample, ObservabilitySnapshot, OperationsPolicy


def build_observability_snapshot(
    *,
    metrics: Mapping[str, Decimal | int | float | str],
    configuration_hash: str,
    policy: OperationsPolicy | None = None,
    session_id: str | None = None,
    observed_at: datetime | None = None,
) -> ObservabilitySnapshot:
    policy = policy or OperationsPolicy()
    observed_at = (observed_at or datetime.now(UTC)).astimezone(UTC)
    samples = tuple(
        MetricSample(name=name, value=Decimal(str(value)), unit=_unit_for(name))
        for name, value in sorted(metrics.items())
    )
    failures: list[str] = []
    lookup = {sample.name: sample.value for sample in samples}
    if lookup.get("heartbeat_gap_seconds", Decimal("0")) > policy.max_heartbeat_gap_seconds:
        failures.append("HEARTBEAT_GAP_EXCEEDED")
    if (
        lookup.get("free_disk_bytes", Decimal(policy.minimum_free_disk_bytes))
        < policy.minimum_free_disk_bytes
    ):
        failures.append("FREE_DISK_BELOW_MINIMUM")
    if (
        lookup.get("file_descriptor_limit", Decimal(policy.minimum_file_descriptor_limit))
        < policy.minimum_file_descriptor_limit
    ):
        failures.append("FILE_DESCRIPTOR_LIMIT_BELOW_MINIMUM")
    core = {
        "session_id": session_id,
        "observed_at": observed_at,
        "healthy": not failures,
        "metrics": samples,
        "failures": tuple(failures),
        "configuration_hash": configuration_hash,
    }
    snapshot_hash = canonical_sha256(core)
    snapshot_id = uuid5(NAMESPACE_URL, f"daybreak-observability:{snapshot_hash}").hex
    return ObservabilitySnapshot.model_validate(
        {**core, "snapshot_id": snapshot_id, "snapshot_hash": snapshot_hash}
    )


def _unit_for(name: str) -> str:
    if name.endswith("_seconds"):
        return "seconds"
    if name.endswith("_ms"):
        return "milliseconds"
    if name.endswith("_bytes"):
        return "bytes"
    if name.endswith("_count") or name.endswith("_limit"):
        return "count"
    return "value"
