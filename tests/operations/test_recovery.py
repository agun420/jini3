from datetime import UTC, date, datetime

from daybreak_operations.enums import RecoveryAction
from daybreak_operations.models import RestartState
from daybreak_operations.recovery import build_recovery_plan

NOW = datetime(2026, 8, 3, 13, 15, tzinfo=UTC)


def state(**changes):
    values = dict(
        trading_date=date(2026, 8, 3),
        session_id="session-1",
        previous_outcome="failed",
        kill_switch_active=False,
        managed_position_count=0,
        open_daybreak_order_count=0,
        recorder_checkpoint_available=True,
        database_consistent=True,
        leadership_lease_active=False,
        configuration_hash_matches=True,
        now=NOW,
    )
    values.update(changes)
    return RestartState(**values)


def test_safe_restart_allows_capture_but_never_new_entries():
    plan = build_recovery_plan(state())
    assert plan.action is RecoveryAction.CAPTURE_ONLY
    assert plan.may_resume_capture is True
    assert plan.may_resume_evaluation is True
    assert plan.may_resume_new_entries is False
    assert plan.manual_acknowledgement_required is True


def test_open_position_requires_flatten_only():
    plan = build_recovery_plan(state(managed_position_count=1))
    assert plan.action is RecoveryAction.FLATTEN_ONLY
    assert plan.may_resume_capture is False


def test_open_order_requires_reconciliation():
    plan = build_recovery_plan(state(open_daybreak_order_count=2))
    assert plan.action is RecoveryAction.RECONCILE_ONLY


def test_kill_switch_requires_manual_review():
    plan = build_recovery_plan(state(kill_switch_active=True))
    assert plan.action is RecoveryAction.MANUAL_REVIEW
    assert "KILL_SWITCH_ACTIVE" in plan.reasons


def test_configuration_mismatch_blocks_recovery():
    plan = build_recovery_plan(state(configuration_hash_matches=False))
    assert plan.action is RecoveryAction.BLOCK
    assert plan.may_resume_capture is False


def test_active_leader_blocks_second_process():
    plan = build_recovery_plan(state(leadership_lease_active=True))
    assert plan.action is RecoveryAction.BLOCK
