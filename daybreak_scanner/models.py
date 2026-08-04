from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from daybreak_contracts.types import CanonicalTicker

Money = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class MarketMover(StrictFrozenModel):
    """One row from Alpaca's `/v1beta1/screener/stocks/movers` gainers list."""

    ticker: CanonicalTicker
    percent_change: Decimal
    change: Decimal
    price: Money


class ActiveStock(StrictFrozenModel):
    """One row from Alpaca's `/v1beta1/screener/stocks/most-actives` list."""

    ticker: CanonicalTicker
    volume: Annotated[int, Field(ge=0)]
    trade_count: Annotated[int, Field(ge=0)]


class ScannerPolicy(StrictFrozenModel):
    """Qualification thresholds. Defaults mirror daybreak_features.FeatureEngineConfig
    so a candidate that clears the scanner is already consistent with what the
    feature engine itself would require at snapshot time."""

    gap_min_pct: Decimal = Decimal("4.0")
    premarket_volume_min: Annotated[int, Field(ge=0)] = 500_000
    rvol_min: Decimal = Decimal("5.0")
    rvol_lookback_sessions: Annotated[int, Field(ge=1)] = 20
    max_candidates: Annotated[int, Field(ge=1, le=25)] = 20


class CandidateQualification(StrictFrozenModel):
    """One scanned ticker with its qualification verdict and, if disqualified, why.

    Every scanned mover is represented here (not just the ones that qualify) so a
    scan run is fully auditable: nothing is silently dropped without a recorded
    reason.
    """

    ticker: CanonicalTicker
    percent_change: Decimal
    price: Money
    volume: Annotated[int, Field(ge=0)]
    relative_volume: Decimal | None = None
    qualifies: bool
    disqualification_reasons: tuple[str, ...] = ()


class Signal(StrictFrozenModel):
    """A mechanical entry/stop/target for one qualifying candidate.

    Uses Project Daybreak's own fixed risk rule (stop = entry - 1x ATR,
    target_price_1 = entry + 2x ATR, from daybreak_risk's TradeParameters
    multiples) computed straight from real historical bars -- no float data,
    no LLM evaluator, no conviction score. This is a mechanical backtest/paper
    signal, not the audited system's own risk-sized, catalyst-scored setup.

    `target_price_2` (entry + 3x ATR) is a scanner-only stretch target, purely
    informational: it exists so `daybreak_scanner.outcomes`/`scorecard` can
    report how often a signal keeps running past its first target, not because
    daybreak_risk defines a second target -- it doesn't, its own fixed shape
    is exactly the 1x/2x mirrored above.
    """

    ticker: CanonicalTicker
    trading_date: date
    generated_at: datetime
    entry_price: Money
    atr_value: Money
    stop_price: Money
    target_price_1: Money
    target_price_2: Money
    percent_change: Decimal
    relative_volume: Decimal | None = None
    forecast_trend_pct: Decimal | None = None

    @field_validator("generated_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("generated_at must be timezone-aware UTC")
        return value


class MinuteBar(StrictFrozenModel):
    """One intraday minute bar, used only to resolve a Signal's outcome."""

    timestamp: datetime
    open: Money
    high: Money
    low: Money
    close: Money
    volume: Annotated[int, Field(ge=0)]

    @field_validator("timestamp")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("timestamp must be timezone-aware UTC")
        return value


class SignalOutcome(StrictFrozenModel):
    """The realized result of one Signal, from real subsequent price data.

    `target_hit` records which target level actually resolved a "win" --
    None for a loss or an expiry, since neither touched a target at all.
    """

    ticker: CanonicalTicker
    trading_date: date
    resolved_at: datetime
    outcome: Literal["win", "loss", "expired"]
    target_hit: Literal["target_1", "target_2"] | None = None
    exit_price: Money
    return_pct: Decimal

    @field_validator("resolved_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("resolved_at must be timezone-aware UTC")
        return value
