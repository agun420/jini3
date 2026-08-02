from datetime import UTC, datetime, timedelta

from daybreak_orchestration.alerts import AlertManager, MemoryAlertSink
from daybreak_orchestration.enums import AlertSeverity, KillSwitchReason
from daybreak_orchestration.kill_switch import activate_kill_switch, health_kill_reason
from daybreak_orchestration.leadership import MemoryLeadershipRepository
from daybreak_orchestration.models import OrchestrationPolicy
from tests.orchestration.helpers import HealthyProbe, compressed_plan


def test_fenced_leadership_blocks_second_holder_and_renews():
    repo = MemoryLeadershipRepository()
    now = datetime(2026, 8, 3, 8, tzinfo=UTC)
    first = repo.acquire("session", "holder-a", now=now, ttl_seconds=30)
    assert first is not None
    assert repo.acquire("session", "holder-b", now=now, ttl_seconds=30) is None
    renewed = repo.renew(first, now=now + timedelta(seconds=10), ttl_seconds=30)
    assert renewed is not None
    assert renewed.fencing_token == first.fencing_token
    repo.release(renewed, now=now + timedelta(seconds=11))
    second = repo.acquire("session", "holder-b", now=now + timedelta(seconds=12), ttl_seconds=30)
    assert second is not None
    assert second.fencing_token > first.fencing_token


def test_same_holder_name_cannot_reacquire_an_active_lease():
    repo = MemoryLeadershipRepository()
    now = datetime(2026, 8, 3, 8, tzinfo=UTC)
    first = repo.acquire("session", "shared-service-name", now=now, ttl_seconds=30)
    assert first is not None
    assert repo.acquire("session", "shared-service-name", now=now, ttl_seconds=30) is None


def test_alert_deduplication():
    sink = MemoryAlertSink()
    manager = AlertManager(sink, dedup_window_seconds=60)
    now = datetime(2026, 8, 3, 8, tzinfo=UTC)
    assert manager.emit(
        session_id="session", severity=AlertSeverity.CRITICAL, code="X", message="one", now=now
    )
    assert (
        manager.emit(
            session_id="session",
            severity=AlertSeverity.CRITICAL,
            code="X",
            message="two",
            now=now + timedelta(seconds=30),
        )
        is None
    )
    assert manager.emit(
        session_id="session",
        severity=AlertSeverity.CRITICAL,
        code="X",
        message="three",
        now=now + timedelta(seconds=61),
    )
    assert len(sink.alerts) == 2


def test_health_failure_maps_to_kill_reason():
    plan, clock = compressed_plan()
    health = HealthyProbe(database_healthy=False).snapshot(plan, now=clock())
    assert (
        health_kill_reason(health, plan, OrchestrationPolicy())
        is KillSwitchReason.DATABASE_UNHEALTHY
    )


def test_recorder_health_failure_maps_to_kill_reason():
    plan, clock = compressed_plan()
    health = HealthyProbe(recorder_healthy=False).snapshot(plan, now=clock())
    assert (
        health_kill_reason(health, plan, OrchestrationPolicy())
        is KillSwitchReason.RECORDER_UNHEALTHY
    )


def test_active_kill_switch_requires_explicit_reset():
    state = activate_kill_switch(
        "session",
        KillSwitchReason.MANUAL,
        now=datetime(2026, 8, 3, 8, tzinfo=UTC),
    )
    assert state.active is True
    assert state.reset_required is True
