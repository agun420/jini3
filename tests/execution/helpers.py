from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from daybreak_execution.canonical import canonical_sha256
from daybreak_execution.enums import BrokerOrderStatus
from daybreak_execution.errors import BrokerNotFound, BrokerTransportError
from daybreak_execution.models import (
    BrokerOrderCommand,
    BrokerOrderLeg,
    BrokerOrderSnapshot,
    BrokerPositionSnapshot,
    ExecutionRequest,
)
from daybreak_risk.engine import size_position
from tests.risk.helpers import sizing_request


def execution_request(*, now: datetime | None = None) -> ExecutionRequest:
    now = now or datetime(2026, 8, 3, 13, 30, 1, tzinfo=UTC)
    risk_request = sizing_request(now=now - timedelta(milliseconds=500))
    decision = size_position(risk_request)
    return ExecutionRequest(
        execution_id="execution-0001",
        run_id=decision.run_id,
        trading_date=decision.trading_date,
        requested_at=now,
        submission_cutoff_timestamp=now + timedelta(seconds=5),
        risk_decision=decision,
        configuration_hash=decision.configuration_hash,
    )


def snapshot_for(
    command: BrokerOrderCommand,
    *,
    status: BrokerOrderStatus = BrokerOrderStatus.NEW,
    filled: str = "0",
    order_id: str = "broker-order-1",
    observed: datetime | None = None,
) -> BrokerOrderSnapshot:
    observed = observed or datetime(2026, 8, 3, 13, 30, 1, 100000, tzinfo=UTC)
    legs_payload = []
    if command.order_class.value == "bracket":
        legs_payload = [
            {
                "id": f"{order_id}-tp",
                "client_order_id": None,
                "side": "sell",
                "type": "limit",
                "status": "held",
                "qty": str(command.quantity),
                "filled_qty": "0",
                "limit_price": str(command.take_profit_limit_price),
                "stop_price": None,
            },
            {
                "id": f"{order_id}-sl",
                "client_order_id": None,
                "side": "sell",
                "type": "stop",
                "status": "held",
                "qty": str(command.quantity),
                "filled_qty": "0",
                "limit_price": None,
                "stop_price": str(command.stop_loss_stop_price),
            },
        ]
    payload = {
        "id": order_id,
        "client_order_id": command.client_order_id,
        "symbol": command.symbol,
        "side": command.side.value,
        "type": command.order_type.value,
        "time_in_force": command.time_in_force.value,
        "order_class": command.order_class.value,
        "status": status.value,
        "qty": str(command.quantity),
        "filled_qty": filled,
        "limit_price": None if command.limit_price is None else str(command.limit_price),
        "stop_price": None if command.stop_price is None else str(command.stop_price),
        "legs": legs_payload,
    }
    legs = tuple(
        BrokerOrderLeg(
            broker_order_id=leg["id"],
            client_order_id=leg["client_order_id"],
            side=leg["side"],
            order_type=leg["type"],
            status=leg["status"],
            quantity=Decimal(leg["qty"]),
            filled_quantity=Decimal(leg["filled_qty"]),
            limit_price=None if leg["limit_price"] is None else Decimal(leg["limit_price"]),
            stop_price=None if leg["stop_price"] is None else Decimal(leg["stop_price"]),
        )
        for leg in legs_payload
    )
    return BrokerOrderSnapshot(
        snapshot_id=f"snapshot-{order_id}-{status.value}-{filled}".replace(".", "_"),
        broker_order_id=order_id,
        client_order_id=command.client_order_id,
        symbol=command.symbol,
        side=command.side,
        order_type=command.order_type,
        time_in_force=command.time_in_force.value,
        order_class=command.order_class.value,
        status=status,
        quantity=Decimal(command.quantity),
        filled_quantity=Decimal(filled),
        limit_price=command.limit_price,
        stop_price=command.stop_price,
        legs=legs,
        updated_at=observed,
        raw_response_hash=canonical_sha256(payload),
        raw_response=payload,
    )


class FakeBroker:
    def __init__(self) -> None:
        self.orders: dict[str, BrokerOrderSnapshot] = {}
        self.submitted: list[BrokerOrderCommand] = []
        self.canceled: list[str] = []
        self.submit_error: BrokerTransportError | None = None
        self.lookup_error: BrokerTransportError | None = None
        self.position: BrokerPositionSnapshot | None = None

    def get_order_by_client_order_id(self, client_order_id: str) -> BrokerOrderSnapshot:
        if self.lookup_error is not None:
            raise self.lookup_error
        try:
            return self.orders[client_order_id]
        except KeyError as exc:
            raise BrokerNotFound(client_order_id) from exc

    def submit_order(self, command: BrokerOrderCommand) -> BrokerOrderSnapshot:
        self.submitted.append(command)
        if self.submit_error is not None:
            raise self.submit_error
        order = snapshot_for(
            command,
            order_id=f"broker-order-{len(self.submitted)}",
        )
        self.orders[command.client_order_id] = order
        return order

    def cancel_order(self, broker_order_id: str) -> None:
        self.canceled.append(broker_order_id)
        for client_order_id, order in tuple(self.orders.items()):
            if order.broker_order_id == broker_order_id:
                self.orders[client_order_id] = order.model_copy(
                    update={"status": BrokerOrderStatus.CANCELED}
                )

    def get_order(self, broker_order_id: str) -> BrokerOrderSnapshot:
        for order in self.orders.values():
            if order.broker_order_id == broker_order_id:
                return order
        raise BrokerNotFound(broker_order_id)

    def get_position(self, symbol: str) -> BrokerPositionSnapshot | None:
        return self.position
