from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from .models import (
    FlattenOrder,
    HealthSnapshot,
    ManagedPositionTarget,
    SessionPlan,
    SessionPosition,
)


class HealthProbe(Protocol):
    def snapshot(self, plan: SessionPlan, *, now: datetime) -> HealthSnapshot: ...


class SessionHooks(Protocol):
    """Integration boundary for recorder, feature, evaluator, risk, and execution services."""

    def warmup_recorder(
        self, plan: SessionPlan, *, now: datetime, fencing_token: int
    ) -> dict[str, object]: ...
    def freeze_features(
        self, plan: SessionPlan, *, now: datetime, fencing_token: int
    ) -> dict[str, object]: ...
    def evaluate(
        self, plan: SessionPlan, *, now: datetime, fencing_token: int
    ) -> dict[str, object]: ...
    def size_and_execute(
        self, plan: SessionPlan, *, now: datetime, fencing_token: int
    ) -> dict[str, object]: ...
    def reconcile(
        self, plan: SessionPlan, *, now: datetime, fencing_token: int
    ) -> dict[str, object]: ...


class SessionBrokerOperations(Protocol):
    def discover_daybreak_targets(self, plan: SessionPlan) -> Sequence[ManagedPositionTarget]: ...
    def cancel_daybreak_orders(self, plan: SessionPlan) -> int: ...
    def list_positions(
        self, targets: Sequence[ManagedPositionTarget]
    ) -> Sequence[SessionPosition]: ...
    def close_position(self, position: SessionPosition) -> FlattenOrder: ...
