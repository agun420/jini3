from datetime import UTC, datetime, timedelta
from decimal import Decimal

from daybreak_orchestration.canonical import canonical_sha256
from daybreak_orchestration.flatten import FlattenService
from daybreak_orchestration.models import SessionPosition
from tests.orchestration.helpers import FakeSessionBroker, compressed_plan


def test_flatten_cancels_orders_and_closes_positions():
    plan, clock = compressed_plan()
    broker = FakeSessionBroker()
    result = FlattenService(broker).flatten(plan, now=clock(), sleep=clock.sleep, clock=clock)
    assert result.complete is True
    assert result.canceled_order_count == 2
    assert len(result.close_orders) == 1
    assert result.remaining_positions == ()


def test_flatten_incomplete_at_deadline():
    plan, clock = compressed_plan()
    plan = plan.model_copy(update={"final_flatten_deadline_at": clock() + timedelta(seconds=0.03)})
    broker = FakeSessionBroker(sticky=True)
    result = FlattenService(broker).flatten(plan, now=clock(), sleep=clock.sleep, clock=clock)
    assert result.complete is False
    assert result.remaining_positions


def test_flatten_records_close_error():
    plan, clock = compressed_plan()
    plan = plan.model_copy(update={"final_flatten_deadline_at": clock() + timedelta(seconds=0.02)})
    result = FlattenService(FakeSessionBroker(fail_close=True)).flatten(
        plan, now=clock(), sleep=clock.sleep, clock=clock
    )
    assert result.complete is False
    assert any("close position" in error for error in result.errors)


def test_flatten_closes_position_that_appears_during_cancel_race():
    plan, clock = compressed_plan()

    class LateFillBroker(FakeSessionBroker):
        def __init__(self):
            super().__init__()
            self.positions.clear()
            self.list_calls = 0

        def list_positions(self, targets):
            self.list_calls += 1
            if self.list_calls == 2:
                raw = {"symbol": "AAPL", "qty": "2"}
                self.positions = [
                    SessionPosition(
                        symbol="AAPL",
                        quantity=Decimal("2"),
                        average_entry_price=Decimal("100"),
                        observed_at=datetime(2026, 8, 3, 19, 50, tzinfo=UTC),
                        raw_response_hash=canonical_sha256(raw),
                    )
                ]
            return super().list_positions(targets)

    broker = LateFillBroker()
    result = FlattenService(broker).flatten(plan, now=clock(), sleep=clock.sleep, clock=clock)

    assert result.complete is True
    assert [order.quantity for order in result.close_orders] == [Decimal("2")]
