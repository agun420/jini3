from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps
from threading import RLock
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from daybreak_risk.enums import ReservationStatus

from .broker import BrokerClient
from .canonical import canonical_sha256
from .enums import (
    BrokerOrderStatus,
    ExecutionEventType,
    ExecutionOutcome,
    ExecutionRejectionCode,
)
from .errors import BrokerNotFound, BrokerTransportError
from .models import (
    BrokerOrderCommand,
    BrokerOrderSnapshot,
    ExecutionEvent,
    ExecutionRequest,
    ExecutionResult,
    TradeUpdate,
)
from .order_builder import build_entry_command, build_partial_fill_protective_stop
from .persistence import ExecutionRepository
from .reservations import NullReservationEventSink, ReservationEventSink


def _synchronized[F: Callable[..., Any]](method: F) -> F:
    @wraps(method)
    def wrapper(self: ExecutionService, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast(F, wrapper)


class ExecutionService:
    """Paper-only Alpaca execution coordinator with fail-closed idempotency."""

    def __init__(
        self,
        *,
        broker: BrokerClient,
        repository: ExecutionRepository,
        reservation_events: ReservationEventSink | None = None,
    ) -> None:
        self._broker = broker
        self._repository = repository
        self._reservation_events = reservation_events or NullReservationEventSink()
        self._lock = RLock()

    def _event(
        self,
        request: ExecutionRequest,
        event_type: ExecutionEventType,
        *,
        timestamp: datetime,
        order: BrokerOrderSnapshot | None = None,
        command: BrokerOrderCommand | None = None,
        details: dict[str, object] | None = None,
    ) -> ExecutionEvent:
        sequence = self._repository.next_event_sequence(request.execution_id)
        payload = {
            "execution_id": request.execution_id,
            "event_sequence": sequence,
            "event_type": event_type,
            "event_timestamp": timestamp,
            "broker_order_id": None if order is None else order.broker_order_id,
            "client_order_id": (
                order.client_order_id
                if order is not None
                else (None if command is None else command.client_order_id)
            ),
            "status": None if order is None else order.status.value,
            "filled_quantity": None if order is None else order.filled_quantity,
            "details": details or {},
        }
        event = ExecutionEvent.model_validate({**payload, "event_hash": canonical_sha256(payload)})
        self._repository.append_event(event)
        return event

    def _result(
        self,
        request: ExecutionRequest,
        *,
        outcome: ExecutionOutcome,
        reasons: tuple[ExecutionRejectionCode, ...],
        command: BrokerOrderCommand | None,
        broker_order: BrokerOrderSnapshot | None,
        protective_order: BrokerOrderSnapshot | None = None,
        reconciliation_required: bool,
        completed_at: datetime,
    ) -> ExecutionResult:
        events = self._repository.list_events(request.execution_id)
        request_hash = canonical_sha256(request)
        core = {
            "execution_id": request.execution_id,
            "outcome": outcome,
            "rejection_reasons": reasons,
            "command": command,
            "broker_order": broker_order,
            "protective_order": protective_order,
            "reconciliation_required": reconciliation_required,
            "events": events,
            "completed_at": completed_at,
            "request_hash": request_hash,
        }
        result_hash = canonical_sha256(core)
        result_id = uuid5(
            NAMESPACE_URL, f"daybreak-execution-result:{request.execution_id}:{result_hash}"
        ).hex
        result = ExecutionResult.model_validate(
            {**core, "result_id": result_id, "result_hash": result_hash}
        )
        self._repository.save_result(result)
        return result

    @staticmethod
    def _matches(command: BrokerOrderCommand, order: BrokerOrderSnapshot) -> bool:
        prices_match = True
        if command.limit_price is not None:
            prices_match = order.limit_price == command.limit_price
        if command.stop_price is not None:
            prices_match = prices_match and order.stop_price == command.stop_price
        identity_matches = (
            command.client_order_id == order.client_order_id
            and command.symbol == order.symbol
            and command.side is order.side
            and command.order_type is order.order_type
            and command.time_in_force.value == order.time_in_force
            and command.order_class.value == order.order_class
            and Decimal(command.quantity) == order.quantity
            and prices_match
        )
        if not identity_matches:
            return False
        if command.order_class.value != "bracket":
            return True
        take_profit_legs = [
            leg
            for leg in order.legs
            if leg.side == "sell"
            and leg.order_type == "limit"
            and leg.limit_price == command.take_profit_limit_price
            and leg.quantity == Decimal(command.quantity)
        ]
        stop_loss_legs = [
            leg
            for leg in order.legs
            if leg.side == "sell"
            and leg.order_type in {"stop", "stop_limit"}
            and leg.stop_price == command.stop_loss_stop_price
            and leg.quantity == Decimal(command.quantity)
        ]
        return len(order.legs) == 2 and len(take_profit_legs) == 1 and len(stop_loss_legs) == 1

    @staticmethod
    def _terminal_rejection(order: BrokerOrderSnapshot) -> bool:
        return order.status in {
            BrokerOrderStatus.REJECTED,
            BrokerOrderStatus.CANCELED,
            BrokerOrderStatus.EXPIRED,
        }

    @staticmethod
    def _broker_state_requires_reconciliation(order: BrokerOrderSnapshot) -> bool:
        return order.status in {
            BrokerOrderStatus.DONE_FOR_DAY,
            BrokerOrderStatus.SUSPENDED,
            BrokerOrderStatus.STOPPED,
            BrokerOrderStatus.PENDING_REPLACE,
        }

    def _record_reservation_from_order(
        self, request: ExecutionRequest, order: BrokerOrderSnapshot, at: datetime
    ) -> None:
        reservation = request.risk_decision.reservation
        if reservation is None:
            return
        mapping = {
            BrokerOrderStatus.PARTIALLY_FILLED: ReservationStatus.PARTIALLY_FILLED,
            BrokerOrderStatus.FILLED: ReservationStatus.FILLED,
            BrokerOrderStatus.CANCELED: ReservationStatus.RELEASED,
            BrokerOrderStatus.EXPIRED: ReservationStatus.EXPIRED,
            BrokerOrderStatus.REJECTED: ReservationStatus.RELEASED,
        }
        status = mapping.get(order.status, ReservationStatus.SUBMITTED)
        self._reservation_events.append_status(
            reservation.reservation_id,
            status,
            at,
            {
                "broker_order_id": order.broker_order_id,
                "filled_quantity": str(order.filled_quantity),
            },
        )

    @_synchronized
    def submit(self, request: ExecutionRequest, *, now: datetime | None = None) -> ExecutionResult:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        self._repository.save_request(request)
        self._event(request, ExecutionEventType.REQUEST_ACCEPTED, timestamp=now)
        if request.policy.mode.value != "paper" or request.policy.allow_live_execution:
            self._event(
                request,
                ExecutionEventType.REJECTED,
                timestamp=now,
                details={"reason": ExecutionRejectionCode.PAPER_MODE_REQUIRED.value},
            )
            return self._result(
                request,
                outcome=ExecutionOutcome.REJECTED,
                reasons=(ExecutionRejectionCode.PAPER_MODE_REQUIRED,),
                command=None,
                broker_order=None,
                reconciliation_required=False,
                completed_at=now,
            )
        request_age_ms = (now - request.requested_at).total_seconds() * 1000
        if request_age_ms < 0 or request_age_ms > request.policy.max_request_age_ms:
            self._event(
                request,
                ExecutionEventType.REJECTED,
                timestamp=now,
                details={"reason": ExecutionRejectionCode.REQUEST_STALE.value},
            )
            return self._result(
                request,
                outcome=ExecutionOutcome.REJECTED,
                reasons=(ExecutionRejectionCode.REQUEST_STALE,),
                command=None,
                broker_order=None,
                reconciliation_required=False,
                completed_at=now,
            )
        try:
            command = build_entry_command(request, now=now)
        except ValueError as exc:
            message = str(exc)
            if "cutoff" in message:
                reason = ExecutionRejectionCode.SUBMISSION_CUTOFF_EXCEEDED
            elif "expired" in message:
                reason = ExecutionRejectionCode.RESERVATION_EXPIRED
            elif "approved" in message:
                reason = ExecutionRejectionCode.RISK_DECISION_NOT_APPROVED
            elif "reservation" in message:
                reason = ExecutionRejectionCode.RESERVATION_MISSING
            else:
                reason = ExecutionRejectionCode.INVALID_ORDER_GEOMETRY
            self._event(
                request,
                ExecutionEventType.REJECTED,
                timestamp=now,
                details={"reason": reason.value},
            )
            return self._result(
                request,
                outcome=ExecutionOutcome.REJECTED,
                reasons=(reason,),
                command=None,
                broker_order=None,
                reconciliation_required=False,
                completed_at=now,
            )
        existing_local = self._repository.get_command_by_client_order_id(command.client_order_id)
        if existing_local is not None and existing_local != command:
            return self._result(
                request,
                outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                reasons=(ExecutionRejectionCode.COMMAND_IDENTITY_CONFLICT,),
                command=command,
                broker_order=None,
                reconciliation_required=True,
                completed_at=now,
            )
        self._repository.save_command(command)
        self._event(request, ExecutionEventType.COMMAND_PERSISTED, timestamp=now, command=command)
        self._event(request, ExecutionEventType.BROKER_LOOKUP, timestamp=now, command=command)
        try:
            existing = self._broker.get_order_by_client_order_id(command.client_order_id)
        except BrokerNotFound:
            existing = None
        except BrokerTransportError:
            return self._result(
                request,
                outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                reasons=(ExecutionRejectionCode.BROKER_TRANSPORT_FAILURE,),
                command=command,
                broker_order=None,
                reconciliation_required=True,
                completed_at=now,
            )
        if existing is not None:
            self._repository.save_snapshot(request.execution_id, existing)
            self._event(
                request, ExecutionEventType.BROKER_ACKNOWLEDGED, timestamp=now, order=existing
            )
            self._record_reservation_from_order(request, existing, now)
            if not self._matches(command, existing):
                return self._result(
                    request,
                    outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                    reasons=(ExecutionRejectionCode.BROKER_ORDER_MISMATCH,),
                    command=command,
                    broker_order=existing,
                    reconciliation_required=True,
                    completed_at=now,
                )
            if self._terminal_rejection(existing):
                return self._result(
                    request,
                    outcome=ExecutionOutcome.REJECTED,
                    reasons=(ExecutionRejectionCode.BROKER_REJECTED,),
                    command=command,
                    broker_order=existing,
                    reconciliation_required=False,
                    completed_at=now,
                )
            if self._broker_state_requires_reconciliation(existing):
                return self._result(
                    request,
                    outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                    reasons=(ExecutionRejectionCode.BROKER_TRANSPORT_FAILURE,),
                    command=command,
                    broker_order=existing,
                    reconciliation_required=True,
                    completed_at=now,
                )
            if (
                existing.status is BrokerOrderStatus.PARTIALLY_FILLED
                and existing.filled_quantity > 0
                and request.policy.partial_fill_protection_enabled
            ):
                update = TradeUpdate(
                    event_id=f"initial-{existing.snapshot_id}",
                    event="partial_fill",
                    event_timestamp=existing.updated_at,
                    order=existing,
                    raw_event_hash=existing.raw_response_hash,
                )
                return self.handle_trade_update(request, update)
            return self._result(
                request,
                outcome=ExecutionOutcome.EXISTING_RECONCILED,
                reasons=(),
                command=command,
                broker_order=existing,
                reconciliation_required=False,
                completed_at=now,
            )
        self._event(request, ExecutionEventType.SUBMIT_STARTED, timestamp=now, command=command)
        try:
            order = self._broker.submit_order(command)
        except BrokerTransportError as exc:
            if exc.transient:
                try:
                    order = self._broker.get_order_by_client_order_id(command.client_order_id)
                except (BrokerNotFound, BrokerTransportError):
                    self._event(
                        request,
                        ExecutionEventType.RECONCILIATION_REQUIRED,
                        timestamp=now,
                        command=command,
                        details={"reason": "ambiguous_submit_state"},
                    )
                    return self._result(
                        request,
                        outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                        reasons=(ExecutionRejectionCode.BROKER_TIMEOUT_UNKNOWN_STATE,),
                        command=command,
                        broker_order=None,
                        reconciliation_required=True,
                        completed_at=now,
                    )
            else:
                return self._result(
                    request,
                    outcome=ExecutionOutcome.REJECTED,
                    reasons=(ExecutionRejectionCode.BROKER_REJECTED,),
                    command=command,
                    broker_order=None,
                    reconciliation_required=False,
                    completed_at=now,
                )
        self._repository.save_snapshot(request.execution_id, order)
        self._event(request, ExecutionEventType.BROKER_ACKNOWLEDGED, timestamp=now, order=order)
        self._record_reservation_from_order(request, order, now)
        if not self._matches(command, order):
            return self._result(
                request,
                outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                reasons=(ExecutionRejectionCode.BROKER_ORDER_MISMATCH,),
                command=command,
                broker_order=order,
                reconciliation_required=True,
                completed_at=now,
            )
        if self._terminal_rejection(order):
            return self._result(
                request,
                outcome=ExecutionOutcome.REJECTED,
                reasons=(ExecutionRejectionCode.BROKER_REJECTED,),
                command=command,
                broker_order=order,
                reconciliation_required=False,
                completed_at=now,
            )
        if self._broker_state_requires_reconciliation(order):
            return self._result(
                request,
                outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                reasons=(ExecutionRejectionCode.BROKER_TRANSPORT_FAILURE,),
                command=command,
                broker_order=order,
                reconciliation_required=True,
                completed_at=now,
            )
        if (
            order.status is BrokerOrderStatus.PARTIALLY_FILLED
            and order.filled_quantity > 0
            and request.policy.partial_fill_protection_enabled
        ):
            update = TradeUpdate(
                event_id=f"initial-{order.snapshot_id}",
                event="partial_fill",
                event_timestamp=order.updated_at,
                order=order,
                raw_event_hash=order.raw_response_hash,
            )
            return self.handle_trade_update(request, update)
        return self._result(
            request,
            outcome=ExecutionOutcome.SUBMITTED,
            reasons=(),
            command=command,
            broker_order=order,
            reconciliation_required=False,
            completed_at=now,
        )

    @_synchronized
    def cancel_stale_entry(
        self,
        request: ExecutionRequest,
        order: BrokerOrderSnapshot,
        *,
        now: datetime | None = None,
    ) -> bool:
        now = (now or datetime.now(UTC)).astimezone(UTC)
        if order.filled_quantity > 0 or order.status in {
            BrokerOrderStatus.FILLED,
            BrokerOrderStatus.CANCELED,
            BrokerOrderStatus.EXPIRED,
            BrokerOrderStatus.REJECTED,
        }:
            return False
        anchor = order.submitted_at or order.updated_at
        if (now - anchor).total_seconds() < request.policy.cancel_unfilled_after_seconds:
            return False
        self._broker.cancel_order(order.broker_order_id)
        self._event(request, ExecutionEventType.CANCEL_REQUESTED, timestamp=now, order=order)
        return True

    @_synchronized
    def handle_trade_update(
        self,
        request: ExecutionRequest,
        update: TradeUpdate,
    ) -> ExecutionResult:
        now = update.event_timestamp
        claimed = self._repository.claim_trade_update(
            update.event_id, request.execution_id, update.raw_event_hash
        )
        command = self._repository.get_command_by_client_order_id(update.order.client_order_id)
        if not claimed:
            if command is None:
                return self._result(
                    request,
                    outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                    reasons=(ExecutionRejectionCode.COMMAND_IDENTITY_CONFLICT,),
                    command=None,
                    broker_order=update.order,
                    reconciliation_required=True,
                    completed_at=now,
                )
            return self._result(
                request,
                outcome=ExecutionOutcome.EXISTING_RECONCILED,
                reasons=(),
                command=command,
                broker_order=update.order,
                reconciliation_required=False,
                completed_at=now,
            )
        if command is None:
            return self._result(
                request,
                outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                reasons=(ExecutionRejectionCode.COMMAND_IDENTITY_CONFLICT,),
                command=None,
                broker_order=update.order,
                reconciliation_required=True,
                completed_at=now,
            )
        self._repository.save_snapshot(request.execution_id, update.order)
        self._event(
            request,
            ExecutionEventType.TRADE_UPDATE,
            timestamp=now,
            order=update.order,
            details={"provider_event": update.event, "raw_event_hash": update.raw_event_hash},
        )
        self._record_reservation_from_order(request, update.order, now)
        if (
            update.order.status is BrokerOrderStatus.PARTIALLY_FILLED
            and update.order.filled_quantity > 0
            and request.policy.partial_fill_protection_enabled
        ):
            self._event(
                request, ExecutionEventType.CANCEL_REQUESTED, timestamp=now, order=update.order
            )
            try:
                self._broker.cancel_order(update.order.broker_order_id)
                final_parent = self._broker.get_order(update.order.broker_order_id)
                self._repository.save_snapshot(request.execution_id, final_parent)
                if final_parent.status is BrokerOrderStatus.FILLED:
                    if not self._matches(command, final_parent):
                        raise ValueError("filled bracket no longer matches its command")
                    return self._result(
                        request,
                        outcome=ExecutionOutcome.EXISTING_RECONCILED,
                        reasons=(),
                        command=command,
                        broker_order=final_parent,
                        reconciliation_required=False,
                        completed_at=now,
                    )
                if final_parent.status is not BrokerOrderStatus.CANCELED:
                    raise ValueError("parent cancellation was not confirmed")
                if final_parent.filled_quantity <= 0:
                    raise ValueError("canceled parent has no protected fill")
                if final_parent.filled_quantity != final_parent.filled_quantity.to_integral_value():
                    raise ValueError("whole-share order returned fractional partial fill")
                protective_command = build_partial_fill_protective_stop(
                    request, filled_quantity=int(final_parent.filled_quantity)
                )
                self._repository.save_command(protective_command)
                self._event(
                    request,
                    ExecutionEventType.PROTECTIVE_STOP_SUBMIT_STARTED,
                    timestamp=now,
                    command=protective_command,
                )
                try:
                    protective = self._broker.get_order_by_client_order_id(
                        protective_command.client_order_id
                    )
                except BrokerNotFound:
                    protective = self._broker.submit_order(protective_command)
                if not self._matches(protective_command, protective):
                    raise ValueError("protective stop does not match its command")
                self._repository.save_snapshot(request.execution_id, protective)
                self._event(
                    request,
                    ExecutionEventType.PROTECTIVE_STOP_ACKNOWLEDGED,
                    timestamp=now,
                    order=protective,
                )
                return self._result(
                    request,
                    outcome=ExecutionOutcome.PARTIAL_FILL_PROTECTED,
                    reasons=(),
                    command=command,
                    broker_order=final_parent,
                    protective_order=protective,
                    reconciliation_required=True,
                    completed_at=now,
                )
            except (BrokerNotFound, BrokerTransportError, ValueError):
                return self._result(
                    request,
                    outcome=ExecutionOutcome.RECONCILIATION_REQUIRED,
                    reasons=(ExecutionRejectionCode.PARTIAL_FILL_PROTECTION_FAILED,),
                    command=command,
                    broker_order=update.order,
                    reconciliation_required=True,
                    completed_at=now,
                )
        return self._result(
            request,
            outcome=ExecutionOutcome.EXISTING_RECONCILED,
            reasons=(),
            command=command,
            broker_order=update.order,
            reconciliation_required=False,
            completed_at=now,
        )
