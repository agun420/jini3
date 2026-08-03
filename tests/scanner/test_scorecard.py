from datetime import UTC, date, datetime
from decimal import Decimal

from daybreak_scanner.models import SignalOutcome
from daybreak_scanner.scorecard import build_scorecard


def _outcome(outcome: str, return_pct: str) -> SignalOutcome:
    return SignalOutcome(
        ticker="AAAA",
        trading_date=date(2026, 8, 3),
        resolved_at=datetime(2026, 8, 3, 15, 0, tzinfo=UTC),
        outcome=outcome,  # type: ignore[arg-type]
        exit_price=Decimal("10"),
        return_pct=Decimal(return_pct),
    )


def test_scorecard_of_no_outcomes():
    scorecard = build_scorecard([])
    assert scorecard["total_signals"] == 0
    assert scorecard["win_rate_pct"] is None
    assert scorecard["average_return_pct"] is None


def test_scorecard_counts_and_win_rate():
    outcomes = [
        _outcome("win", "20"),
        _outcome("win", "20"),
        _outcome("loss", "-10"),
        _outcome("expired", "5"),
    ]
    scorecard = build_scorecard(outcomes)
    assert scorecard["total_signals"] == 4
    assert scorecard["wins"] == 2
    assert scorecard["losses"] == 1
    assert scorecard["expired"] == 1
    assert Decimal(scorecard["win_rate_pct"]) == Decimal(2) / Decimal(3) * 100
    assert Decimal(scorecard["average_return_pct"]) == Decimal("8.75")


def test_scorecard_win_rate_is_none_with_no_decided_outcomes():
    scorecard = build_scorecard([_outcome("expired", "5")])
    assert scorecard["win_rate_pct"] is None
    assert Decimal(scorecard["average_return_pct"]) == Decimal("5")
