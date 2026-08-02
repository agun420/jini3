from __future__ import annotations

import time as time_module
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from .canonical import canonical_sha256
from .models import (
    FlattenOrder,
    FlattenResult,
    ManagedPositionTarget,
    SessionPlan,
    SessionPosition,
)
from .protocols import SessionBrokerOperations

ManagedTargetSource = Literal["execution_ledger", "broker_order_reconstruction", "combined"]


class FlattenService:
    def __init__(self, broker: SessionBrokerOperations) -> None:
        self._broker = broker

    def flatten(
        self,
        plan: SessionPlan,
        *,
        now: datetime,
        managed_quantities: Mapping[str, Decimal | int | str] | None = None,
        sleep: Callable[[float], None] = time_module.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> FlattenResult:
        started_at = now.astimezone(UTC)
        errors: list[str] = []
        try:
            discovered = tuple(self._broker.discover_daybreak_targets(plan))
        except Exception as exc:
            discovered = ()
            errors.append(f"discover Daybreak quantities failed: {type(exc).__name__}: {exc}")
        targets = _merge_targets(discovered, managed_quantities or {})

        canceled_order_count = 0
        try:
            canceled_order_count = self._broker.cancel_daybreak_orders(plan)
        except Exception as exc:
            errors.append(f"cancel Daybreak orders failed: {type(exc).__name__}: {exc}")

        try:
            initial_positions = tuple(self._broker.list_positions(targets))
        except Exception as exc:
            initial_positions = ()
            errors.append(f"list Daybreak positions failed: {type(exc).__name__}: {exc}")

        close_orders: list[FlattenOrder] = []
        submitted_quantities: dict[str, Decimal] = {}

        def close_uncovered(positions: Sequence[SessionPosition]) -> None:
            for position in positions:
                already_submitted = submitted_quantities.get(position.symbol, Decimal("0"))
                uncovered = position.quantity - already_submitted
                if uncovered <= 0:
                    continue
                close_target = position.model_copy(update={"quantity": uncovered})
                try:
                    close_orders.append(self._broker.close_position(close_target))
                    submitted_quantities[position.symbol] = already_submitted + uncovered
                except Exception as exc:
                    errors.append(
                        f"close position {position.symbol} failed: {type(exc).__name__}: {exc}"
                    )

        close_uncovered(initial_positions)

        remaining = initial_positions
        verification_deadline = min(
            plan.final_flatten_deadline_at,
            started_at + timedelta(seconds=plan.policy.flatten_verification_timeout_seconds),
        )
        while clock().astimezone(UTC) < verification_deadline:
            try:
                remaining = tuple(self._broker.list_positions(targets))
            except Exception as exc:
                errors.append(f"verify Daybreak positions failed: {type(exc).__name__}: {exc}")
                break
            if not remaining:
                break
            # A parent can fill while cancellation is propagating. Close only the
            # newly uncovered quantity; never duplicate an outstanding close.
            close_uncovered(remaining)
            sleep(plan.policy.flatten_poll_interval_seconds)

        completed_at = clock().astimezone(UTC)
        core = {
            "session_id": plan.session_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "canceled_order_count": canceled_order_count,
            "initial_positions": initial_positions,
            "close_orders": tuple(close_orders),
            "remaining_positions": remaining,
            "complete": not remaining and not errors,
            "errors": tuple(errors),
        }
        result_hash = canonical_sha256(core)
        flatten_id = uuid5(NAMESPACE_URL, f"daybreak-flatten:{plan.session_id}:{result_hash}").hex
        return FlattenResult.model_validate(
            {**core, "flatten_id": flatten_id, "result_hash": result_hash}
        )


def _merge_targets(
    discovered: Sequence[ManagedPositionTarget],
    managed_quantities: Mapping[str, Decimal | int | str],
) -> tuple[ManagedPositionTarget, ...]:
    quantities: dict[str, Decimal] = {}
    sources: dict[str, set[ManagedTargetSource]] = {}
    for target in discovered:
        quantities[target.symbol] = max(
            quantities.get(target.symbol, Decimal("0")), target.quantity
        )
        sources.setdefault(target.symbol, set()).add(target.source)
    for symbol, raw_quantity in managed_quantities.items():
        quantity = Decimal(str(raw_quantity))
        if quantity <= 0:
            continue
        quantities[symbol] = max(quantities.get(symbol, Decimal("0")), quantity)
        sources.setdefault(symbol, set()).add("execution_ledger")
    targets: list[ManagedPositionTarget] = []
    for symbol in sorted(quantities):
        source: ManagedTargetSource = (
            "combined" if len(sources[symbol]) > 1 else next(iter(sources[symbol]))
        )
        targets.append(
            ManagedPositionTarget(symbol=symbol, quantity=quantities[symbol], source=source)
        )
    return tuple(targets)
