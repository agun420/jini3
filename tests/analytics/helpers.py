from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from daybreak_analytics.enums import ExitReason, ReplayComponent
from daybreak_analytics.models import (
    FullSessionReplayRequest,
    ReplayComponentEvidence,
    SessionEvidence,
    TradeOutcome,
)
from daybreak_analytics.replay import build_full_session_replay_report

H = "a" * 64


def make_trade(
    *,
    session_id: str = "SESSION01",
    trade_id: str = "TRADE001",
    pnl_sign: int = 1,
    ticker: str = "AAPL",
    risk_flags: tuple[str, ...] = (),
) -> TradeOutcome:
    entry = Decimal("10.00")
    exit_price = Decimal("11.00") if pnl_sign > 0 else Decimal("9.00") if pnl_sign < 0 else entry
    return TradeOutcome(
        trade_id=trade_id,
        session_id=session_id,
        ticker=ticker,
        final_rank=1,
        quantity=10,
        entry_timestamp=datetime(2026, 8, 3, 13, 30, tzinfo=UTC),
        exit_timestamp=datetime(2026, 8, 3, 14, 30, tzinfo=UTC),
        planned_entry_price=entry,
        average_entry_price=Decimal("10.05"),
        planned_stop_price=Decimal("9.00"),
        planned_target_price=Decimal("12.00"),
        average_exit_price=exit_price,
        fees=Decimal("0.10"),
        source_type="primary",
        chart_structure="clean_short_term",
        risk_flags=risk_flags,
        exit_reason=ExitReason.TARGET if pnl_sign > 0 else ExitReason.STOP,
    )


def make_session(
    *,
    index: int = 0,
    clean: bool = True,
    trades: tuple[TradeOutcome, ...] | None = None,
) -> SessionEvidence:
    session_id = f"SESSION{index:02d}"
    if trades is None:
        trades = (
            make_trade(session_id=session_id, trade_id=f"TRADE{index:02d}A", pnl_sign=1),
            make_trade(
                session_id=session_id, trade_id=f"TRADE{index:02d}B", pnl_sign=-1, ticker="MSFT"
            ),
        )
    return SessionEvidence(
        session_id=session_id,
        trading_date=date(2026, 7, 1) + timedelta(days=index),
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        configuration_hash=H,
        full_session_recorded=clean,
        raw_event_count=1000,
        evaluator_run_count=1,
        approved_setup_count=min(3, len(trades)),
        qualified_not_selected_count=0,
        excluded_ticker_count=1,
        orders_submitted=len(trades),
        orders_filled=len(trades),
        invariant_violations=0 if clean else 1,
        unresolved_reconciliations=0,
        duplicate_order_count=0,
        late_primary_response_count=0,
        all_positions_flat=True,
        kill_switch_activation_count=0,
        trades=trades,
    )


def make_replay(session: SessionEvidence, *, passed: bool = True):
    components = []
    for component in sorted(ReplayComponent, key=lambda item: item.value):
        expected = hashlib.sha256(component.value.encode("utf-8")).hexdigest()
        actual = expected if passed else ("f" * 64)
        components.append(
            ReplayComponentEvidence(
                component=component,
                expected_hash=expected,
                actual_hash=actual,
                evidence_count=1,
                verified=passed,
                errors=() if passed else ("mismatch",),
            )
        )
    request = FullSessionReplayRequest(
        session_id=session.session_id,
        trading_date=session.trading_date,
        replayed_at=datetime(2026, 8, 1, tzinfo=UTC),
        expected_raw_event_count=session.raw_event_count,
        actual_raw_event_count=session.raw_event_count,
        event_ordering_verified=True,
        point_in_time_integrity_verified=True,
        components=tuple(components),
    )
    return build_full_session_replay_report(request)
