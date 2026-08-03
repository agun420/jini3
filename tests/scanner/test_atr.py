from datetime import date, timedelta
from decimal import Decimal

from daybreak_features.models import DailyBar
from daybreak_scanner.atr import wilder_atr


def _bar(day: int, *, high: str, low: str, close: str) -> DailyBar:
    return DailyBar(
        session_date=date(2026, 1, 1) + timedelta(days=day),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=100,
    )


def test_wilder_atr_is_none_with_insufficient_history():
    bars = [_bar(i, high="11", low="9", close="10") for i in range(10)]
    assert wilder_atr(bars, period=14) is None


def test_wilder_atr_of_a_constant_true_range_series_equals_that_range():
    # 15 bars => 14 true-range values, each exactly 2 (11-9), close always 10
    bars = [_bar(i, high="11", low="9", close="10") for i in range(15)]
    assert wilder_atr(bars, period=14) == Decimal("2")


def test_wilder_atr_smooths_a_later_spike():
    bars = [_bar(i, high="11", low="9", close="10") for i in range(15)]
    # 16th bar: true range vs previous close (10) is high(26)-low(10)=16
    bars.append(_bar(15, high="26", low="10", close="20"))
    # ATR after 14 constant TRs of 2 is 2; Wilder step: (2*13 + 16) / 14 = 3
    assert wilder_atr(bars, period=14) == Decimal("3")


def test_wilder_atr_sorts_out_of_order_bars():
    ordered = [_bar(i, high="11", low="9", close="10") for i in range(15)]
    shuffled = [ordered[3], ordered[0], ordered[14]] + ordered[1:3] + ordered[4:14]
    assert wilder_atr(shuffled, period=14) == wilder_atr(ordered, period=14)
