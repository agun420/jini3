"""Wilder's ATR-14, computed from daily bars alone -- no float or evaluator dependency.

This deliberately mirrors daybreak_features.FeatureEngineConfig.atr_period (14) and
daybreak_risk's TradeParameters fixed multiples (1.0x ATR stop, 2.0x ATR target) so
a scanner-generated signal uses the same numeric rule as the audited system's own
risk engine, without needing to run the full feature engine or evaluator to get it.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal

from daybreak_features.models import DailyBar

ATR_PERIOD = 14

# Matches the `Money` type's `decimal_places=6` in daybreak_scanner.models: Decimal
# division below doesn't terminate cleanly (e.g. sums divided by 14), so it keeps
# growing digits up to the active decimal context's precision if left unquantized.
_ATR_QUANTUM = Decimal("0.000001")


def wilder_atr(bars: Sequence[DailyBar], *, period: int = ATR_PERIOD) -> Decimal | None:
    """The most recent Wilder-smoothed ATR value, or None with insufficient history.

    Needs at least `period + 1` bars (period true-range values, each of which
    needs a prior close) sorted by session_date; returns None rather than a
    result computed from partial/insufficient history.
    """
    ordered = sorted(bars, key=lambda bar: bar.session_date)
    if len(ordered) < period + 1:
        return None
    true_ranges: list[Decimal] = []
    for previous, current in zip(ordered, ordered[1:], strict=False):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    atr = sum(true_ranges[:period], Decimal("0")) / Decimal(period)
    for true_range in true_ranges[period:]:
        atr = (atr * Decimal(period - 1) + true_range) / Decimal(period)
    return atr.quantize(_ATR_QUANTUM, rounding=ROUND_HALF_EVEN)
