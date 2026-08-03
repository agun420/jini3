from decimal import Decimal

from daybreak_scanner.discovery import qualify_candidates, qualifying_tickers
from daybreak_scanner.models import ActiveStock, MarketMover, ScannerPolicy


def _mover(ticker: str, percent_change: str, price: str = "10.00") -> MarketMover:
    return MarketMover(
        ticker=ticker,
        percent_change=Decimal(percent_change),
        change=Decimal("1.0"),
        price=Decimal(price),
    )


def _active(ticker: str, volume: int) -> ActiveStock:
    return ActiveStock(ticker=ticker, volume=volume, trade_count=volume // 10)


def test_candidate_qualifies_when_both_thresholds_clear():
    gainers = [_mover("AAAA", "9.0")]
    actives = [_active("AAAA", 600_000)]
    results = qualify_candidates(gainers, actives)
    assert len(results) == 1
    assert results[0].qualifies is True
    assert results[0].disqualification_reasons == ()


def test_candidate_disqualified_for_low_gap():
    gainers = [_mover("AAAA", "1.0")]
    actives = [_active("AAAA", 600_000)]
    results = qualify_candidates(gainers, actives)
    assert results[0].qualifies is False
    assert "gap_min_pct" in results[0].disqualification_reasons[0]


def test_candidate_disqualified_for_low_volume():
    gainers = [_mover("AAAA", "9.0")]
    actives = [_active("AAAA", 100)]
    results = qualify_candidates(gainers, actives)
    assert results[0].qualifies is False
    assert "premarket_volume_min" in results[0].disqualification_reasons[0]


def test_candidate_disqualified_when_absent_from_most_actives():
    gainers = [_mover("AAAA", "9.0")]
    results = qualify_candidates(gainers, actives=[])
    assert results[0].qualifies is False
    assert "most-actives" in results[0].disqualification_reasons[0]
    assert results[0].volume == 0


def test_custom_policy_thresholds_are_honored():
    gainers = [_mover("AAAA", "2.0")]
    actives = [_active("AAAA", 1_000)]
    policy = ScannerPolicy(gap_min_pct=Decimal("1.0"), premarket_volume_min=500)
    results = qualify_candidates(gainers, actives, policy=policy)
    assert results[0].qualifies is True


def test_qualifying_tickers_ranks_by_percent_change_descending_and_excludes_disqualified():
    gainers = [
        _mover("AAAA", "5.0"),
        _mover("BBBB", "20.0"),
        _mover("CCCC", "1.0"),  # disqualified: below default gap_min_pct
    ]
    actives = [_active("AAAA", 600_000), _active("BBBB", 600_000), _active("CCCC", 600_000)]
    results = qualify_candidates(gainers, actives)
    assert qualifying_tickers(results) == ("BBBB", "AAAA")


def test_qualifying_tickers_respects_limit():
    gainers = [_mover("AAAA", "20.0"), _mover("BBBB", "15.0"), _mover("CCCC", "10.0")]
    actives = [_active(t, 600_000) for t in ("AAAA", "BBBB", "CCCC")]
    results = qualify_candidates(gainers, actives)
    assert qualifying_tickers(results, limit=2) == ("AAAA", "BBBB")
