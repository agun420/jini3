from datetime import timedelta
from decimal import Decimal

from daybreak_execution.canonical import canonical_sha256
from daybreak_execution.enums import (
    BrokerOrderStatus,
    ExecutionOutcome,
    ExecutionRejectionCode,
)
from daybreak_execution.errors import BrokerTransportError
from daybreak_execution.models import TradeUpdate
from daybreak_execution.order_builder import build_entry_command
from daybreak_execution.persistence import MemoryExecutionRepository
from daybreak_execution.service import ExecutionService
from tests.execution.helpers import FakeBroker, execution_request, snapshot_for


def test_submit_new_order_and_persist_events():
    request = execution_request()
    broker = FakeBroker()
    repo = MemoryExecutionRepository()
    result = ExecutionService(broker=broker, repository=repo).submit(
        request, now=request.requested_at
    )
    assert result.outcome is ExecutionOutcome.SUBMITTED
    assert len(broker.submitted) == 1
    assert result.broker_order is not None
    assert len(repo.events[request.execution_id]) == 5


def test_existing_order_is_reconciled_without_second_submit():
    request = execution_request()
    command = build_entry_command(request, now=request.requested_at)
    broker = FakeBroker()
    broker.orders[command.client_order_id] = snapshot_for(command)
    result = ExecutionService(broker=broker, repository=MemoryExecutionRepository()).submit(
        request, now=request.requested_at
    )
    assert result.outcome is ExecutionOutcome.EXISTING_RECONCILED
    assert broker.submitted == []


def test_ambiguous_timeout_does_not_retry_submission():
    request = execution_request()
    broker = FakeBroker()
    broker.submit_error = BrokerTransportError("timeout", transient=True)
    result = ExecutionService(broker=broker, repository=MemoryExecutionRepository()).submit(
        request, now=request.requested_at
    )
    assert result.outcome is ExecutionOutcome.RECONCILIATION_REQUIRED
    assert len(broker.submitted) == 1
    assert result.reconciliation_required is True


def test_timeout_recovers_by_client_order_lookup():
    request = execution_request()

    class TimeoutThenFound(FakeBroker):
        def submit_order(self, cmd):
            self.submitted.append(cmd)
            self.orders[cmd.client_order_id] = snapshot_for(cmd)
            raise BrokerTransportError("timeout", transient=True)

    broker = TimeoutThenFound()
    result = ExecutionService(broker=broker, repository=MemoryExecutionRepository()).submit(
        request, now=request.requested_at
    )
    assert result.outcome is ExecutionOutcome.SUBMITTED
    assert len(broker.submitted) == 1


def test_partial_fill_submits_protective_stop_and_requires_reconciliation():
    request = execution_request()
    broker = FakeBroker()
    repo = MemoryExecutionRepository()
    service = ExecutionService(broker=broker, repository=repo)
    initial = service.submit(request, now=request.requested_at)
    parent = initial.broker_order
    partial = parent.model_copy(
        update={
            "snapshot_id": "snapshot-partial",
            "status": BrokerOrderStatus.PARTIALLY_FILLED,
            "filled_quantity": Decimal("3"),
            "updated_at": request.requested_at + timedelta(seconds=1),
        }
    )
    update = TradeUpdate(
        event_id="update-1",
        event="partial_fill",
        event_timestamp=partial.updated_at,
        order=partial,
        raw_event_hash=canonical_sha256({"event": "partial_fill"}),
    )
    broker.orders[parent.client_order_id] = partial
    result = service.handle_trade_update(request, update)
    assert result.outcome is ExecutionOutcome.PARTIAL_FILL_PROTECTED
    assert result.reconciliation_required is True
    assert broker.canceled == [parent.broker_order_id]
    assert len(broker.submitted) == 2
    assert broker.submitted[-1].quantity == 3
    assert broker.submitted[-1].side.value == "sell"


def test_stale_unfilled_entry_is_canceled():
    request = execution_request()
    broker = FakeBroker()
    repo = MemoryExecutionRepository()
    service = ExecutionService(broker=broker, repository=repo)
    initial = service.submit(request, now=request.requested_at)
    assert (
        service.cancel_stale_entry(
            request,
            initial.broker_order,
            now=request.requested_at
            + timedelta(seconds=request.policy.cancel_unfilled_after_seconds + 1),
        )
        is True
    )
    assert broker.canceled == [initial.broker_order.broker_order_id]


