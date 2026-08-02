from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from daybreak_contracts.enums import RiskFlag
from daybreak_risk.engine import size_position
from daybreak_risk.enums import BindingCap, RiskDecisionStatus, RiskRejectionCode

from .helpers import approved_setup, sizing_request


def test_eligible_setup_is_sized_and_reserved() -> None:
    decision = size_position(sizing_request())
    assert decision.decision == RiskDecisionStatus.APPROVED
    assert decision.final_quantity > 0
    assert decision.binding_cap == BindingCap.TRADE_RISK
    assert decision.reservation is not None
    assert decision.reservation.client_order_id.endswith("-AAAA")
    assert decision.stop_price == Decimal("19.00")
    assert decision.target_price == Decimal("22.00")
    assert decision.risk_flag_multiplier == Decimal("1.00")


def test_low_float_reduces_risk_budget_by_half() -> None:
    base = size_position(sizing_request())
    setup = approved_setup(risk_flags=(RiskFlag.LOW_FLOAT,))
    reduced = size_position(sizing_request(setup=setup))
    assert reduced.decision == RiskDecisionStatus.APPROVED
    assert reduced.risk_flag_multiplier == Decimal("0.50")
    assert reduced.adjusted_trade_risk_budget == base.adjusted_trade_risk_budget / 2
    assert reduced.final_quantity < base.final_quantity


def test_multiple_flags_use_minimum_not_product() -> None:
    setup = approved_setup(
        risk_flags=(RiskFlag.LOW_FLOAT, RiskFlag.SPIKY_VOLUME, RiskFlag.SECONDARY_SOURCE)
    )
    decision = size_position(sizing_request(setup=setup))
    assert decision.risk_flag_multiplier == Decimal("0.50")


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("account_blocked", RiskRejectionCode.ACCOUNT_BLOCKED),
        ("trading_blocked", RiskRejectionCode.TRADING_BLOCKED),
        ("trade_suspended_by_user", RiskRejectionCode.TRADE_SUSPENDED_BY_USER),
    ],
)
def test_account_blocks_fail_closed(field: str, reason: RiskRejectionCode) -> None:
    request = sizing_request()
    account = request.account.model_copy(update={field: True})
    decision = size_position(request.model_copy(update={"account": account}))
    assert decision.decision == RiskDecisionStatus.REJECTED
    assert reason in decision.rejection_reasons


def test_stale_account_and_quote_are_rejected() -> None:
    request = sizing_request()
    account = request.account.model_copy(
        update={"snapshot_timestamp": request.calculated_at - timedelta(seconds=3)}
    )
    quote = request.quote.model_copy(
        update={"quote_timestamp": request.calculated_at - timedelta(seconds=3)}
    )
    decision = size_position(request.model_copy(update={"account": account, "quote": quote}))
    assert RiskRejectionCode.ACCOUNT_SNAPSHOT_STALE in decision.rejection_reasons
    assert RiskRejectionCode.QUOTE_SNAPSHOT_STALE in decision.rejection_reasons


def test_crossed_quote_is_rejected() -> None:
    request = sizing_request()
    quote = request.quote.model_copy(
        update={"bid_price": Decimal("20.10"), "ask_price": Decimal("20.00")}
    )
    decision = size_position(request.model_copy(update={"quote": quote}))
    assert RiskRejectionCode.INVALID_QUOTE in decision.rejection_reasons


def test_wide_spread_is_rejected() -> None:
    request = sizing_request()
    quote = request.quote.model_copy(
        update={"bid_price": Decimal("19.50"), "ask_price": Decimal("20.50")}
    )
    decision = size_position(request.model_copy(update={"quote": quote}))
    assert RiskRejectionCode.SPREAD_TOO_WIDE in decision.rejection_reasons


def test_premarket_low_break_is_rejected() -> None:
    request = sizing_request()
    quote = request.quote.model_copy(update={"last_price": Decimal("19.00")})
    decision = size_position(request.model_copy(update={"quote": quote}))
    assert RiskRejectionCode.PREMARKET_LOW_BROKEN in decision.rejection_reasons


def test_stop_above_premarket_low_is_rejected() -> None:
    setup = approved_setup()
    params = setup.trade_parameters.model_copy(update={"premarket_low_used": 18.50})
    setup = setup.model_copy(update={"trade_parameters": params})
    decision = size_position(sizing_request(setup=setup))
    assert RiskRejectionCode.STOP_ABOVE_PREMARKET_LOW in decision.rejection_reasons


def test_entry_drift_is_rejected() -> None:
    request = sizing_request().model_copy(update={"planned_entry_limit": Decimal("20.50")})
    decision = size_position(request)
    assert RiskRejectionCode.ENTRY_PRICE_DRIFT_TOO_LARGE in decision.rejection_reasons


def test_soft_daily_loss_blocks_new_entries() -> None:
    request = sizing_request()
    account = request.account.model_copy(update={"equity": Decimal("49600")})
    session = request.session.model_copy(update={"internal_realized_pnl": Decimal("-400")})
    decision = size_position(request.model_copy(update={"account": account, "session": session}))
    assert RiskRejectionCode.SOFT_DAILY_LOSS_LIMIT in decision.rejection_reasons
    assert not decision.kill_switch_required


