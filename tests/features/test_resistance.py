from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from daybreak_features.errors import DataQualityError
from daybreak_features.models import DailyBar, FeatureEngineConfig
from daybreak_features.resistance import daily_pivot_cluster_v1

from .helpers import daily_bars


def test_blue_sky_uses_sentinel():
    bars = daily_bars(date(2026, 8, 3), count=60, top=Decimal("11"))
    result = daily_pivot_cluster_v1(
        bars=bars,
        current_price=Decimal("12"),
        atr=Decimal("1"),
        history_complete_since_listing=True,
        config=FeatureEngineConfig(),
    )
    assert result.chart_structure == "blue_sky"
    assert result.distance_to_resistance_atr == Decimal("99.0")
    assert result.is_blue_sky_sentinel


def test_incomplete_history_cannot_be_blue_sky():
    bars = daily_bars(date(2026, 8, 3), count=60, top=Decimal("11"))
    with pytest.raises(DataQualityError, match="INCOMPLETE_HISTORY_FOR_BLUE_SKY_CHECK"):
        daily_pivot_cluster_v1(
            bars=bars,
            current_price=Decimal("12"),
            atr=Decimal("1"),
            history_complete_since_listing=False,
            config=FeatureEngineConfig(),
        )


def test_insufficient_history_rejected():
    with pytest.raises(DataQualityError, match="INSUFFICIENT_DAILY_HISTORY"):
        daily_pivot_cluster_v1(
            bars=daily_bars(date(2026, 8, 3), count=29),
            current_price=Decimal("10"),
            atr=Decimal("1"),
            history_complete_since_listing=True,
            config=FeatureEngineConfig(),
        )


def make_cluster_bars(distance: Decimal) -> tuple[DailyBar, ...]:
    day = date(2026, 8, 3)
    template = daily_bars(day, count=60, top=Decimal("9.80"))
    bars = [
        DailyBar(
            session_date=bar.session_date,
            open=Decimal("9.50"),
            high=Decimal("9.80"),
            low=Decimal("9.20"),
            close=Decimal("9.50"),
            volume=bar.volume,
        )
        for bar in template
    ]
    target = Decimal("10") + distance
    for idx in (20, 40):
        bar = bars[idx]
        bars[idx] = DailyBar(
            session_date=bar.session_date,
            open=Decimal("9.80"),
            high=target,
            low=Decimal("9.20"),
            close=Decimal("9.80"),
            volume=bar.volume,
        )
    return tuple(bars)


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        (Decimal("0.999999"), "capped"),
        (Decimal("1.000000"), "moderate_room"),
        (Decimal("2.000000"), "moderate_room"),
        (Decimal("2.000001"), "clean_short_term"),
    ],
)
def test_distance_boundaries(distance, expected):
    result = daily_pivot_cluster_v1(
        bars=make_cluster_bars(distance),
        current_price=Decimal("10"),
        atr=Decimal("1"),
        history_complete_since_listing=True,
        config=FeatureEngineConfig(),
    )
    assert result.distance_to_resistance_atr == distance
    assert result.chart_structure == expected


def test_price_inside_zone_is_capped():
    bars = make_cluster_bars(Decimal("0.5"))
    result = daily_pivot_cluster_v1(
        bars=bars,
        current_price=Decimal("10.5"),
        atr=Decimal("1"),
        history_complete_since_listing=True,
        config=FeatureEngineConfig(),
    )
    assert result.distance_to_resistance_atr == Decimal("0.000000")
    assert result.chart_structure == "capped"


def test_split_only_bar_contract_rejects_dividend_adjustment():
    day = date(2026, 8, 3)
    with pytest.raises(ValidationError):
        DailyBar(
            session_date=day,
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10"),
            volume=100,
            dividend_adjusted=True,
        )
