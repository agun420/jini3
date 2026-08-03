"""Dynamic candidate discovery: scans Alpaca market movers/most-actives and
applies Project Daybreak's feature-engine qualifier thresholds to produce a
watchlist, without any fixed hand-typed ticker list."""

from .alpaca_data import AlpacaMarketDataClient
from .discovery import qualify_candidates, qualifying_tickers
from .models import ActiveStock, CandidateQualification, MarketMover, ScannerPolicy

__all__ = [
    "ActiveStock",
    "AlpacaMarketDataClient",
    "CandidateQualification",
    "MarketMover",
    "ScannerPolicy",
    "qualify_candidates",
    "qualifying_tickers",
]