def test_duplicate_trade_update_is_idempotent():
    request = execution_request()
    broker = FakeBroker()
    repo = MemoryExecutionRepository()
    service = ExecutionService(broker=broker, repository=repo)
    submitted = service.submit(request, now=request.requested_at)
    partial = submitted.broker_order.model_copy(
        update={
            "snapshot_id": "dup-partial",
            "status": BrokerOrderStatus.PARTIALLY_FILLED,
            "filled_quantity": Decimal("2"),
            "updated_at": request.requested_at + timedelta(seconds=1),
        }
    )
    update = TradeUpdate(
        event_id="dup-update",
        event="partial_fill",
        event_timestamp=partial.updated_at,
        order=partial,
        raw_event_hash=canonical_sha256({"dup": 1}),
    )
    broker.orders[partial.client_order_id] = partial
    first = service.handle_trade_update(request, update)
    submitted_count = len(broker.submitted)
    canceled_count = len(broker.canceled)
    second = service.handle_trade_update(request, update)
    assert first.outcome is ExecutionOutcome.PARTIAL_FILL_PROTECTED
    assert second.outcome is ExecutionOutcome.EXISTING_RECONCILED
    assert len(broker.submitted) == submitted_count
    assert len(broker.canceled) == canceled_count


def test_http_success_with_rejected_status_is_not_successful_submission():
    request = execution_request()

    class RejectedBroker(FakeBroker):
        def submit_order(self, command):
            self.submitted.append(command)
            order = snapshot_for(command, status=BrokerOrderStatus.REJECTED)
            self.orders[command.client_order_id] = order
            return order

    result = ExecutionService(
        broker=RejectedBroker(), repository=MemoryExecutionRepository()
    ).submit(request, now=request.requested_at)
    assert result.outcome is ExecutionOutcome.REJECTED


def test_existing_order_with_different_limit_requires_reconciliation():
    request = execution_request()
    command = build_entry_command(request, now=request.requested_at)
    broker = FakeBroker()
    broker.orders[command.client_order_id] = snapshot_for(command).model_copy(
        update={"limit_price": command.limit_price + Decimal("0.01")}
    )
    result = ExecutionService(broker=broker, repository=MemoryExecutionRepository()).submit(
        request, now=request.requested_at
    )
    assert result.outcome is ExecutionOutcome.RECONCILIATION_REQUIRED


def test_existing_bracket_with_wrong_protective_leg_requires_reconciliation():
    request = execution_request()
    command = build_entry_command(request, now=request.requested_at)
    broker = FakeBroker()
    existing = snapshot_for(command)
    wrong_stop = existing.legs[1].model_copy(
        update={"stop_price": command.stop_loss_stop_price - Decimal("0.01")}
    )
    broker.orders[command.client_order_id] = existing.model_copy(
        update={"legs": (existing.legs[0], wrong_stop)}
    )

    result = ExecutionService(broker=broker, repository=MemoryExecutionRepository()).submit(
        request, now=request.requested_at
    )

    assert result.outcome is ExecutionOutcome.RECONCILIATION_REQUIRED
    assert result.rejection_reasons == (ExecutionRejectionCode.BROKER_ORDER_MISMATCH,)


def test_partial_fill_waits_for_confirmed_cancel_before_protective_order():
    request = execution_request()

    class CancelNotConfirmed(FakeBroker):
        def cancel_order(self, broker_order_id):
            self.canceled.append(broker_order_id)

    broker = CancelNotConfirmed()
    service = ExecutionService(broker=broker, repository=MemoryExecutionRepository())
    submitted = service.submit(request, now=request.requested_at)
    partial = submitted.broker_order.model_copy(
        update={
            "snapshot_id": "cancel-pending-partial",
            "status": BrokerOrderStatus.PARTIALLY_FILLED,
            "filled_quantity": Decimal("2"),
            "updated_at": request.requested_at + timedelta(seconds=1),
        }
    )
    broker.orders[partial.client_order_id] = partial
    update = TradeUpdate(
        event_id="cancel-pending-update",
        event="partial_fill",
        event_timestamp=partial.updated_at,
        order=partial,
        raw_event_hash=canonical_sha256({"cancel": "pending"}),
    )

    result = service.handle_trade_update(request, update)

    assert result.outcome is ExecutionOutcome.RECONCILIATION_REQUIRED
    assert len(broker.submitted) == 1


def test_immediate_partial_ack_enters_protection_path():
    request = execution_request()

    class ImmediatePartialBroker(FakeBroker):
        def submit_order(self, command):
            self.submitted.append(command)
            if command.side.value == "buy":
                order = snapshot_for(
                    command,
                    status=BrokerOrderStatus.PARTIALLY_FILLED,
                    filled="2",
                    order_id="parent-immediate-partial",
                )
            else:
                order = snapshot_for(command, order_id="protective-immediate")
            self.orders[command.client_order_id] = order
            return order

    broker = ImmediatePartialBroker()
    result = ExecutionService(broker=broker, repository=MemoryExecutionRepository()).submit(
        request, now=request.requested_at
    )
    assert result.outcome is ExecutionOutcome.PARTIAL_FILL_PROTECTED
    assert result.protective_order is not None
    assert len(broker.submitted) == 2
