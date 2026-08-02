from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal, TypedDict

from .canonical import canonical_sha256
from .models import AttributionBucket, SessionEvidence, SessionPerformance, TradeOutcome

Q = Decimal("0.0000000001")
ZERO = Decimal("0")
TEN_THOUSAND = Decimal("10000")

AttributionDimension = Literal["source_type", "chart_structure", "risk_flag", "exit_reason"]


class TradeSummary(TypedDict):
    trade_count: int
    wins: int
    losses: int
    breakeven: int
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    win_rate: Decimal
    profit_factor: Decimal | None
    expectancy: Decimal
    average_win: Decimal
    average_loss: Decimal
    average_r: Decimal
    maximum_drawdown: Decimal
    total_slippage: Decimal
    average_slippage_bps: Decimal


def _q(value: Decimal) -> Decimal:
    return value.quantize(Q, rounding=ROUND_HALF_EVEN)


def _trade_metrics(trade: TradeOutcome) -> dict[str, Decimal]:
    gross = (trade.average_exit_price - trade.average_entry_price) * trade.quantity
    net = gross - trade.fees
    risk = (trade.planned_entry_price - trade.planned_stop_price) * trade.quantity
    r_multiple = net / risk if risk > 0 else ZERO
    entry_slippage = (trade.average_entry_price - trade.planned_entry_price) * trade.quantity
    entry_slippage_bps = (
        (trade.average_entry_price - trade.planned_entry_price)
        / trade.planned_entry_price
        * TEN_THOUSAND
    )
    return {
        "gross": _q(gross),
        "net": _q(net),
        "risk": _q(risk),
        "r": _q(r_multiple),
        "entry_slippage": _q(entry_slippage),
        "entry_slippage_bps": _q(entry_slippage_bps),
    }


def _summary(trades: Iterable[TradeOutcome]) -> TradeSummary:
    trade_list = list(trades)
    metrics = [_trade_metrics(item) for item in trade_list]
    net_values = [item["net"] for item in metrics]
    gross_pnl = _q(sum((item["gross"] for item in metrics), ZERO))
    fees = _q(sum((item.fees for item in trade_list), ZERO))
    net_pnl = _q(sum(net_values, ZERO))
    wins = [value for value in net_values if value > 0]
    losses = [value for value in net_values if value < 0]
    count = len(trade_list)
    win_rate = _q(Decimal(len(wins)) / Decimal(count)) if count else ZERO
    gross_profit = sum(wins, ZERO)
    gross_loss = abs(sum(losses, ZERO))
    profit_factor = _q(gross_profit / gross_loss) if gross_loss > 0 else None
    expectancy = _q(net_pnl / Decimal(count)) if count else ZERO
    average_win = _q(gross_profit / Decimal(len(wins))) if wins else ZERO
    average_loss = _q(sum(losses, ZERO) / Decimal(len(losses))) if losses else ZERO
    average_r = _q(sum((item["r"] for item in metrics), ZERO) / Decimal(count)) if count else ZERO
    total_slippage = _q(sum((item["entry_slippage"] for item in metrics), ZERO))
    average_slippage_bps = (
        _q(sum((item["entry_slippage_bps"] for item in metrics), ZERO) / Decimal(count))
        if count
        else ZERO
    )
    cumulative = ZERO
    peak = ZERO
    max_drawdown = ZERO
    for value in net_values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return {
        "trade_count": count,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": count - len(wins) - len(losses),
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "average_win": average_win,
        "average_loss": average_loss,
        "average_r": average_r,
        "maximum_drawdown": _q(max_drawdown),
        "total_slippage": total_slippage,
        "average_slippage_bps": average_slippage_bps,
    }


