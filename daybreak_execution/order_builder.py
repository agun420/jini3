from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from daybreak_risk.enums import ReservationStatus, RiskDecisionStatus

from .canonical import canonical_sha256
from .enums import OrderClass, OrderSide, OrderType, TimeInForce
from .models import BrokerOrderCommand, ExecutionRequest


def _command_id(execution_id: str, client_order_id: str) -> str:
    return uuid5(NAMESPACE_URL, f"daybreak-command:{execution_id}:{client_order_id}").hex


def _with_hash(payload: dict[str, object]) -> BrokerOrderCommand:
    unhashed = {**payload, "command_hash": "0" * 64}
    hash_value = canonical_sha256({k: v for k, v in unhashed.items() if k != "command_hash"})
    return BrokerOrderCommand.model_validate({**payload, "command_hash": hash_value})


def build_entry_command(
    request: ExecutionRequest,
    *,
    now: datetime | None = None,
) -> BrokerOrderCommand:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    decision = request.risk_decision
    if decision.decision is not RiskDecisionStatus.APPROVED:
        raise ValueError("risk decision is not approved")
    if decision.reservation is None:
        raise ValueError("approved risk decision has no reservation")
    if decision.reservation.status is not ReservationStatus.RESERVED:
        raise ValueError("risk reservation is not in reserved status")
    if now > request.submission_cutoff_timestamp:
        raise ValueError("submission cutoff exceeded")
    if now >= decision.reservation.expires_at:
        raise ValueError("risk reservation expired")
    if decision.final_quantity != decision.reservation.reserved_quantity:
        raise ValueError("risk quantity and reservation quantity differ")
    if (
        decision.planned_entry_limit is None
        or decision.stop_price is None
        or decision.target_price is None
    ):
        raise ValueError("risk decision is missing executable prices")
    payload: dict[str, object] = {
        "command_id": _command_id(request.execution_id, decision.reservation.client_order_id),
        "execution_id": request.execution_id,
        "client_order_id": decision.reservation.client_order_id,
        "symbol": decision.ticker,
        "quantity": decision.final_quantity,
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "time_in_force": TimeInForce.DAY,
        "order_class": OrderClass.BRACKET,
        "limit_price": decision.planned_entry_limit,
        "take_profit_limit_price": decision.target_price,
        "stop_loss_stop_price": decision.stop_price,
        "extended_hours": False,
        "parent_client_order_id": None,
    }
    return _with_hash(payload)


def protective_client_order_id(parent: str) -> str:
    suffix = "-P"
    return f"{parent[: 48 - len(suffix)]}{suffix}"


def build_partial_fill_protective_stop(
    request: ExecutionRequest,
    *,
    filled_quantity: int,
) -> BrokerOrderCommand:
    decision = request.risk_decision
    if filled_quantity <= 0:
        raise ValueError("protective stop requires positive filled quantity")
    if decision.stop_price is None or decision.reservation is None:
        raise ValueError("risk decision is missing stop or reservation")
    client_id = protective_client_order_id(decision.reservation.client_order_id)
    payload: dict[str, object] = {
        "command_id": _command_id(request.execution_id, client_id),
        "execution_id": request.execution_id,
        "client_order_id": client_id,
        "symbol": decision.ticker,
        "quantity": filled_quantity,
        "side": OrderSide.SELL,
        "order_type": OrderType.STOP,
        "time_in_force": TimeInForce.DAY,
        "order_class": OrderClass.SIMPLE,
        "limit_price": None,
        "stop_price": decision.stop_price,
        "take_profit_limit_price": None,
        "stop_loss_stop_price": None,
        "extended_hours": False,
        "parent_client_order_id": decision.reservation.client_order_id,
    }
    return _with_hash(payload)
