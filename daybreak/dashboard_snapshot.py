"""Build a dashboard.schema.json-shaped snapshot from real Daybreak system state.

This module is a pure mapping layer: it takes already-fetched domain objects
(read from the various package repositories and the live broker) and produces
a plain dict matching dashboard/data/dashboard.schema.json. It performs no I/O
itself — the `daybreak dashboard-snapshot` CLI command is responsible for
fetching sources and writing the result to a file.

Coverage is intentionally honest rather than complete: several packages in
this codebase are append-only event stores with no "current state" read path
(see docs/audit/Project_Daybreak_v1.0.2_Independent_Audit_2026-08-02.md).
Where no real source exists for a schema field, this module emits null/empty
rather than fabricating a plausible-looking value. In particular:

- `services[]` collapses to at most one aggregate entry from the operations
  observability snapshot, because no persisted data distinguishes per-layer
  health for the nine service layers.
- `performance.equity_curve` and `performance.daily` are always empty: no
  repository exposes a historical time series, only point-in-time session
  performance.
- `release.branch_coverage_pct`, `ruff_errors`, `mypy_errors`,
  `dependency_vulnerabilities`, and `invariant_count` are always null: none
  of these are persisted anywhere in the release evidence chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from daybreak_analytics.models import PaperAcceptanceLedger, SessionPerformance
from daybreak_evaluator.models import EvaluationRunResult
from daybreak_execution.enums import BrokerOrderStatus
from daybreak_execution.models import BrokerOrderSnapshot, BrokerPositionSnapshot
from daybreak_operations.models import ObservabilitySnapshot
from daybreak_orchestration.models import AlertRecord, KillSwitchState, PhaseRecord
from daybreak_release.models import BuildAttestation, ProductionCandidateReport
from daybreak_risk.models import RiskDecision

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class DashboardSnapshotSources:
    """Everything the exporter was able to fetch for one session, already typed.

    Every field beyond session_id/trading_date is optional: callers pass
    whatever repositories/credentials they have configured, and the mapper
    below degrades gracefully when a source is unavailable.
    """

    session_id: str
    trading_date: date
    kill_switch: KillSwitchState | None = None
    phases: tuple[PhaseRecord, ...] = ()
    alerts: tuple[AlertRecord, ...] = ()
    decisions: tuple[RiskDecision, ...] = ()
    run_result: EvaluationRunResult | None = None
    session_performance: SessionPerformance | None = None
    paper_ledger: PaperAcceptanceLedger | None = None
    observability: ObservabilitySnapshot | None = None
    candidate_report: ProductionCandidateReport | None = None
    build_attestation: BuildAttestation | None = None
    positions: tuple[BrokerPositionSnapshot, ...] = ()
    orders: tuple[BrokerOrderSnapshot, ...] = ()
    account: dict[str, Any] = field(default_factory=dict)
    market_status_normal: bool | None = None


def build_dashboard_snapshot(
    sources: DashboardSnapshotSources, *, generated_at: datetime | None = None
) -> dict[str, Any]:
    """Map fetched sources into a dashboard.schema.json-conformant dict.

    `data_mode` is always "local": this function only ever backs the
    dashboard-snapshot CLI command, whose whole purpose is a file meant to be
    loaded via the dashboard's private "Load private snapshot" control, never
    published to dashboard/data/dashboard.json.
    """
    now = (generated_at or datetime.now(UTC)).astimezone(UTC)
    decisions_by_ticker = {item.ticker: item for item in sources.decisions}
    orders_by_ticker: dict[str, list[BrokerOrderSnapshot]] = {}
    for order in sources.orders:
        orders_by_ticker.setdefault(order.symbol, []).append(order)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now) or now.isoformat(),
        "data_mode": "local",
        "environment": "paper",
        "public_safe": False,
        "system": _build_system(sources, now),
        "safety": _build_safety(sources),
        "account": _build_account(sources),
        "session": _build_session(sources),
        "performance": _build_performance(sources),
        "signals": _build_signals(sources, decisions_by_ticker, orders_by_ticker),
        "positions": _build_positions(sources, decisions_by_ticker),
        "orders": [_map_order(item) for item in sources.orders],
        "services": _build_services(sources),
        "qualification": _build_qualification(sources),
        "release": _build_release(sources),
        "alerts": [_map_alert(item) for item in sources.alerts],
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _num(value: Decimal | float | int | None) -> float | None:
    return None if value is None else float(value)


def _latest_phase(sources: DashboardSnapshotSources) -> PhaseRecord | None:
    return sources.phases[-1] if sources.phases else None


def _build_system(sources: DashboardSnapshotSources, now: datetime) -> dict[str, Any]:
    phase = _latest_phase(sources)
    market_status = (
        "unknown"
        if sources.market_status_normal is None
        else ("normal" if sources.market_status_normal else "not_normal")
    )
    return {
        "name": "Project Daybreak",
        "version": sources.candidate_report.release_version
        if sources.candidate_report
        else "unknown",
        "specification_version": sources.candidate_report.specification_version
        if sources.candidate_report
        else "unknown",
        "phase": phase.phase.value if phase else "unknown",
        "market_status": market_status,
        "market_detail": "",
        "timezone": "America/New_York",
        "freshness_threshold_seconds": 90,
    }


def _build_safety(sources: DashboardSnapshotSources) -> dict[str, Any]:
    return {
        "paper_only": True,
        "live_capital_eligible": False,
        "kill_switch_active": bool(sources.kill_switch and sources.kill_switch.active),
        "entries_enabled": False,
        "all_positions_flat": len(sources.positions) == 0,
    }


def _build_account(sources: DashboardSnapshotSources) -> dict[str, Any]:
    account = sources.account
    open_risk = sum(
        (item.reserved_modeled_risk for item in sources.decisions if item.reserved_modeled_risk),
        Decimal("0"),
    )
    equity = _num(account.get("equity"))
    last_equity = _num(account.get("last_equity"))
    return {
        "currency": "USD",
        "equity": equity,
        "session_start_equity": last_equity,
        "buying_power": _num(account.get("buying_power")),
        "cash": _num(account.get("cash")),
        "gross_exposure": _num(account.get("long_market_value")),
        "gross_exposure_limit": None,
        "open_risk": float(open_risk) if sources.decisions else None,
        "open_risk_limit": None,
        "daily_pnl": (equity - last_equity)
        if equity is not None and last_equity is not None
        else None,
        "daily_pnl_pct": None,
        "realized_pnl": _num(sources.session_performance.net_pnl)
        if sources.session_performance
        else None,
        "unrealized_pnl": None,
        "hard_daily_loss_limit": None,
    }


def _build_session(sources: DashboardSnapshotSources) -> dict[str, Any]:
    phase = _latest_phase(sources)
    output = sources.run_result.output if sources.run_result else None
    filled = sum(1 for item in sources.orders if item.status == BrokerOrderStatus.FILLED)
    return {
        "session_id": sources.session_id,
        "trading_date": sources.trading_date.isoformat(),
        "state": phase.phase.value if phase else "unknown",
        "state_detail": phase.status.value if phase else "",
        "started_at": _iso(sources.phases[0].started_at) if sources.phases else None,
        "approved_setup_count": len(output.approved_setups) if output else 0,
        "qualified_setup_count": len(output.qualified_not_selected) if output else 0,
        "excluded_ticker_count": len(output.excluded_tickers) if output else 0,
        "orders_submitted": len(sources.orders),
        "orders_filled": filled,
    }


def _build_performance(sources: DashboardSnapshotSources) -> dict[str, Any]:
    perf = sources.session_performance
    summary: dict[str, Any] = {}
    attributions: list[dict[str, Any]] = []
    if perf is not None:
        summary = {
            "session_count": 1,
            "trade_count": perf.trade_count,
            "winning_trade_count": perf.winning_trade_count,
            "losing_trade_count": perf.losing_trade_count,
            "breakeven_trade_count": perf.breakeven_trade_count,
            "gross_pnl": _num(perf.gross_pnl),
            "fees": _num(perf.fees),
            "net_pnl": _num(perf.net_pnl),
            "win_rate": _num(perf.win_rate),
            "profit_factor": _num(perf.profit_factor),
            "expectancy": _num(perf.expectancy),
            "maximum_drawdown": _num(perf.maximum_drawdown),
            "average_r_multiple": _num(perf.average_r_multiple),
            "average_entry_slippage_bps": _num(perf.average_entry_slippage_bps),
        }
        attributions = [
            {
                "dimension": item.dimension,
                "key": item.key,
                "trade_count": item.trade_count,
                "net_pnl": _num(item.net_pnl),
                "win_rate": _num(item.win_rate),
                "average_r_multiple": _num(item.average_r_multiple),
            }
            for item in perf.attributions
        ]
    return {
        "summary": summary,
        "equity_curve": [],
        "daily": [],
        "attributions": attributions,
        "trades": [],
    }


def _build_signals(
    sources: DashboardSnapshotSources,
    decisions_by_ticker: dict[str, RiskDecision],
    orders_by_ticker: dict[str, list[BrokerOrderSnapshot]],
) -> list[dict[str, Any]]:
    output = sources.run_result.output if sources.run_result else None
    if output is None:
        return []
    signals: list[dict[str, Any]] = []
    for index, setup in enumerate(output.approved_setups):
        decision = decisions_by_ticker.get(setup.ticker)
        rank = decision.final_rank if decision else index + 1
        matching_orders = orders_by_ticker.get(setup.ticker, ())
        execution_status = matching_orders[-1].status.value if matching_orders else "not_submitted"
        signals.append(
            {
                "ticker": setup.ticker,
                "rank": rank,
                "status": "approved",
                "execution_status": execution_status,
                "conviction_score": setup.conviction_score,
                "technical_grade": setup.score_breakdown.technical_grade,
                "catalyst_source": setup.catalyst_source,
                "catalyst_age_hours": setup.catalyst_age_hours,
                "source_type": setup.source_type,
                "corroborated": setup.corroborated,
                "catalyst": "",
                "thesis": setup.master_thesis,
                "entry_price": _num(decision.planned_entry_limit) if decision else None,
                "stop_price": _num(decision.stop_price) if decision else None,
                "target_price": _num(decision.target_price) if decision else None,
                "quantity": decision.final_quantity if decision else None,
                "modeled_risk": _num(decision.reserved_modeled_risk) if decision else None,
                "risk_flags": list(setup.risk_flags),
            }
        )
    for candidate in output.qualified_not_selected:
        signals.append(
            {
                "ticker": candidate.ticker,
                "rank": candidate.final_rank,
                "status": "qualified",
                "conviction_score": candidate.conviction_score,
                "technical_grade": candidate.score_breakdown.technical_grade,
                "catalyst_source": candidate.catalyst_source,
                "catalyst_age_hours": candidate.catalyst_age_hours,
                "source_type": candidate.source_type,
                "corroborated": candidate.corroborated,
                "risk_flags": list(candidate.risk_flags),
                "rejection_reason": candidate.non_selection_reason_code,
            }
        )
    for excluded in output.excluded_tickers:
        signals.append(
            {
                "ticker": excluded.ticker,
                "rank": 0,
                "status": "excluded",
                "conviction_score": 0,
                "technical_grade": excluded.evaluation_snapshot.technical_grade,
                "risk_flags": list(excluded.evaluation_snapshot.risk_flags),
                "rejection_reason": excluded.primary_reason.reason,
            }
        )
    return signals


def _build_positions(
    sources: DashboardSnapshotSources, decisions_by_ticker: dict[str, RiskDecision]
) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for item in sources.positions:
        decision = decisions_by_ticker.get(item.symbol)
        positions.append(
            {
                "ticker": item.symbol,
                "side": "long",
                "quantity": _num(item.quantity) or 0,
                "average_entry_price": _num(item.average_entry_price),
                "stop_price": _num(decision.stop_price) if decision else None,
                "target_price": _num(decision.target_price) if decision else None,
                "updated_at": _iso(item.observed_at),
            }
        )
    return positions


def _map_order(item: BrokerOrderSnapshot) -> dict[str, Any]:
    return {
        "submitted_at": _iso(item.submitted_at),
        "ticker": item.symbol,
        "side": item.side.value,
        "type": item.order_type.value,
        "order_class": item.order_class,
        "quantity": _num(item.quantity) or 0,
        "filled_quantity": _num(item.filled_quantity) or 0,
        "price": _num(item.limit_price) if item.limit_price is not None else _num(item.stop_price),
        "status": item.status.value,
        "client_order_id": item.client_order_id,
    }


def _build_services(sources: DashboardSnapshotSources) -> list[dict[str, Any]]:
    observability = sources.observability
    if observability is None:
        return []
    return [
        {
            "name": "System (aggregate)",
            "status": "healthy" if observability.healthy else "critical",
            "detail": "; ".join(observability.failures) if observability.failures else "",
            "updated_at": _iso(observability.observed_at),
        }
    ]


def _build_qualification(sources: DashboardSnapshotSources) -> dict[str, Any]:
    ledger = sources.paper_ledger
    if ledger is None:
        return {"status": "unavailable", "items": [], "blockers": []}
    policy = ledger.policy
    items = [
        {
            "key": "sessions",
            "label": "Paper sessions",
            "current": ledger.session_count,
            "target": policy.minimum_sessions,
            "status": "passed" if ledger.session_count >= policy.minimum_sessions else "incomplete",
        },
        {
            "key": "clean_sessions",
            "label": "Clean sessions",
            "current": ledger.clean_session_count,
            "target": ledger.session_count,
            "status": "passed"
            if ledger.clean_session_count == ledger.session_count
            else "incomplete",
        },
        {
            "key": "filled_orders",
            "label": "Reconciled fills",
            "current": ledger.filled_order_count,
            "target": policy.minimum_filled_orders,
            "status": "passed"
            if ledger.filled_order_count >= policy.minimum_filled_orders
            else "incomplete",
        },
    ]
    return {"status": ledger.status.value, "items": items, "blockers": list(ledger.blockers)}


def _build_release(sources: DashboardSnapshotSources) -> dict[str, Any]:
    report = sources.candidate_report
    if report is None:
        return {
            "status": "unavailable",
            "release_version": "unknown",
            "specification_version": "unknown",
            "live_capital_eligible": False,
        }
    attestation = sources.build_attestation
    return {
        "status": report.status.value,
        "release_version": report.release_version,
        "specification_version": report.specification_version,
        "tests_passed": attestation.tests_passed if attestation else None,
        "tests_collected": attestation.tests_collected if attestation else None,
        "branch_coverage_pct": None,
        "ruff_errors": None,
        "mypy_errors": None,
        "security_findings": attestation.secret_findings if attestation else None,
        "dependency_vulnerabilities": None,
        "schema_count": attestation.schema_count if attestation else None,
        "invariant_count": None,
        "report_hash": report.report_hash,
        "generated_at": _iso(report.generated_at),
        "paper_release_candidate": report.paper_release_candidate,
        "live_capital_eligible": False,
    }


def _map_alert(item: AlertRecord) -> dict[str, Any]:
    return {
        "severity": item.severity.value,
        "title": item.code,
        "message": item.message,
        "timestamp": _iso(item.created_at),
        "source": "Orchestration",
    }
