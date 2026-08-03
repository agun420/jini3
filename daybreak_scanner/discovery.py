"""Deterministic candidate qualification.

Project Daybreak's evaluator only ever proposes long setups (`ApprovedSetup.side`
is the fixed literal `"long"`), so this module only ever looks at gainers, never
losers/shorts — a short-side "candidate" could never become a real setup.
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import ActiveStock, CandidateQualification, MarketMover, ScannerPolicy


def qualify_candidates(
    gainers: Sequence[MarketMover],
    actives: Sequence[ActiveStock],
    *,
    policy: ScannerPolicy | None = None,
) -> tuple[CandidateQualification, ...]:
    policy = policy or ScannerPolicy()
    volume_by_ticker = {item.ticker: item.volume for item in actives}
    results: list[CandidateQualification] = []
    for mover in gainers:
        reasons: list[str] = []
        volume = volume_by_ticker.get(mover.ticker)
        if mover.percent_change < policy.gap_min_pct:
            reasons.append(
                f"percent_change {mover.percent_change} below gap_min_pct {policy.gap_min_pct}"
            )
        if volume is None:
            reasons.append("ticker not present in the most-actives volume snapshot")
        elif volume < policy.premarket_volume_min:
            reasons.append(
                f"volume {volume} below premarket_volume_min {policy.premarket_volume_min}"
            )
        results.append(
            CandidateQualification(
                ticker=mover.ticker,
                percent_change=mover.percent_change,
                price=mover.price,
                volume=volume or 0,
                qualifies=not reasons,
                disqualification_reasons=tuple(reasons),
            )
        )
    return tuple(results)


def qualifying_tickers(
    candidates: Sequence[CandidateQualification], *, limit: int | None = None
) -> tuple[str, ...]:
    ranked = sorted(
        (item for item in candidates if item.qualifies),
        key=lambda item: item.percent_change,
        reverse=True,
    )
    if limit is not None:
        ranked = ranked[:limit]
    return tuple(item.ticker for item in ranked)
