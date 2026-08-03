from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

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
