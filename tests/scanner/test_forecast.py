from datetime import date as date_cls
from datetime import timedelta
from decimal import Decimal

import pytest

from daybreak_features.models import DailyBar
from daybreak_scanner.forecast import (
    ForecastError,
    TimesFMForecaster,
    daily_closes_by_ticker,
    trend_pct,
)


def _bar(day: int, close: str) -> DailyBar:
    return DailyBar(
        session_date=date_cls(2026, 1, 1) + timedelta(days=day),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=100,
    )


def test_trend_pct_computes_percent_change_from_last_close():
    closes = [Decimal("10"), Decimal("20")]
    forecast = [Decimal("22"), Decimal("24")]
    assert trend_pct(closes, forecast) == Decimal("20")


def test_trend_pct_is_none_without_closes_or_forecast():
    assert trend_pct([], [Decimal("1")]) is None
    assert trend_pct([Decimal("1")], []) is None


def test_trend_pct_is_none_when_last_close_is_zero():
    assert trend_pct([Decimal("0")], [Decimal("1")]) is None


def test_daily_closes_by_ticker_orders_oldest_first_and_respects_lookback():
    bars = {
        "AAAA": [_bar(2, "12"), _bar(0, "10"), _bar(1, "11")],
        "BBBB": [],
    }
    result = daily_closes_by_ticker(bars, lookback_sessions=2)
    assert result["AAAA"] == (Decimal("11"), Decimal("12"))
    assert "BBBB" not in result


def test_timesfm_forecaster_raises_forecast_error_without_timesfm_installed():
    forecaster = TimesFMForecaster()
    with pytest.raises(ForecastError, match="timesfm"):
        forecaster.forecast({"AAAA": [Decimal("10"), Decimal("11")]})


def test_timesfm_forecaster_empty_input_short_circuits():
    forecaster = TimesFMForecaster()
    assert forecaster.forecast({}) == {}
