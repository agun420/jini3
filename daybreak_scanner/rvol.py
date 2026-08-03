"""Relative-volume baseline math, kept separate from I/O so it is trivially testable.

This is a coarse, full-day-average RVOL used only to narrow the scanner's
candidate list cheaply. It is deliberately not the feature engine's precise
`rvol_time_matched` module (which compares today's volume-so-far against the
historical average at the same time of day, using intraday history this
scanner stage does not fetch) — that module still runs, unmodified, once a
candidate reaches `daybreak_features.build_feature_snapshot`, and is the
authoritative check. A candidate that clears this coarse filter is not
guaranteed to also clear the feature engine's own stricter one.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from daybreak_features.models import DailyBar


def average_daily_volume(bars: Sequence[DailyBar], *, lookback_sessions: int) -> Decimal | None:
    """Mean volume over the most recent `lookback_sessions` sessions in `bars`.

    Returns None if there is no history to average at all. Fewer sessions than
    requested are still averaged over what is available, matching how the feature
    engine's own rvol_lookback_sessions works against partial history.
    """
    if not bars:
        return None
    recent = sorted(bars, key=lambda bar: bar.session_date)[-lookback_sessions:]
    total = sum((bar.volume for bar in recent), 0)
    return Decimal(total) / Decimal(len(recent))


def relative_volume(current_volume: int, average_volume: Decimal | None) -> Decimal | None:
    """Today's volume expressed as a multiple of its historical average.

    Returns None when there is no usable baseline (no history, or a zero-volume
    average) rather than raising or fabricating a ratio.
    """
    if average_volume is None or average_volume == 0:
        return None
    return Decimal(current_volume) / average_volume
