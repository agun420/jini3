from datetime import date
from decimal import Decimal

from daybreak_features.models import DailyBar
from daybreak_scanner.rvol import average_daily_volume, relative_volume


def _bar(day: int, volume: int) -> DailyBar:
    return DailyBar(
        session_date=date(2026, 7, day),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=volume,
    )


def test_average_daily_volume_uses_only_the_lookback_window():
    bars = [_bar(1, 100), _bar(2, 200), _bar(3, 300), _bar(4, 400)]
    assert average_daily_volume(bars, lookback_sessions=2) == Decimal("350")


def test_average_daily_volume_sorts_out_of_order_bars():
    bars = [_bar(3, 300), _bar(1, 100), _bar(2, 200)]
    assert average_daily_volume(bars, lookback_sessions=2) == Decimal("250")


def test_average_daily_volume_handles_fewer_bars_than_lookback():
    bars = [_bar(1, 100), _bar(2, 300)]
    assert average_daily_volume(bars, lookback_sessions=20) == Decimal("200")


def test_average_daily_volume_of_empty_history_is_none():
    assert average_daily_volume([], lookback_sessions=20) is None


def test_relative_volume_ratio():
    assert relative_volume(1000, Decimal("100")) == Decimal("10")


def test_relative_volume_is_none_without_a_baseline():
    assert relative_volume(1000, None) is None
    assert relative_volume(1000, Decimal("0")) is None
