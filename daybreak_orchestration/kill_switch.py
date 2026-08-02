from __future__ import annotations

from datetime import UTC, datetime

from .canonical import canonical_sha256
from .enums import KillSwitchReason
from .models import HealthSnapshot, KillSwitchState, OrchestrationPolicy, SessionPlan


def inactive_kill_switch(session_id: str) -> KillSwitchState:
    core = {
        "session_id": session_id,
        "active": False,
        "activated_at": None,
        "reason": None,
        "details": {},
        "reset_required": False,
    }
    return KillSwitchState.model_validate({**core, "state_hash": canonical_sha256(core)})


def activate_kill_switch(
    session_id: str,
    reason: KillSwitchReason,
    *,
    now: datetime,
    details: dict[str, object] | None = None,
) -> KillSwitchState:
    now = now.astimezone(UTC)
    core = {
        "session_id": session_id,
        "active": True,
        "activated_at": now,
        "reason": reason,
        "details": details or {},
        "reset_required": True,
    }
    return KillSwitchState.model_validate({**core, "state_hash": canonical_sha256(core)})


def health_kill_reason(
    health: HealthSnapshot,
    plan: SessionPlan,
    policy: OrchestrationPolicy,
) -> KillSwitchReason | None:
    if health.configuration_hash != plan.configuration_hash:
        return KillSwitchReason.CONFIGURATION_MISMATCH
    if not health.clock_synchronized or abs(health.clock_skew_ms) > policy.max_clock_skew_ms:
        return KillSwitchReason.CLOCK_UNSYNCED
    if not health.database_healthy:
        return KillSwitchReason.DATABASE_UNHEALTHY
    if not health.recorder_healthy:
        return KillSwitchReason.RECORDER_UNHEALTHY
    if not health.market_data_stream_healthy:
        return KillSwitchReason.MARKET_DATA_UNHEALTHY
    if not health.trade_update_stream_healthy:
        return KillSwitchReason.TRADE_UPDATE_STREAM_UNHEALTHY
    if not health.broker_healthy or not health.account_active:
        return KillSwitchReason.BROKER_UNHEALTHY
    if health.account_blocked:
        return KillSwitchReason.ACCOUNT_BLOCKED
    if health.trading_blocked:
        return KillSwitchReason.TRADING_BLOCKED
    if not health.market_status_normal:
        return KillSwitchReason.MARKET_CIRCUIT_BREAKER
    return None
