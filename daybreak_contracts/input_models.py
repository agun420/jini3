from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from .base import StrictFrozenModel
from .enums import (
    BorrowStatus,
    ChartStructure,
    DisqualifierFlag,
    MarketStatus,
    SourceType,
    VolumeProfile,
)
from .types import CanonicalTicker, UTCZTimestamp

NonNegativeFloat = Annotated[float, Field(ge=0)]
PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
BoundedText = Annotated[str, Field(min_length=1, max_length=4000)]
SourceName = Annotated[str, Field(min_length=1, max_length=256)]
PositiveInt = Annotated[int, Field(gt=0)]


class NewsContext(StrictFrozenModel):
    catalyst_text: BoundedText
    source_type: SourceType
    source_name: SourceName
    source_timestamp: UTCZTimestamp
    catalyst_age_hours: NonNegativeFloat
    corroborated: bool
    disqualifier_flags: Annotated[tuple[DisqualifierFlag, ...], Field(max_length=5)]

    @model_validator(mode="after")
    def validate_disqualifier_uniqueness(self) -> NewsContext:
        if len(self.disqualifier_flags) != len(set(self.disqualifier_flags)):
            raise ValueError("disqualifier_flags must not contain duplicates")
        return self


class LiquidityMetrics(StrictFrozenModel):
    gap_pct: float
    premarket_volume: NonNegativeInt
    rvol_time_matched: NonNegativeFloat
    float_shares: PositiveInt
    volume_profile: VolumeProfile
    borrow_status: BorrowStatus


class TechnicalContext(StrictFrozenModel):
    distance_to_resistance_atr: NonNegativeFloat
    distance_from_vwap_atr: float
    chart_structure: ChartStructure
    current_price: PositiveFloat
    atr_value: PositiveFloat
    premarket_low: PositiveFloat

    @model_validator(mode="after")
    def validate_structure_distance_pair(self) -> TechnicalContext:
        if (
            self.chart_structure == ChartStructure.CLEAN_SHORT_TERM
            and self.distance_to_resistance_atr <= 2.0
        ):
            raise ValueError("clean_short_term requires distance_to_resistance_atr > 2.0")
        if self.chart_structure == ChartStructure.MODERATE_ROOM and not (
            1.0 <= self.distance_to_resistance_atr <= 2.0
        ):
            raise ValueError("moderate_room requires distance_to_resistance_atr in [1.0, 2.0]")
        if self.premarket_low > self.current_price:
            raise ValueError("premarket_low must be less than or equal to current_price")
        return self


class TickerInput(StrictFrozenModel):
    ticker: CanonicalTicker
    halted: bool
    news_context: NewsContext
    liquidity_metrics: LiquidityMetrics
    technical_context: TechnicalContext


class DaybreakInput(StrictFrozenModel):
    evaluation_timestamp: UTCZTimestamp
    payload_timestamp: UTCZTimestamp
    payload_age_seconds: NonNegativeInt
    catalyst_freshness_threshold_hours: PositiveFloat
    market_status: MarketStatus
    tickers: Annotated[tuple[TickerInput, ...], Field(max_length=25)]

    @model_validator(mode="after")
    def validate_unique_tickers(self) -> DaybreakInput:
        symbols = [entry.ticker for entry in self.tickers]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Duplicate valid ticker values are not permitted within one payload.")
        return self
