from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from daybreak_risk.models import RiskPolicyConfig


def test_paper_and_live_profiles_are_coherent() -> None:
    paper = RiskPolicyConfig.paper_v1()
    live = RiskPolicyConfig.live_pilot_v1()
    assert paper.risk_per_trade_pct == Decimal("0.0025")
    assert live.max_concurrent_positions == 1
    assert live.risk_per_trade_pct < paper.risk_per_trade_pct


def test_policy_rejects_soft_limit_above_hard_limit() -> None:
    data = RiskPolicyConfig.paper_v1().model_dump(mode="python")
    data["soft_daily_loss_pct"] = Decimal("0.02")
    with pytest.raises(ValidationError):
        RiskPolicyConfig.model_validate(data)


def test_policy_rejects_position_limit_above_gross_limit() -> None:
    data = RiskPolicyConfig.paper_v1().model_dump(mode="python")
    data["max_position_notional_pct"] = Decimal("0.50")
    with pytest.raises(ValidationError):
        RiskPolicyConfig.model_validate(data)


def test_sizing_request_rejects_wrong_exchange_date() -> None:
    from datetime import timedelta

    from pydantic import ValidationError

    from .helpers import sizing_request

    request = sizing_request()
    data = request.model_dump(mode="python")
    data["trading_date"] = request.trading_date + timedelta(days=1)
    with pytest.raises(ValidationError):
        request.__class__.model_validate(data)