def test_hard_daily_loss_requires_kill_switch() -> None:
    request = sizing_request()
    account = request.account.model_copy(update={"equity": Decimal("49400")})
    session = request.session.model_copy(update={"internal_realized_pnl": Decimal("-600")})
    decision = size_position(request.model_copy(update={"account": account, "session": session}))
    assert RiskRejectionCode.HARD_DAILY_LOSS_LIMIT in decision.rejection_reasons
    assert decision.kill_switch_required


def test_pnl_reconciliation_difference_fails_closed() -> None:
    request = sizing_request()
    session = request.session.model_copy(update={"internal_realized_pnl": Decimal("-10")})
    decision = size_position(request.model_copy(update={"session": session}))
    assert RiskRejectionCode.SESSION_PNL_RECONCILIATION_FAILURE in decision.rejection_reasons


def test_open_risk_capacity_can_bind() -> None:
    request = sizing_request()
    session = request.session.model_copy(update={"current_total_open_risk": Decimal("350")})
    decision = size_position(request.model_copy(update={"session": session}))
    assert decision.decision == RiskDecisionStatus.APPROVED
    assert decision.binding_cap == BindingCap.OPEN_RISK


def test_buying_power_can_bind() -> None:
    request = sizing_request()
    account = request.account.model_copy(
        update={
            "buying_power": Decimal("250"),
            "non_marginable_buying_power": Decimal("250"),
        }
    )
    decision = size_position(request.model_copy(update={"account": account}))
    assert decision.decision == RiskDecisionStatus.APPROVED
    assert decision.binding_cap == BindingCap.BUYING_POWER


def test_liquidity_cap_can_bind() -> None:
    request = sizing_request()
    liquidity = request.liquidity.model_copy(update={"adv20_shares": 10_000})
    decision = size_position(request.model_copy(update={"liquidity": liquidity}))
    assert decision.decision == RiskDecisionStatus.APPROVED
    assert decision.binding_cap == BindingCap.ADV_LIQUIDITY
    assert decision.final_quantity == 10


def test_zero_capacity_rejects() -> None:
    request = sizing_request()
    session = request.session.model_copy(update={"current_total_open_risk": Decimal("375")})
    decision = size_position(request.model_copy(update={"session": session}))
    assert decision.decision == RiskDecisionStatus.REJECTED
    assert RiskRejectionCode.NO_OPEN_RISK_CAPACITY in decision.rejection_reasons


def test_reserved_notional_reduces_buying_power_capacity() -> None:
    request = sizing_request()
    account = request.account.model_copy(
        update={
            "buying_power": Decimal("1000"),
            "non_marginable_buying_power": Decimal("1000"),
        }
    )
    session = request.session.model_copy(update={"reserved_entry_notional": Decimal("600")})
    decision = size_position(request.model_copy(update={"account": account, "session": session}))
    assert decision.decision == RiskDecisionStatus.APPROVED
    assert decision.binding_cap == BindingCap.BUYING_POWER


def test_client_order_id_is_compact_and_deterministic() -> None:
    request = sizing_request().model_copy(update={"run_id": "r" * 200})
    first = size_position(request)
    second = size_position(request)
    assert first.reservation is not None
    assert first.reservation.client_order_id == second.reservation.client_order_id
    assert len(first.reservation.client_order_id) <= 48


def test_session_initialization_uses_conservative_equity() -> None:
    from daybreak_risk.engine import initialize_session_state

    request = sizing_request()
    account = request.account.model_copy(
        update={"equity": Decimal("51000"), "last_equity": Decimal("50000")}
    )
    state = initialize_session_state(account)
    assert state.session_reference_equity == Decimal("50000")
    assert state.session_start_equity == Decimal("51000")


def test_negative_available_buying_power_fails_closed() -> None:
    request = sizing_request()
    account = request.account.model_copy(
        update={
            "buying_power": Decimal("100"),
            "non_marginable_buying_power": Decimal("100"),
        }
    )
    session = request.session.model_copy(update={"reserved_entry_notional": Decimal("100")})
    decision = size_position(request.model_copy(update={"account": account, "session": session}))
    assert RiskRejectionCode.NO_BUYING_POWER_CAPACITY in decision.rejection_reasons


def test_stale_last_trade_is_rejected() -> None:
    request = sizing_request()
    quote = request.quote.model_copy(
        update={"last_trade_timestamp": request.calculated_at - timedelta(seconds=5)}
    )
    decision = size_position(request.model_copy(update={"quote": quote}))
    assert RiskRejectionCode.LAST_TRADE_STALE in decision.rejection_reasons


def test_non_marketable_entry_limit_is_rejected() -> None:
    request = sizing_request().model_copy(update={"planned_entry_limit": Decimal("20.05")})
    decision = size_position(request)
    assert RiskRejectionCode.ENTRY_LIMIT_NOT_MARKETABLE in decision.rejection_reasons


def test_execution_cutoff_is_enforced() -> None:
    request = sizing_request()
    late = request.model_copy(
        update={"calculated_at": request.execution_cutoff_timestamp + timedelta(milliseconds=1)}
    )
    decision = size_position(late)
    assert RiskRejectionCode.EXECUTION_CUTOFF_EXCEEDED in decision.rejection_reasons


def test_decision_and_reservation_echo_exchange_trading_date() -> None:
    request = sizing_request()
    decision = size_position(request)
    assert decision.trading_date == request.trading_date
    assert decision.reservation is not None
    assert decision.reservation.trading_date == request.trading_date
