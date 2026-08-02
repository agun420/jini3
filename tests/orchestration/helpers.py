from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from daybreak_orchestration.canonical import canonical_sha256
from daybreak_orchestration.clock import build_session_plan
from daybreak_orchestration.models import (
    FlattenOrder,
    HealthSnapshot,
    OrchestrationPolicy,
    SessionPlan,
    SessionPosition,
)

CONFIG_HASH = "a" * 64


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class HealthyProbe:
    def __init__(self, *, configuration_hash: str = CONFIG_HASH, **overrides) -> None:
        self.configuration_hash = configuration_hash
        self.overrides = overrides

    def snapshot(self, plan: SessionPlan, *, now: datetime) -> HealthSnapshot:
        values = {
            "observed_at": now,
            "clock_synchronized": True,
            "clock_skew_ms": 0,
            "database_healthy": True,
            "recorder_healthy": True,
            "market_data_stream_healthy": True,
            "trade_update_stream_healthy": True,
            "broker_healthy": True,
            "account_active": True,
            "account_blocked": False,
            "trading_blocked": False,
            "market_status_normal": True,
            "configuration_hash": self.configuration_hash,
        }
        values.update(self.overrides)
        return HealthSnapshot(**values)


class FakeHooks:
    def __init__(
        self,
        *,
        run_status: str = "approved",
        approved_count: int = 1,
        fail_phase: str | None = None,
    ) -> None:
        self.run_status = run_status
        self.approved_count = approved_count
        self.fail_phase = fail_phase
        self.calls: list[str] = []

    def _call(self, name: str, result: dict[str, object]) -> dict[str, object]:
        self.calls.append(name)
        if self.fail_phase == name:
            raise RuntimeError(f"{name} failed")
        return result

    def warmup_recorder(self, plan, *, now, fencing_token):
        return self._call("warmup", {"recorder": "ready"})

    def freeze_features(self, plan, *, now, fencing_token):
        return self._call("features", {"snapshot_id": "snapshot-1"})

    def evaluate(self, plan, *, now, fencing_token):
        return self._call(
            "evaluate", {"run_status": self.run_status, "approved_count": self.approved_count}
        )

    def size_and_execute(self, plan, *, now, fencing_token):
        return self._call(
            "execute",
            {
                "submitted_count": self.approved_count,
                "managed_positions": {"AAPL": "5"} if self.approved_count else {},
            },
        )

    def reconcile(self, plan, *, now, fencing_token):
        return self._call("reconcile", {"matched": True})


class FakeSessionBroker:
    def __init__(self, *, sticky: bool = False, fail_close: bool = False) -> None:
        observed = datetime(2026, 8, 3, 19, 50, tzinfo=UTC)
        raw = {"symbol": "AAPL", "qty": "5"}
        self.positions = [
            SessionPosition(
                symbol="AAPL",
                quantity=Decimal("5"),
                average_entry_price=Decimal("100"),
                observed_at=observed,
                raw_response_hash=canonical_sha256(raw),
            )
        ]
        self.sticky = sticky
        self.fail_close = fail_close
        self.cancel_calls = 0
        self.close_calls = 0

    def discover_daybreak_targets(self, plan):
        from daybreak_orchestration.models import ManagedPositionTarget

        return (
            ManagedPositionTarget(
                symbol="AAPL", quantity=Decimal("5"), source="broker_order_reconstruction"
            ),
        )

    def cancel_daybreak_orders(self, plan) -> int:
        self.cancel_calls += 1
        return 2

    def list_positions(self, targets):
        quantities = {target.symbol: target.quantity for target in targets}
        return tuple(
            position.model_copy(
                update={"quantity": min(position.quantity, quantities[position.symbol])}
            )
            for position in self.positions
            if position.symbol in quantities
        )

    def close_position(self, position: SessionPosition) -> FlattenOrder:
        self.close_calls += 1
        if self.fail_close:
            raise RuntimeError("close rejected")
        order = FlattenOrder(
            symbol=position.symbol,
            quantity=position.quantity,
            broker_order_id="close-order-1",
            client_order_id="flatten-aapl",
            submitted_at=position.observed_at,
            raw_response_hash=canonical_sha256({"id": "close-order-1"}),
        )
        if not self.sticky:
            self.positions.clear()
        return order


def compressed_plan(start: datetime | None = None) -> tuple[SessionPlan, FakeClock]:
    start = start or datetime(2026, 8, 3, 7, 55, tzinfo=UTC)
    policy = OrchestrationPolicy(
        leadership_ttl_seconds=30,
        leadership_renew_interval_seconds=10,
        flatten_poll_interval_seconds=0.01,
        flatten_verification_timeout_seconds=1.0,
    )
    base = build_session_plan(
        trading_date=date(2026, 8, 3),
        run_id="run-1",
        configuration_hash=CONFIG_HASH,
        policy=policy,
    )
    plan = base.model_copy(
        update={
            "recorder_warmup_at": start,
            "feature_window_start_at": start + timedelta(seconds=1),
            "feature_snapshot_at": start + timedelta(seconds=2),
            "evaluator_cutoff_at": start + timedelta(seconds=4),
            "eligibility_lock_at": start + timedelta(seconds=5),
            "regular_session_open_at": start + timedelta(seconds=6),
            "new_entry_cutoff_at": start + timedelta(seconds=8),
            "mandatory_flatten_at": start + timedelta(seconds=10),
            "final_flatten_deadline_at": start + timedelta(seconds=12),
        }
    )
    return plan, FakeClock(start)
