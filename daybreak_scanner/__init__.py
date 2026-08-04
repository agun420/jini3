"""Dynamic candidate discovery: scans Alpaca market movers/most-actives and
applies Project Daybreak's feature-engine qualifier thresholds to produce a
watchlist, without any fixed hand-typed ticker list."""

from .alpaca_data import AlpacaMarketDataClient
from .discovery import qualify_candidates, qualifying_tickers
from .forecast import (
    Forecaster,
    ForecastError,
    TimesFMForecaster,
    daily_closes_by_ticker,
    trend_pct,
)
from .models import ActiveStock, CandidateQualification, MarketMover, ScannerPolicy
from .rvol import average_daily_volume, relative_volume

__all__ = [
    "ActiveStock",
    "AlpacaMarketDataClient",
    "CandidateQualification",
    "Forecaster",
    "ForecastError",
    "MarketMover",
    "ScannerPolicy",
    "TimesFMForecaster",
    "average_daily_volume",
    "daily_closes_by_ticker",
    "qualify_candidates",
    "qualifying_tickers",
    "relative_volume",
    "trend_pct",
]
