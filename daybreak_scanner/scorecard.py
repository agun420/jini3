"""Aggregates resolved SignalOutcomes into a running win-rate/return scorecard."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from .models import SignalOutcome


def build_scorecard(outcomes: Sequence[SignalOutcome]) -> dict[str, Any]:
    """win_rate_pct is wins / (wins + losses) -- an "expired" signal touched
    neither the stop nor the target, so it's excluded from the win-rate
    denominator regardless of whether its eventual close price happened to sit
    above or below entry. average_return_pct covers every signal, expired
    included, since that's the actual realized percentage regardless of which
    rule resolved it."""
    total = len(outcomes)
    wins = sum(1 for item in outcomes if item.outcome == "win")
    losses = sum(1 for item in outcomes if item.outcome == "loss")
    expired = sum(1 for item in outcomes if item.outcome == "expired")
    decided = wins + losses
    win_rate = (Decimal(wins) / Decimal(decided) * 100) if decided else None
    average_return_pct = (
        (sum((item.return_pct for item in outcomes), Decimal("0")) / Decimal(total))
        if total
        else None
    )
    return {
        "total_signals": total,
        "wins": wins,
        "losses": losses,
        "expired": expired,
        "win_rate_pct": None if win_rate is None else str(win_rate),
        "average_return_pct": None if average_return_pct is None else str(average_return_pct),
    }
