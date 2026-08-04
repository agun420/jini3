from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from daybreak_features.models import DailyBar
from daybreak_scanner.models import CandidateQualification
from daybreak_scanner.signals import build_signals


def _bars(high: str, low: str, close: str, count: int = 15) -> tuple[DailyBar, ...]:
    return tuple(
        DailyBar(
            session_date=date(2026, 1, 1) + timedelta(days=i),
            open=Decimal(close),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=100,
        )
        for i in range(count)
    )


def _candidate(
    ticker: str, *, qualifies: bool = True, price: str = "20.00"
) -> CandidateQualification:
    return CandidateQualification(
        ticker=ticker,
        percent_change=Decimal("9.0"),
        price=Decimal(price),
        volume=600_000,
        relative_volume=Decimal("6.0"),
        qualifies=qualifies,
    )


def test_build_signals_computes_atr_based_stop_and_target():
    candidates = [_candidate("AAAA")]
    bars_by_ticker = {"AAAA": _bars("11", "9", "10")}
    signals = build_signals(
        candidates,
        bars_by_ticker,
        trading_date=date(2026, 8, 3),
        generated_at=datetime(2026, 8, 3, 13, 35, tzinfo=UTC),
    )
    assert len(signals) == 1
    signal = signals[0]
    assert signal.ticker == "AAAA"
    assert signal.entry_price == Decimal("20.00")
    assert signal.atr_value == Decimal("2")
    assert signal.stop_price == Decimal("18.00")
    assert signal.target_price == Decimal("24.00")
    assert signal.trading_date == date(2026, 8, 3)


def test_build_signals_skips_disqualified_candidates():
    candidates = [_candidate("AAAA", qualifies=False)]
    bars_by_ticker = {"AAAA": _bars("11", "9", "10")}
    signals = build_signals(candidates, bars_by_ticker, trading_date=date(2026, 8, 3))
    assert signals == ()


def test_build_signals_skips_candidates_with_insufficient_bar_history():
    candidates = [_candidate("AAAA")]
    bars_by_ticker = {"AAAA": _bars("11", "9", "10", count=5)}
    signals = build_signals(candidates, bars_by_ticker, trading_date=date(2026, 8, 3))
    assert signals == ()


def test_build_signals_skips_candidates_with_no_bars_at_all():
    candidates = [_candidate("AAAA")]
    signals = build_signals(candidates, {}, trading_date=date(2026, 8, 3))
    assert signals == ()


def test_build_signals_attaches_forecast_trend_when_supplied():
    candidates = [_candidate("AAAA"), _candidate("BBBB")]
    bars_by_ticker = {"AAAA": _bars("11", "9", "10"), "BBBB": _bars("11", "9", "10")}
    signals = build_signals(
        candidates,
        bars_by_ticker,
        trading_date=date(2026, 8, 3),
        forecast_trend_by_ticker={"AAAA": Decimal("3.5")},
    )
    by_ticker = {item.ticker: item for item in signals}
    assert by_ticker["AAAA"].forecast_trend_pct == Decimal("3.5")
    assert by_ticker["BBBB"].forecast_trend_pct is None


def test_build_signals_forecast_trend_defaults_to_none_without_it():
    candidates = [_candidate("AAAA")]
    bars_by_ticker = {"AAAA": _bars("11", "9", "10")}
    signals = build_signals(candidates, bars_by_ticker, trading_date=date(2026, 8, 3))
    assert signals[0].forecast_trend_pct is None
