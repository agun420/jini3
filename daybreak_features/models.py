"""Strict immutable domain models for deterministic feature construction."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from daybreak_contracts.input_models import DaybreakInput

TICKER_PATTERN = r"^[A-Z0-9](?:[A-Z0-9.-]{0,13}[A-Z0-9])?$"
CanonicalTicker = Annotated[str, StringConstraints(pattern=TICKER_PATTERN)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
HASH_PATTERN = r"^[0-9a-f]{64}$"


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class TradeAction(StrEnum):
    NEW = "new"
    CORRECTION = "correction"
    CANCEL = "cancel"


class SourceType(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    UNCONFIRMED = "unconfirmed"


class BorrowStatus(StrEnum):
    EASY = "easy"
    HARD_TO_BORROW = "hard_to_borrow"
    UNKNOWN = "unknown"


class QualityStatus(StrEnum):
    VERIFIED = "verified"
    SINGLE_SOURCE = "single_source"


class DailyBar(StrictFrozenModel):
    session_date: date
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: int = Field(ge=0)
    split_adjusted: Literal[True] = True
    dividend_adjusted: Literal[False] = False

    @model_validator(mode="after")
    def validate_ohlc(self) -> DailyBar:
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be greater than or equal to open, close, and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be less than or equal to open, close, and high")
        return self


class TradeLedgerEvent(StrictFrozenModel):
    ingest_seq: int = Field(gt=0)
    trade_id: str = Field(min_length=1, max_length=128)
    action: TradeAction
    event_timestamp: datetime
    price: PositiveDecimal | None = None
    size: int | None = Field(default=None, gt=0)
    original_trade_id: str | None = Field(default=None, min_length=1, max_length=128)
    eligible: bool = True

    @field_validator("event_timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("event_timestamp must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def validate_action_fields(self) -> TradeLedgerEvent:
        if self.action == TradeAction.NEW:
            if self.price is None or self.size is None:
                raise ValueError("new trade requires price and size")
            if self.original_trade_id is not None:
                raise ValueError("new trade must not have original_trade_id")
        else:
            if self.original_trade_id is None:
                raise ValueError("correction/cancel requires original_trade_id")
            if self.action == TradeAction.CORRECTION and (self.price is None or self.size is None):
                raise ValueError("correction requires replacement price and size")
        return self


class PremarketSession(StrictFrozenModel):
    session_date: date
    events: tuple[TradeLedgerEvent, ...]
    complete: bool = True


class FloatRecord(StrictFrozenModel):
    ticker: CanonicalTicker
    float_shares: int = Field(gt=0)
    effective_date: date
    observed_at: datetime
    validated_at: datetime
    expires_at: datetime
    quality_status: QualityStatus
    source: Literal["fmp", "massive", "sec_api", "fixture"]
    raw_response_hashes: tuple[Annotated[str, StringConstraints(pattern=HASH_PATTERN)], ...]

    @field_validator("observed_at", "validated_at", "expires_at")
    @classmethod
    def utc_datetimes(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("float timestamps must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def validate_times(self) -> FloatRecord:
        if self.expires_at <= self.validated_at:
            raise ValueError("expires_at must follow validated_at")
        return self


Disqualifier = Literal[
    "paid_promotion",
    "reverse_split_only",
    "unconfirmed_rumor",
    "non_operating_promotion",
    "other_disqualifying_catalyst",
]


class CatalystRecord(StrictFrozenModel):
    catalyst_id: str = Field(min_length=1, max_length=256)
    ticker: CanonicalTicker
    catalyst_text: str = Field(min_length=1)
    source_type: SourceType
    source_name: str = Field(min_length=1, max_length=256)
    source_timestamp: datetime
    observed_at: datetime
    corroborated: bool
    disqualifier_flags: tuple[Disqualifier, ...] = ()
    source_hash: Annotated[str, StringConstraints(pattern=HASH_PATTERN)]

    @field_validator("source_timestamp", "observed_at")
    @classmethod
    def utc_datetimes(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("catalyst timestamps must be timezone-aware UTC")
        return value


class CandidateSourceData(StrictFrozenModel):
    ticker: CanonicalTicker
    halted: bool = False
    borrow_status: BorrowStatus = BorrowStatus.UNKNOWN
    previous_regular_close: PositiveDecimal
    current_session_events: tuple[TradeLedgerEvent, ...]
    historical_premarket_sessions: tuple[PremarketSession, ...]
    daily_bars: tuple[DailyBar, ...]
    history_complete_since_listing: bool
    float_records: tuple[FloatRecord, ...]
    catalysts: tuple[CatalystRecord, ...]

    @model_validator(mode="after")
    def validate_order_and_identity(self) -> CandidateSourceData:
        dates = [bar.session_date for bar in self.daily_bars]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError("daily_bars must be unique and sorted ascending")
        for record in self.float_records:
            if record.ticker != self.ticker:
                raise ValueError("float record ticker mismatch")
        for catalyst in self.catalysts:
            if catalyst.ticker != self.ticker:
                raise ValueError("catalyst ticker mismatch")
        return self


class FeatureEngineConfig(StrictFrozenModel):
    engine_version: Literal["daily_features_v1"] = "daily_features_v1"
    module_versions: dict[str, str] = {
        "trade_ledger": "1.0.1",
        "gap": "1.0.1",
        "premarket_volume": "1.0.1",
        "rvol_time_matched": "1.0.1",
        "atr_wilder_14": "1.0.1",
        "premarket_vwap": "1.0.1",
        "volume_profile": "1.0.1",
        "daily_pivot_cluster_v1": "1.0.1",
        "float_join": "1.0.1",
        "news_join": "1.0.1",
        "prequalification": "1.0.1",
        "snapshot_builder": "1.0.1",
    }
    premarket_start_et: str = "04:00:00"
    snapshot_time_et: str = "09:23:00"
    rvol_lookback_sessions: int = Field(default=20, ge=1)
    atr_period: Literal[14] = 14
    min_daily_history: int = Field(default=30, ge=14)
    cluster_lookback_sessions: Literal[180] = 180
    pivot_left_width: Literal[5] = 5
    pivot_right_width: Literal[5] = 5
    cluster_tolerance_atr: Decimal = Decimal("0.5")
    cluster_recency_sessions: Literal[120] = 120
    distance_decimal_places: Literal[6] = 6
    blue_sky_sentinel: Decimal = Decimal("99.0")
    volume_bucket_minutes: Literal[5] = 5
    spiky_max_bucket_share: Decimal = Decimal("0.35")
    spiky_min_nonempty_coverage: Decimal = Decimal("0.60")
    gap_min_pct: Decimal = Decimal("4.0")
    premarket_volume_min: int = 500_000
    rvol_min: Decimal = Decimal("5.0")
    resistance_min_atr: Decimal = Decimal("1.0")
    max_evaluator_candidates: int = Field(default=20, ge=1, le=25)
    allow_single_source_float: bool = True

    @model_validator(mode="after")
    def coherent(self) -> FeatureEngineConfig:
        if self.spiky_max_bucket_share <= 0 or self.spiky_max_bucket_share > 1:
            raise ValueError("spiky_max_bucket_share must be in (0, 1]")
        if self.spiky_min_nonempty_coverage <= 0 or self.spiky_min_nonempty_coverage > 1:
            raise ValueError("spiky_min_nonempty_coverage must be in (0, 1]")
        return self


class FeatureContext(StrictFrozenModel):
    evaluation_timestamp: datetime
    payload_timestamp: datetime
    catalyst_freshness_threshold_hours: PositiveDecimal
    market_status: Literal["normal", "limit_up_down_active", "circuit_breaker_halt"]
    candidates: tuple[CandidateSourceData, ...]
    config: FeatureEngineConfig = FeatureEngineConfig()

    @field_validator("evaluation_timestamp", "payload_timestamp")
    @classmethod
    def utc_datetimes(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("snapshot timestamps must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def validate_context(self) -> FeatureContext:
        if self.evaluation_timestamp < self.payload_timestamp:
            raise ValueError("evaluation_timestamp cannot precede payload_timestamp")
        symbols = [candidate.ticker for candidate in self.candidates]
        if len(symbols) != len(set(symbols)):
            raise ValueError("candidate tickers must be unique")
        return self


class MaterializedTrade(StrictFrozenModel):
    trade_id: str
    event_timestamp: datetime
    price: PositiveDecimal
    size: int = Field(gt=0)
    ingest_seq: int = Field(gt=0)


class ResistanceAudit(StrictFrozenModel):
    algorithm_version: Literal["daily_pivot_cluster_v1"] = "daily_pivot_cluster_v1"
    available_completed_bars: int
    cluster_lookback_bars: int
    all_time_high_price: Decimal
    all_time_high_date: date
    confirmed_pivot_count: int
    synthetic_lookback_high_added: bool
    valid_cluster_count: int
    selected_resistance_source: Literal[
        "pivot_cluster", "all_time_high_fallback", "none_above_all_time_high"
    ]
    selected_zone_low: Decimal | None = None
    selected_zone_high: Decimal | None = None
    selected_zone_center: Decimal | None = None
    selected_touch_count: int | None = None
    selected_touch_dates: tuple[date, ...] = ()
    raw_distance_to_resistance_atr: str | None = None
    distance_to_resistance_atr: Decimal
    chart_structure: Literal["blue_sky", "clean_short_term", "moderate_room", "capped"]
    is_blue_sky_sentinel: bool


class CandidateFeatures(StrictFrozenModel):
    ticker: CanonicalTicker
    halted: bool
    current_price: PositiveDecimal
    premarket_low: PositiveDecimal
    gap_pct: Decimal
    premarket_volume: int = Field(ge=0)
    rvol_time_matched: NonNegativeDecimal
    atr_value: PositiveDecimal
    premarket_vwap: PositiveDecimal
    distance_from_vwap_atr: Decimal
    volume_profile: Literal["clean", "spiky"]
    float_shares: int = Field(gt=0)
    borrow_status: BorrowStatus
    resistance: ResistanceAudit
    catalyst: CatalystRecord
    catalyst_age_hours: NonNegativeDecimal
    feature_source_hash: Annotated[str, StringConstraints(pattern=HASH_PATTERN)]


class PrequalificationDecision(StrictFrozenModel):
    ticker: CanonicalTicker
    accepted: bool
    reason_codes: tuple[str, ...]
    feature_source_hash: str | None = None


class CapacityOmission(StrictFrozenModel):
    ticker: CanonicalTicker
    policy_version: Literal["prequal_rank_v1"] = "prequal_rank_v1"
    final_capacity_rank: int = Field(gt=0)
    reason_code: Literal["EVALUATOR_CAPACITY"] = "EVALUATOR_CAPACITY"


class FeatureSnapshot(StrictFrozenModel):
    snapshot_id: str
    context_hash: Annotated[str, StringConstraints(pattern=HASH_PATTERN)]
    audit_hash: Annotated[str, StringConstraints(pattern=HASH_PATTERN)]
    payload: DaybreakInput
    payload_hash: Annotated[str, StringConstraints(pattern=HASH_PATTERN)]
    feature_hash: Annotated[str, StringConstraints(pattern=HASH_PATTERN)]
    configuration_hash: Annotated[str, StringConstraints(pattern=HASH_PATTERN)]
    module_manifest: dict[str, str]
    prequalification: tuple[PrequalificationDecision, ...]
    capacity_omissions: tuple[CapacityOmission, ...]
    accepted_feature_records: tuple[CandidateFeatures, ...]

    @model_validator(mode="after")
    def terminal_consistency(self) -> FeatureSnapshot:
        payload_symbols = tuple(item.ticker for item in self.payload.tickers)
        feature_symbols = tuple(item.ticker for item in self.accepted_feature_records)
        if payload_symbols != feature_symbols:
            raise ValueError("payload and accepted feature record order must match")
        return self
