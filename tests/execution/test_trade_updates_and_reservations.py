from datetime import timedelta
from decimal import Decimal

from daybreak_execution.canonical import canonical_sha256
from daybreak_execution.enums import BrokerOrderStatus, ExecutionOutcome
from daybreak_execution.models import TradeUpdate
from daybreak_execution.persistence import MemoryExecutionRepository
from daybreak_execution.reservations import MemoryReservationEventSink
from daybreak_execution.service import ExecutionService
from daybreak_execution.trade_updates import normalize_trade_update
from daybreak_risk.enums import ReservationStatus
from tests.execution.helpers import FakeBroker, execution_request


def test_normalize_trade_update_preserves_provider_event():
    request = execution_request()
    raw = {
        "data": {
            "event": "fill",
            "timestamp": "2026-08-03T13:30:02Z",
            "order": {
                "id": "order-1",
                "client_order_id": request.risk_decision.reservation.client_order_id,
                "symbol": request.risk_decision.ticker,
                "side": "buy",
                "type": "limit",
                "time_in_force": "day",
                "order_class": "bracket",
                "status": "filled",
                "qty": str(request.risk_decision.final_quantity),
                "filled_qty": str(request.risk_decision.final_quantity),
                "filled_avg_price": "20.05",
                "limit_price": str(request.risk_decision.planned_entry_limit),
                "updated_at": "2026-08-03T13:30:02Z",
                "legs": [],
            },
        }
    }
    update = normalize_trade_update(raw)
    assert update.event == "fill"
    assert update.order.status is BrokerOrderStatus.FILLED
    assert update.order.filled_quantity == Decimal(request.risk_decision.final_quantity)


def test_execution_updates_reservation_lifecycle():
    request = execution_request()
    broker = FakeBroker()
    sink = MemoryReservationEventSink()
    repo = MemoryExecutionRepository()
    service = ExecutionService(broker=broker, repository=repo, reservation_events=sink)
    submitted = service.submit(request, now=request.requested_at)
    assert sink.events[0][1] is ReservationStatus.SUBMITTED
    filled = submitted.broker_order.model_copy(
        update={
            "snapshot_id": "filled-snapshot",
            "status": BrokerOrderStatus.FILLED,
            "filled_quantity": Decimal(submitted.command.quantity),
            "updated_at": request.requested_at + timedelta(seconds=1),
        }
    )
    update = TradeUpdate(
        event_id="fill-event",
        event="fill",
        event_timestamp=filled.updated_at,
        order=filled,
        raw_event_hash=canonical_sha256({"fill": 1}),
    )
    result = service.handle_trade_update(request, update)
    assert result.outcome is ExecutionOutcome.EXISTING_RECONCILED
    assert sink.events[-1][1] is ReservationStatus.FILLED
