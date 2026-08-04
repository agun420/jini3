"""Aggregates resolved SignalOutcomes into a running win-rate/return scorecard."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from .models import SignalOutcome


def build_scorecard(outcomes: Sequence[SignalOutcome]) -> dict[str, Any]:
    """win_rate_pct is wins / (wins + losses) -- an "expired" signal touched
    neither the stop nor a target, so it's excluded from the win-rate
    denominator regardless of whether its eventual close price happened to sit
    above or below entry. average_return_pct covers every signal, expired
    included, since that's the actual realized percentage regardless of which
    rule resolved it.

    wins_target_1/wins_target_2 split that same win count by which level
    actually resolved it (see daybreak_scanner.outcomes.resolve_outcome);
    target_1_hit_rate_pct/target_2_hit_rate_pct use the identical `decided`
    denominator as win_rate_pct, so the two rates always sum to it exactly --
    this is "of every signal that got a real answer, how far did it run."
    """
    total = len(outcomes)
    wins = sum(1 for item in outcomes if item.outcome == "win")
    losses = sum(1 for item in outcomes if item.outcome == "loss")
    expired = sum(1 for item in outcomes if item.outcome == "expired")
    wins_target_1 = sum(1 for item in outcomes if item.target_hit == "target_1")
    wins_target_2 = sum(1 for item in outcomes if item.target_hit == "target_2")
    decided = wins + losses
    win_rate = (Decimal(wins) / Decimal(decided) * 100) if decided else None
    target_1_hit_rate = (Decimal(wins_target_1) / Decimal(decided) * 100) if decided else None
    target_2_hit_rate = (Decimal(wins_target_2) / Decimal(decided) * 100) if decided else None
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
        "wins_target_1": wins_target_1,
        "wins_target_2": wins_target_2,
        "win_rate_pct": None if win_rate is None else str(win_rate),
        "target_1_hit_rate_pct": None if target_1_hit_rate is None else str(target_1_hit_rate),
        "target_2_hit_rate_pct": None if target_2_hit_rate is None else str(target_2_hit_rate),
        "average_return_pct": None if average_return_pct is None else str(average_return_pct),
    }
