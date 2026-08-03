"""Builds mechanical entry/stop/target signals from qualifying candidates.

Deliberately bypasses daybreak_features/daybreak_evaluator entirely: those
packages require float data from a vendor (fmp/massive/sec_api) nobody has
credentials for yet, and score a rich conviction/thesis this scanner-mode
pivot never asked for. This produces the same fixed 1x/2x ATR risk shape
daybreak_risk always uses, from real historical bars alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

from daybreak_features.models import DailyBar

from .atr import wilder_atr
from .models import CandidateQualification, Signal


def build_signals(
    candidates: Sequence[CandidateQualification],
    bars_by_ticker: Mapping[str, Sequence[DailyBar]],
    *,
    trading_date: date,
    generated_at: datetime | None = None,
    forecast_trend_by_ticker: Mapping[str, Decimal] | None = None,
) -> tuple[Signal, ...]:
    """One Signal per qualifying candidate with enough bar history for an ATR value.

    A qualifying candidate whose ATR can't be computed (insufficient bar
    history) is silently omitted rather than given a fabricated stop/target --
    callers that need to know why should compare against `candidates` directly.

    `forecast_trend_by_ticker` is optional and purely informational (see
    daybreak_scanner.forecast): it never affects which candidates get a
    Signal or what that Signal's entry/stop/target are.
    """
    now = (generated_at or datetime.now(UTC)).astimezone(UTC)
    forecast_trend_by_ticker = forecast_trend_by_ticker or {}
    signals: list[Signal] = []
    for candidate in candidates:
        if not candidate.qualifies:
            continue
        atr = wilder_atr(bars_by_ticker.get(candidate.ticker, ()))
        if atr is None or atr <= 0:
            continue
        entry_price = candidate.price
        signals.append(
            Signal(
                ticker=candidate.ticker,
                trading_date=trading_date,
                generated_at=now,
                entry_price=entry_price,
                atr_value=atr,
                stop_price=entry_price - atr,
                target_price=entry_price + (atr * 2),
                percent_change=candidate.percent_change,
                relative_volume=candidate.relative_volume,
                forecast_trend_pct=forecast_trend_by_ticker.get(candidate.ticker),
            )
        )
    return tuple(signals)
