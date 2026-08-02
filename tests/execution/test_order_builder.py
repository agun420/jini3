from datetime import timedelta

import pytest

from daybreak_execution.enums import OrderClass, OrderSide, OrderType
from daybreak_execution.order_builder import (
    build_entry_command,
    build_partial_fill_protective_stop,
)
from tests.execution.helpers import execution_request


def test_entry_command_uses_risk_reservation_and_bracket_prices():
    request = execution_request()
    command = build_entry_command(request, now=request.requested_at)
    decision = request.risk_decision
    assert command.client_order_id == decision.reservation.client_order_id
    assert command.quantity == decision.final_quantity
    assert command.side is OrderSide.BUY
    assert command.order_type is OrderType.LIMIT
    assert command.order_class is OrderClass.BRACKET
    assert command.limit_price == decision.planned_entry_limit
    assert command.stop_loss_stop_price == decision.stop_price
    assert command.take_profit_limit_price == decision.target_price
    assert command.extended_hours is False


def test_entry_command_rejects_cutoff_and_expired_reservation():
    request = execution_request()
    with pytest.raises(ValueError, match="cutoff"):
        build_entry_command(
            request, now=request.submission_cutoff_timestamp + timedelta(microseconds=1)
        )
    expired = request.risk_decision.model_copy(
        update={
            "reservation": request.risk_decision.reservation.model_copy(
                update={"expires_at": request.requested_at}
            )
        }
    )
    with pytest.raises(ValueError, match="expired"):
        build_entry_command(
            request.model_copy(update={"risk_decision": expired}), now=request.requested_at
        )


def test_partial_fill_stop_is_sell_stop_and_parent_linked():
    request = execution_request()
    command = build_partial_fill_protective_stop(request, filled_quantity=3)
    assert command.side is OrderSide.SELL
    assert command.order_type is OrderType.STOP
    assert command.order_class is OrderClass.SIMPLE
    assert command.quantity == 3
    assert command.stop_price == request.risk_decision.stop_price
    assert command.parent_client_order_id == request.risk_decision.reservation.client_order_id
