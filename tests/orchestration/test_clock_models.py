from datetime import date, time

import pytest

from daybreak_orchestration.clock import build_session_plan
from daybreak_orchestration.models import OrchestrationPolicy
from tests.orchestration.helpers import CONFIG_HASH


def test_session_plan_is_dst_aware():
    winter = build_session_plan(
        trading_date=date(2026, 1, 5), run_id="w", configuration_hash=CONFIG_HASH
    )
    summer = build_session_plan(
        trading_date=date(2026, 8, 3), run_id="s", configuration_hash=CONFIG_HASH
    )
    assert winter.regular_session_open_at.hour == 14
    assert summer.regular_session_open_at.hour == 13


def test_policy_requires_monotonic_times():
    with pytest.raises(ValueError):
        OrchestrationPolicy(
            feature_snapshot_time_et=time(9, 30),
            evaluator_cutoff_time_et=time(9, 20),
        )


def test_plan_identity_is_deterministic():
    left = build_session_plan(
        trading_date=date(2026, 8, 3), run_id="run", configuration_hash=CONFIG_HASH
    )
    right = build_session_plan(
        trading_date=date(2026, 8, 3), run_id="run", configuration_hash=CONFIG_HASH
    )
    assert left == right
