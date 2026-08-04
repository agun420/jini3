"""Resolves a Signal's real outcome against subsequent price bars.

Pure logic, no I/O: callers fetch the bars (daybreak_scanner.alpaca_data) and
pass them in, so this is trivially testable without a live account.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from .models import MinuteBar, Signal, SignalOutcome


def _return_pct(entry_price: Decimal, exit_price: Decimal) -> Decimal:
    return (exit_price - entry_price) / entry_price * 100


def resolve_outcome(signal: Signal, bars: Sequence[MinuteBar]) -> SignalOutcome | None:
    """Walks bars in chronological order for the first stop/target touch.

    A bar whose range covers both the stop and a target is treated as a loss
    -- intrabar order can't be known from OHLC data alone, so the worse case
    is assumed rather than guessed. A bar that reaches target_price_2 without
    touching the stop resolves as the better win outright: target_price_2 is
    strictly above target_price_1, so a bar's high reaching it necessarily
    crossed target_price_1 first, and this walk would otherwise never learn
    that -- once a bar resolves the signal, later bars aren't examined,
    exactly as before this second target existed. Returns None if unresolved
    through the given bars; the caller should either fetch more bars later or
    call `expire_at_close` once the session has ended.
    """
    for bar in sorted(bars, key=lambda item: item.timestamp):
        hit_stop = bar.low <= signal.stop_price
        hit_target_2 = bar.high >= signal.target_price_2
        hit_target_1 = bar.high >= signal.target_price_1
        if hit_stop:
            return SignalOutcome(
                ticker=signal.ticker,
                trading_date=signal.trading_date,
                resolved_at=bar.timestamp,
                outcome="loss",
                exit_price=signal.stop_price,
                return_pct=_return_pct(signal.entry_price, signal.stop_price),
            )
        if hit_target_2:
            return SignalOutcome(
                ticker=signal.ticker,
                trading_date=signal.trading_date,
                resolved_at=bar.timestamp,
                outcome="win",
                target_hit="target_2",
                exit_price=signal.target_price_2,
                return_pct=_return_pct(signal.entry_price, signal.target_price_2),
            )
        if hit_target_1:
            return SignalOutcome(
                ticker=signal.ticker,
                trading_date=signal.trading_date,
                resolved_at=bar.timestamp,
                outcome="win",
                target_hit="target_1",
                exit_price=signal.target_price_1,
                return_pct=_return_pct(signal.entry_price, signal.target_price_1),
            )
    return None


def expire_at_close(signal: Signal, *, close_price: Decimal, closed_at: datetime) -> SignalOutcome:
    """Finalizes a signal that touched neither level by end of the regular
    session, using the session's closing price as the exit."""
    return SignalOutcome(
        ticker=signal.ticker,
        trading_date=signal.trading_date,
        resolved_at=closed_at,
        outcome="expired",
        exit_price=close_price,
        return_pct=_return_pct(signal.entry_price, close_price),
    )
