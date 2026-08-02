from daybreak_orchestration.alerts import AlertManager, MemoryAlertSink
from daybreak_orchestration.enums import KillSwitchReason, SessionOutcome
from daybreak_orchestration.flatten import FlattenService
from daybreak_orchestration.kill_switch import activate_kill_switch
from daybreak_orchestration.leadership import MemoryLeadershipRepository
from daybreak_orchestration.persistence import MemoryOrchestrationRepository
from daybreak_orchestration.service import SessionOrchestrator
from tests.orchestration.helpers import (
    FakeHooks,
    FakeSessionBroker,
    HealthyProbe,
    compressed_plan,
)


def build_service(
    plan, clock, *, hooks=None, probe=None, broker=None, leadership=None, repository=None
):
    repo = repository or MemoryOrchestrationRepository()
    sink = MemoryAlertSink()
    service = SessionOrchestrator(
        holder_id="holder-1",
        leadership=leadership or MemoryLeadershipRepository(),
        repository=repo,
        health_probe=probe or HealthyProbe(),
        hooks=hooks or FakeHooks(),
        flatten_service=FlattenService(broker or FakeSessionBroker()),
        alerts=AlertManager(sink, dedup_window_seconds=0),
        clock=clock,
        sleep=clock.sleep,
    )
    return service, repo, sink


def test_full_approved_session_completes_and_flattens():
    plan, clock = compressed_plan()
    service, repo, _ = build_service(plan, clock)
    result = service.run(plan, start_at=clock())
    assert result.outcome is SessionOutcome.COMPLETED
    assert result.flatten_result is not None and result.flatten_result.complete
    assert "execute" in [call for call in FakeHooks().calls] or result.phase_records
    assert repo.results


def test_no_setups_skips_execution_but_still_flattens():
    plan, clock = compressed_plan()
    hooks = FakeHooks(run_status="no_setups", approved_count=0)
    service, _, _ = build_service(plan, clock, hooks=hooks)
    result = service.run(plan, start_at=clock())
    assert result.outcome is SessionOutcome.NO_SETUPS
    assert "execute" not in hooks.calls
    assert result.flatten_result is not None


def test_health_failure_activates_kill_switch_and_alert():
    plan, clock = compressed_plan()
    service, _, sink = build_service(plan, clock, probe=HealthyProbe(database_healthy=False))
    result = service.run(plan, start_at=clock())
    assert result.outcome is SessionOutcome.KILLED
    assert result.kill_switch.active is True
    assert sink.alerts


def test_hook_failure_activates_kill_switch():
    plan, clock = compressed_plan()
    service, _, _ = build_service(plan, clock, hooks=FakeHooks(fail_phase="features"))
    result = service.run(plan, start_at=clock())
    assert result.outcome is SessionOutcome.KILLED
    assert result.kill_switch.active


def test_incomplete_flatten_is_terminal_failure():
    plan, clock = compressed_plan()
    service, _, _ = build_service(plan, clock, broker=FakeSessionBroker(sticky=True))
    result = service.run(plan, start_at=clock())
    assert result.outcome is SessionOutcome.FLATTEN_INCOMPLETE
    assert result.kill_switch.active


def test_second_leader_is_blocked():
    plan, clock = compressed_plan()
    leadership = MemoryLeadershipRepository()
    held = leadership.acquire(plan.session_id, "other", now=clock(), ttl_seconds=30)
    assert held is not None
    service, _, sink = build_service(plan, clock, leadership=leadership)
    result = service.run(plan, start_at=clock())
    assert result.outcome is SessionOutcome.BLOCKED
    assert sink.alerts


def test_persistent_kill_switch_survives_restart_and_blocks_hooks():
    plan, clock = compressed_plan()
    repo = MemoryOrchestrationRepository()
    active = activate_kill_switch(
        plan.session_id,
        KillSwitchReason.MANUAL,
        now=clock(),
    )
    repo.save_kill_switch(active)
    hooks = FakeHooks()
    service, _, sink = build_service(
        plan,
        clock,
        hooks=hooks,
        repository=repo,
    )

    result = service.run(plan, start_at=clock())

    assert result.outcome is SessionOutcome.KILLED
    assert result.kill_switch == active
    assert hooks.calls == []
    assert sink.alerts[0].code == "PERSISTENT_KILL_SWITCH_ACTIVE"


def test_unknown_evaluation_status_fails_closed_before_execution():
    plan, clock = compressed_plan()
    hooks = FakeHooks(run_status="unexpected", approved_count=1)
    service, _, _ = build_service(plan, clock, hooks=hooks)

    result = service.run(plan, start_at=clock())

    assert result.outcome is SessionOutcome.KILLED
    assert "execute" not in hooks.calls
