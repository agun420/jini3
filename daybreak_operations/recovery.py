from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from .canonical import canonical_sha256
from .enums import RecoveryAction
from .models import RecoveryPlan, RestartState


def build_recovery_plan(state: RestartState) -> RecoveryPlan:
    reasons: list[str] = []
    action = RecoveryAction.CAPTURE_ONLY
    may_capture = True
    may_evaluate = False

    if not state.configuration_hash_matches:
        reasons.append("CONFIGURATION_HASH_MISMATCH")
        action = RecoveryAction.BLOCK
        may_capture = False
    if not state.database_consistent:
        reasons.append("DATABASE_NOT_CONSISTENT")
        action = RecoveryAction.BLOCK
        may_capture = False
    if state.leadership_lease_active:
        reasons.append("ACTIVE_LEADERSHIP_LEASE_EXISTS")
        action = RecoveryAction.BLOCK
        may_capture = False
    if state.kill_switch_active:
        reasons.append("KILL_SWITCH_ACTIVE")
        action = RecoveryAction.MANUAL_REVIEW
        may_evaluate = False
    if state.managed_position_count > 0:
        reasons.append("MANAGED_POSITIONS_REQUIRE_RECONCILIATION")
        action = RecoveryAction.FLATTEN_ONLY
        may_capture = False
    elif state.open_daybreak_order_count > 0:
        reasons.append("OPEN_ORDERS_REQUIRE_RECONCILIATION")
        action = RecoveryAction.RECONCILE_ONLY
        may_capture = False
    elif not state.recorder_checkpoint_available:
        reasons.append("RECORDER_CHECKPOINT_MISSING")
        action = RecoveryAction.CAPTURE_ONLY
    elif not reasons:
        reasons.append("SAFE_CAPTURE_RECOVERY_ONLY")
        action = RecoveryAction.CAPTURE_ONLY
        may_evaluate = True

    state_hash = canonical_sha256(state)
    core = {
        "generated_at": state.now,
        "action": action,
        "reasons": tuple(reasons),
        "may_resume_capture": may_capture,
        "may_resume_evaluation": may_evaluate,
        "may_resume_new_entries": False,
        "manual_acknowledgement_required": True,
        "state_hash": state_hash,
    }
    plan_hash = canonical_sha256(core)
    plan_id = uuid5(NAMESPACE_URL, f"daybreak-recovery:{plan_hash}").hex
    return RecoveryPlan.model_validate({**core, "plan_id": plan_id, "plan_hash": plan_hash})
