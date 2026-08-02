from datetime import UTC, datetime, timedelta

from daybreak_operations.drills import run_failure_drill
from daybreak_operations.enums import DrillStatus, DrillType


class Clock:
    def __init__(self):
        self.value = datetime(2026, 8, 3, 14, 0, tzinfo=UTC)

    def __call__(self):
        value = self.value
        self.value += timedelta(seconds=1)
        return value


def test_successful_failure_drill():
    state = {"failed": False}
    result = run_failure_drill(
        DrillType.DATABASE_DISCONNECT,
        inject_failure=lambda: state.update(failed=True),
        detect_failure=lambda: state["failed"],
        entries_blocked=lambda: True,
        recovery_probe=lambda: True,
        kill_switch_probe=lambda: True,
        now=Clock(),
    )
    assert result.status is DrillStatus.PASSED
    assert result.kill_switch_activated is True


def test_drill_fails_when_entries_are_not_blocked():
    result = run_failure_drill(
        DrillType.BROKER_TIMEOUT,
        inject_failure=lambda: None,
        detect_failure=lambda: True,
        entries_blocked=lambda: False,
        recovery_probe=lambda: True,
        now=Clock(),
    )
    assert result.status is DrillStatus.FAILED
    assert "NEW_ENTRIES_BLOCKED" in result.errors


def test_probe_exception_is_recorded():
    def broken():
        raise RuntimeError("down")

    result = run_failure_drill(
        DrillType.MARKET_DATA_DISCONNECT,
        inject_failure=lambda: None,
        detect_failure=broken,
        entries_blocked=lambda: True,
        recovery_probe=lambda: True,
        now=Clock(),
    )
    assert result.status is DrillStatus.FAILED
    assert any("FAILURE_DETECTED_FAILED" in error for error in result.errors)
