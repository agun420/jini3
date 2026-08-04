from datetime import UTC, date, datetime
from decimal import Decimal

from daybreak_scanner.models import SignalOutcome
from daybreak_scanner.scorecard import build_scorecard


def _outcome(outcome: str, return_pct: str, target_hit: str | None = None) -> SignalOutcome:
    return SignalOutcome(
        ticker="AAAA",
        trading_date=date(2026, 8, 3),
        resolved_at=datetime(2026, 8, 3, 15, 0, tzinfo=UTC),
        outcome=outcome,  # type: ignore[arg-type]
        target_hit=target_hit,  # type: ignore[arg-type]
        exit_price=Decimal("10"),
        return_pct=Decimal(return_pct),
    )


def test_scorecard_of_no_outcomes():
    scorecard = build_scorecard([])
    assert scorecard["total_signals"] == 0
    assert scorecard["win_rate_pct"] is None
    assert scorecard["target_1_hit_rate_pct"] is None
    assert scorecard["target_2_hit_rate_pct"] is None
    assert scorecard["average_return_pct"] is None


def test_scorecard_counts_and_win_rate():
    # Denominators chosen to divide evenly (decided=4) so the "two target
    # rates sum to the overall win rate" check below isn't just fighting
    # Decimal division's rounding rather than testing the real invariant.
    outcomes = [
        _outcome("win", "20", target_hit="target_1"),
        _outcome("win", "20", target_hit="target_1"),
        _outcome("win", "30", target_hit="target_2"),
        _outcome("loss", "-10"),
        _outcome("expired", "5"),
    ]
    scorecard = build_scorecard(outcomes)
    assert scorecard["total_signals"] == 5
    assert scorecard["wins"] == 3
    assert scorecard["losses"] == 1
    assert scorecard["expired"] == 1
    assert scorecard["wins_target_1"] == 2
    assert scorecard["wins_target_2"] == 1
    assert Decimal(scorecard["win_rate_pct"]) == Decimal("75")
    assert Decimal(scorecard["target_1_hit_rate_pct"]) == Decimal("50")
    assert Decimal(scorecard["target_2_hit_rate_pct"]) == Decimal("25")
    # The two target rates always sum to the overall win rate exactly.
    assert Decimal(scorecard["target_1_hit_rate_pct"]) + Decimal(
        scorecard["target_2_hit_rate_pct"]
    ) == Decimal(scorecard["win_rate_pct"])
    assert Decimal(scorecard["average_return_pct"]) == Decimal("13")


def test_scorecard_win_rate_is_none_with_no_decided_outcomes():
    scorecard = build_scorecard([_outcome("expired", "5")])
    assert scorecard["win_rate_pct"] is None
    assert scorecard["target_1_hit_rate_pct"] is None
    assert scorecard["target_2_hit_rate_pct"] is None
    assert Decimal(scorecard["average_return_pct"]) == Decimal("5")
