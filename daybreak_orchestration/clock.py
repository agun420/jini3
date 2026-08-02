from __future__ import annotations

from datetime import UTC, date, datetime, time
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from .models import OrchestrationPolicy, SessionPlan

ET = ZoneInfo("America/New_York")


def _at(trading_date: date, local_time: time) -> datetime:
    return datetime.combine(trading_date, local_time, tzinfo=ET).astimezone(UTC)


def build_session_plan(
    *,
    trading_date: date,
    run_id: str,
    configuration_hash: str,
    policy: OrchestrationPolicy | None = None,
) -> SessionPlan:
    policy = policy or OrchestrationPolicy()
    session_id = uuid5(
        NAMESPACE_URL,
        f"daybreak-session:{trading_date.isoformat()}:{run_id}:{configuration_hash}:{policy.policy_version}",
    ).hex
    return SessionPlan(
        session_id=session_id,
        run_id=run_id,
        trading_date=trading_date,
        recorder_warmup_at=_at(trading_date, policy.recorder_warmup_time_et),
        feature_window_start_at=_at(trading_date, policy.feature_window_start_time_et),
        feature_snapshot_at=_at(trading_date, policy.feature_snapshot_time_et),
        evaluator_cutoff_at=_at(trading_date, policy.evaluator_cutoff_time_et),
        eligibility_lock_at=_at(trading_date, policy.eligibility_lock_time_et),
        regular_session_open_at=_at(trading_date, policy.regular_session_open_time_et),
        new_entry_cutoff_at=_at(trading_date, policy.new_entry_cutoff_time_et),
        mandatory_flatten_at=_at(trading_date, policy.mandatory_flatten_time_et),
        final_flatten_deadline_at=_at(trading_date, policy.final_flatten_deadline_et),
        policy=policy,
        configuration_hash=configuration_hash,
    )
