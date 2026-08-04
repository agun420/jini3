from datetime import UTC, date, datetime
from decimal import Decimal

from daybreak_scanner.models import MinuteBar, Signal
from daybreak_scanner.outcomes import expire_at_close, resolve_outcome


def _signal(entry="20.00", stop="18.00", target_1="24.00", target_2="26.00") -> Signal:
    return Signal(
        ticker="AAAA",
        trading_date=date(2026, 8, 3),
        generated_at=datetime(2026, 8, 3, 13, 35, tzinfo=UTC),
        entry_price=Decimal(entry),
        atr_value=Decimal("2.00"),
        stop_price=Decimal(stop),
        target_price_1=Decimal(target_1),
        target_price_2=Decimal(target_2),
        percent_change=Decimal("9.0"),
    )


def _bar(minute: int, *, high: str, low: str) -> MinuteBar:
    return MinuteBar(
        timestamp=datetime(2026, 8, 3, 13, 35 + minute, tzinfo=UTC),
        open=Decimal(high),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(high),
        volume=1000,
    )


def test_resolve_outcome_win_when_target_1_touched_first():
    signal = _signal()
    bars = [
        _bar(0, high="20.50", low="19.50"),
        _bar(1, high="24.50", low="20.00"),
    ]
    outcome = resolve_outcome(signal, bars)
    assert outcome is not None
    assert outcome.outcome == "win"
    assert outcome.target_hit == "target_1"
    assert outcome.exit_price == Decimal("24.00")
    assert outcome.resolved_at == bars[1].timestamp
    assert outcome.return_pct == Decimal("20")


def test_resolve_outcome_win_at_target_2_when_a_bar_runs_past_target_1():
    signal = _signal()
    bars = [
        _bar(0, high="20.50", low="19.50"),
        # High clears target_2 (26) directly -- necessarily crossed target_1
        # (24) first within this same bar, so this resolves as the better win.
        _bar(1, high="26.50", low="20.00"),
    ]
    outcome = resolve_outcome(signal, bars)
    assert outcome is not None
    assert outcome.outcome == "win"
    assert outcome.target_hit == "target_2"
    assert outcome.exit_price == Decimal("26.00")
    assert outcome.return_pct == Decimal("30")


def test_resolve_outcome_loss_when_stop_touched_first():
    signal = _signal()
    bars = [
        _bar(0, high="20.50", low="19.50"),
        _bar(1, high="20.00", low="17.50"),
    ]
    outcome = resolve_outcome(signal, bars)
    assert outcome is not None
    assert outcome.outcome == "loss"
    assert outcome.target_hit is None
    assert outcome.exit_price == Decimal("18.00")
    assert outcome.return_pct == Decimal("-10")


def test_resolve_outcome_treats_same_bar_touching_stop_and_target_1_as_a_loss():
    signal = _signal()
    bars = [_bar(0, high="25.00", low="17.00")]
    outcome = resolve_outcome(signal, bars)
    assert outcome is not None
    assert outcome.outcome == "loss"
    assert outcome.target_hit is None


def test_resolve_outcome_treats_same_bar_touching_stop_and_target_2_as_a_loss():
    signal = _signal()
    bars = [_bar(0, high="27.00", low="17.00")]
    outcome = resolve_outcome(signal, bars)
    assert outcome is not None
    assert outcome.outcome == "loss"
    assert outcome.target_hit is None


def test_resolve_outcome_uses_chronological_order_not_list_order():
    signal = _signal()
    later_hits_target = _bar(5, high="25.00", low="20.00")
    earlier_hits_stop = _bar(1, high="20.00", low="17.00")
    outcome = resolve_outcome(signal, [later_hits_target, earlier_hits_stop])
    assert outcome is not None
    assert outcome.outcome == "loss"
    assert outcome.resolved_at == earlier_hits_stop.timestamp


def test_resolve_outcome_is_none_when_neither_level_is_touched():
    signal = _signal()
    bars = [_bar(0, high="20.50", low="19.50")]
    assert resolve_outcome(signal, bars) is None


def test_expire_at_close_computes_return_relative_to_entry():
    signal = _signal()
    outcome = expire_at_close(
        signal,
        close_price=Decimal("21.00"),
        closed_at=datetime(2026, 8, 3, 20, 0, tzinfo=UTC),
    )
    assert outcome.outcome == "expired"
    assert outcome.target_hit is None
    assert outcome.exit_price == Decimal("21.00")
    assert outcome.return_pct == Decimal("5")
