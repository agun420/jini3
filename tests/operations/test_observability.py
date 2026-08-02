from datetime import UTC, datetime
from decimal import Decimal

from daybreak_operations.models import OperationsPolicy
from daybreak_operations.observability import build_observability_snapshot

CONFIG = "a" * 64
NOW = datetime(2026, 8, 3, 13, 0, tzinfo=UTC)


def test_healthy_observability_snapshot_is_deterministic():
    values = {
        "heartbeat_gap_seconds": 2,
        "free_disk_bytes": 9_000_000_000,
        "file_descriptor_limit": 8192,
    }
    left = build_observability_snapshot(metrics=values, configuration_hash=CONFIG, observed_at=NOW)
    right = build_observability_snapshot(
        metrics=dict(reversed(list(values.items()))), configuration_hash=CONFIG, observed_at=NOW
    )
    assert left == right
    assert left.healthy is True


def test_heartbeat_gap_fails_closed():
    value = build_observability_snapshot(
        metrics={"heartbeat_gap_seconds": Decimal("21")},
        configuration_hash=CONFIG,
        policy=OperationsPolicy(max_heartbeat_gap_seconds=20),
        observed_at=NOW,
    )
    assert value.healthy is False
    assert "HEARTBEAT_GAP_EXCEEDED" in value.failures


def test_low_disk_and_file_limit_are_reported():
    value = build_observability_snapshot(
        metrics={"free_disk_bytes": 1, "file_descriptor_limit": 128},
        configuration_hash=CONFIG,
        observed_at=NOW,
    )
    assert set(value.failures) == {"FREE_DISK_BELOW_MINIMUM", "FILE_DESCRIPTOR_LIMIT_BELOW_MINIMUM"}
