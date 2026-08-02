from decimal import Decimal

from daybreak_analytics.analytics import analyze_session

from .helpers import make_session, make_trade


def test_session_performance_is_deterministic():
    session = make_session()
    first = analyze_session(session)
    second = analyze_session(session)
    assert first == second
    assert first.analytics_hash == second.analytics_hash
    assert first.trade_count == 2
    assert first.winning_trade_count == 1
    assert first.losing_trade_count == 1


def test_trade_pnl_and_slippage_are_computed_from_raw_fields():
    trade = make_trade(session_id="SESSION00", pnl_sign=1)
    result = analyze_session(make_session(trades=(trade,)))
    assert result.gross_pnl == Decimal("9.5000000000")
    assert result.fees == Decimal("0.1000000000")
    assert result.net_pnl == Decimal("9.4000000000")
    assert result.total_entry_slippage == Decimal("0.5000000000")
    assert result.average_entry_slippage_bps == Decimal("50.0000000000")


def test_attribution_contains_source_chart_flag_and_exit_reason():
    trade = make_trade(session_id="SESSION00", risk_flags=("low_float",))
    result = analyze_session(make_session(trades=(trade,)))
    keys = {(item.dimension, item.key) for item in result.attributions}
    assert ("source_type", "primary") in keys
    assert ("chart_structure", "clean_short_term") in keys
    assert ("risk_flag", "low_float") in keys
    assert ("exit_reason", "target") in keys


def test_max_drawdown_uses_trade_order():
    losing = make_trade(session_id="SESSION00", trade_id="TRADE002", pnl_sign=-1)
    winning = make_trade(session_id="SESSION00", trade_id="TRADE003", pnl_sign=1, ticker="MSFT")
    result = analyze_session(make_session(trades=(losing, winning)))
    assert result.maximum_drawdown == Decimal("10.6000000000")


def test_empty_session_has_zero_metrics():
    result = analyze_session(make_session(trades=()))
    assert result.trade_count == 0
    assert result.win_rate == 0
    assert result.profit_factor is None