def _attributions(trades: tuple[TradeOutcome, ...]) -> tuple[AttributionBucket, ...]:
    groups: dict[tuple[AttributionDimension, str], list[TradeOutcome]] = defaultdict(list)
    for trade in trades:
        groups[("source_type", trade.source_type)].append(trade)
        groups[("chart_structure", trade.chart_structure)].append(trade)
        groups[("exit_reason", trade.exit_reason.value)].append(trade)
        for flag in trade.risk_flags:
            groups[("risk_flag", flag)].append(trade)
    buckets: list[AttributionBucket] = []
    for (dimension, key), group in sorted(groups.items()):
        summary = _summary(group)
        buckets.append(
            AttributionBucket(
                dimension=dimension,
                key=key,
                trade_count=summary["trade_count"],
                net_pnl=summary["net_pnl"],
                win_rate=summary["win_rate"],
                expectancy=summary["expectancy"],
                average_r_multiple=summary["average_r"],
            )
        )
    return tuple(buckets)


def analyze_session(evidence: SessionEvidence) -> SessionPerformance:
    summary = _summary(evidence.trades)
    evidence_hash = canonical_sha256(evidence)
    body = {
        "session_id": evidence.session_id,
        "trading_date": evidence.trading_date,
        "trade_count": summary["trade_count"],
        "winning_trade_count": summary["wins"],
        "losing_trade_count": summary["losses"],
        "breakeven_trade_count": summary["breakeven"],
        "gross_pnl": summary["gross_pnl"],
        "fees": summary["fees"],
        "net_pnl": summary["net_pnl"],
        "win_rate": summary["win_rate"],
        "profit_factor": summary["profit_factor"],
        "expectancy": summary["expectancy"],
        "average_win": summary["average_win"],
        "average_loss": summary["average_loss"],
        "average_r_multiple": summary["average_r"],
        "maximum_drawdown": summary["maximum_drawdown"],
        "total_entry_slippage": summary["total_slippage"],
        "average_entry_slippage_bps": summary["average_slippage_bps"],
        "attributions": _attributions(evidence.trades),
        "evidence_hash": evidence_hash,
    }
    analytics_hash = canonical_sha256(body)
    return SessionPerformance.model_validate(
        {
            **body,
            "analytics_id": f"AN-{analytics_hash[:20]}",
            "analytics_hash": analytics_hash,
        }
    )


def summarize_sessions(
    values: Iterable[SessionPerformance],
    trades: Iterable[TradeOutcome] | None = None,
) -> dict[str, Decimal | int | None]:
    sessions = list(values)
    if trades is not None:
        aggregate = _summary(trades)
        return {
            "session_count": len(sessions),
            "trade_count": aggregate["trade_count"],
            "gross_pnl": aggregate["gross_pnl"],
            "fees": aggregate["fees"],
            "net_pnl": aggregate["net_pnl"],
            "win_rate": aggregate["win_rate"],
            "profit_factor": aggregate["profit_factor"],
            "expectancy": aggregate["expectancy"],
            "maximum_drawdown": aggregate["maximum_drawdown"],
            "average_r_multiple": aggregate["average_r"],
        }
    trade_count = sum(item.trade_count for item in sessions)
    gross_pnl = _q(sum((item.gross_pnl for item in sessions), ZERO))
    fees = _q(sum((item.fees for item in sessions), ZERO))
    net_pnl = _q(sum((item.net_pnl for item in sessions), ZERO))
    winning = sum(item.winning_trade_count for item in sessions)
    win_rate = _q(Decimal(winning) / Decimal(trade_count)) if trade_count else ZERO
    expectancy = _q(net_pnl / Decimal(trade_count)) if trade_count else ZERO
    weighted_r = sum((item.average_r_multiple * item.trade_count for item in sessions), ZERO)
    average_r = _q(weighted_r / Decimal(trade_count)) if trade_count else ZERO
    cumulative = ZERO
    peak = ZERO
    max_drawdown = ZERO
    for item in sessions:
        cumulative += item.net_pnl
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return {
        "session_count": len(sessions),
        "trade_count": trade_count,
        "gross_pnl": gross_pnl,
        "fees": fees,
        "net_pnl": net_pnl,
        "win_rate": win_rate,
        "profit_factor": None,
        "expectancy": expectancy,
        "maximum_drawdown": _q(max_drawdown),
        "average_r_multiple": average_r,
    }
