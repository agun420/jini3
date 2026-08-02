from datetime import date
from decimal import Decimal

import pytest

from daybreak_features.core_features import (
    current_price,
    current_session_trades,
    distance_from_vwap_atr,
    gap_pct,
    premarket_low,
    premarket_volume,
    premarket_vwap,
    rvol_time_matched,
    volume_profile,
    wilder_atr_14,
)
from daybreak_features.errors import DataQualityError
from daybreak_features.models import FeatureEngineConfig

from .helpers import daily_bars, dt, historical_sessions, trade_events


def test_gap_percentage():
    assert gap_pct(Decimal("12"), Decimal("10")) == Decimal("20.000000")


def test_gap_rejects_zero_close():
    with pytest.raises(DataQualityError, match="INVALID_PREVIOUS_CLOSE"):
        gap_pct(Decimal("12"), Decimal("0"))


def test_current_trades_volume_vwap_and_low():
    day = date(2026, 8, 3)
    config = FeatureEngineConfig()
    trades = current_session_trades(trade_events(day, count=3, size=100), dt(day, 9, 23), config)
    assert current_price(trades) == Decimal("12.02")
    assert premarket_low(trades) == Decimal("12.00")
    assert premarket_volume(trades) == 300
    assert premarket_vwap(trades) == Decimal("12.010000")


def test_distance_from_vwap():
    assert distance_from_vwap_atr(Decimal("12"), Decimal("11"), Decimal("0.5")) == Decimal(
        "2.000000"
    )


def test_atr_is_positive_and_deterministic():
    bars = daily_bars(date(2026, 8, 3), count=30)
    first = wilder_atr_14(bars)
    second = wilder_atr_14(tuple(bars))
    assert first == second
    assert first > 0


def test_atr_requires_15_bars():
    with pytest.raises(DataQualityError, match="INSUFFICIENT_ATR_HISTORY"):
        wilder_atr_14(daily_bars(date(2026, 8, 3), count=14))


def test_rvol_time_matched():
    day = date(2026, 8, 3)
    result = rvol_time_matched(
        600_000, historical_sessions(day), dt(day, 9, 23), FeatureEngineConfig()
    )
    assert result == Decimal("10.000000")


def test_rvol_requires_twenty_sessions():
    day = date(2026, 8, 3)
    with pytest.raises(DataQualityError, match="INSUFFICIENT_RVOL_HISTORY"):
        rvol_time_matched(
            600_000, historical_sessions(day)[:19], dt(day, 9, 23), FeatureEngineConfig()
        )


def test_distributed_volume_is_clean():
    day = date(2026, 8, 3)
    config = FeatureEngineConfig()
    trades = current_session_trades(trade_events(day, count=50, size=100), dt(day, 9, 23), config)
    assert volume_profile(trades, dt(day, 9, 23), config) == "clean"


def test_concentrated_volume_is_spiky():
    day = date(2026, 8, 3)
    config = FeatureEngineConfig()
    trades = current_session_trades(trade_events(day, count=1, size=1000), dt(day, 9, 23), config)
    assert volume_profile(trades, dt(day, 9, 23), config) == "spiky"
