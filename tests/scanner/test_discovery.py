from decimal import Decimal

from daybreak_scanner.discovery import qualify_candidates, qualifying_tickers
from daybreak_scanner.models import MarketMover, ScannerPolicy


def _mover(ticker: str, percent_change: str, price: str = "10.00") -> MarketMover:
    return MarketMover(
        ticker=ticker,
        percent_change=Decimal(percent_change),
        change=Decimal("1.0"),
        price=Decimal(price),
    )


def test_candidate_qualifies_when_both_thresholds_clear():
    gainers = [_mover("AAAA", "9.0")]
    results = qualify_candidates(gainers, {"AAAA": 600_000})
    assert len(results) == 1
    assert results[0].qualifies is True
    assert results[0].disqualification_reasons == ()


def test_candidate_disqualified_for_low_gap():
    gainers = [_mover("AAAA", "1.0")]
    results = qualify_candidates(gainers, {"AAAA": 600_000})
    assert results[0].qualifies is False
    assert "gap_min_pct" in results[0].disqualification_reasons[0]


def test_candidate_disqualified_for_low_volume():
    gainers = [_mover("AAAA", "9.0")]
    results = qualify_candidates(gainers, {"AAAA": 100})
    assert results[0].qualifies is False
    assert "premarket_volume_min" in results[0].disqualification_reasons[0]


def test_candidate_disqualified_when_absent_from_volume_snapshot():
    gainers = [_mover("AAAA", "9.0")]
    results = qualify_candidates(gainers, volume_by_ticker={})
    assert results[0].qualifies is False
    assert "current-session volume" in results[0].disqualification_reasons[0]
    assert results[0].volume == 0


def test_custom_policy_thresholds_are_honored():
    gainers = [_mover("AAAA", "2.0")]
    policy = ScannerPolicy(gap_min_pct=Decimal("1.0"), premarket_volume_min=500)
    results = qualify_candidates(gainers, {"AAAA": 1_000}, policy=policy)
    assert results[0].qualifies is True


def test_qualifying_tickers_ranks_by_percent_change_descending_and_excludes_disqualified():
    gainers = [
        _mover("AAAA", "5.0"),
        _mover("BBBB", "20.0"),
        _mover("CCCC", "1.0"),  # disqualified: below default gap_min_pct
    ]
    volume_by_ticker = {"AAAA": 600_000, "BBBB": 600_000, "CCCC": 600_000}
    results = qualify_candidates(gainers, volume_by_ticker)
    assert qualifying_tickers(results) == ("BBBB", "AAAA")


def test_qualifying_tickers_respects_limit():
    gainers = [_mover("AAAA", "20.0"), _mover("BBBB", "15.0"), _mover("CCCC", "10.0")]
    volume_by_ticker = {t: 600_000 for t in ("AAAA", "BBBB", "CCCC")}
    results = qualify_candidates(gainers, volume_by_ticker)
    assert qualifying_tickers(results, limit=2) == ("AAAA", "BBBB")


def test_rvol_check_is_skipped_without_a_baseline():
    gainers = [_mover("AAAA", "9.0")]
    results = qualify_candidates(gainers, {"AAAA": 600_000})
    assert results[0].qualifies is True
    assert results[0].relative_volume is None


def test_rvol_check_disqualifies_below_threshold_when_baseline_is_provided():
    gainers = [_mover("AAAA", "9.0")]
    results = qualify_candidates(
        gainers, {"AAAA": 600_000}, average_volume_by_ticker={"AAAA": Decimal("500000")}
    )
    assert results[0].qualifies is False
    assert results[0].relative_volume == Decimal("1.2")
    assert "rvol_min" in results[0].disqualification_reasons[-1]


def test_rvol_check_passes_above_threshold_when_baseline_is_provided():
    gainers = [_mover("AAAA", "9.0")]
    results = qualify_candidates(
        gainers, {"AAAA": 600_000}, average_volume_by_ticker={"AAAA": Decimal("100000")}
    )
    assert results[0].qualifies is True
    assert results[0].relative_volume == Decimal("6")
