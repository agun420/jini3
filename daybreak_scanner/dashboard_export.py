"""Maps the scanner's local JSON files into a dashboard.schema.json-shaped
private snapshot -- entirely separate from daybreak/dashboard_snapshot.py.

Scanner mode never runs the evaluator, sizes no position with real capital
logic, and submits no order, so its signals carry no conviction_score,
technical_grade, or catalyst thesis the way the audited system's real signals
do. `system.name`/`system.phase` say so explicitly and every signal's `status`
is "scanner_signal" (never "approved"/"qualified"/"excluded"), so this can
never be mistaken for the audited system's real paper-trading output.

Verified by hand against the real dashboard (Playwright: loaded a sample
snapshot, opened the Setup ledger and a signal's detail dialog, checked the
Performance view -- no console errors, no leaked literal "undefined" text,
genuinely-unavailable dollar fields render "--" rather than a fabricated
number). One known cosmetic quirk from that check: the Trading view's
Approved/Qualified/Excluded/Average-score summary cards only recognize the
evaluator's own status taxonomy, so they always read 0 for scanner-mode
signals even though the setup ledger table below them is populated -- fixing
that would mean reusing "approved" as the status, which was rejected
specifically because it would misrepresent a mechanical signal as an
evaluator-approved one.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .models import Signal, SignalOutcome

SCHEMA_VERSION = "1.0"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _load_signals(path: Path) -> tuple[Signal, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))["signals"]
    return tuple(Signal.model_validate_json(json.dumps(item)) for item in raw)


def _load_outcomes(path: Path) -> dict[str, SignalOutcome]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))["outcomes"]
    return {item["ticker"]: SignalOutcome.model_validate_json(json.dumps(item)) for item in raw}


def _map_signal(rank: int, signal: Signal, outcome: SignalOutcome | None) -> dict[str, Any]:
    return {
        "ticker": signal.ticker,
        "rank": rank,
        "status": "scanner_signal",
        "execution_status": outcome.outcome if outcome is not None else "pending",
        "conviction_score": 0,
        # The detail dialog interpolates these into template-literal text
        # unconditionally (no null-guard): omitting them renders the literal
        # word "undefined" in the UI, so an empty string -- not omission --
        # is the honest way to say "no evaluator ran, there is no thesis."
        "technical_grade": "",
        "catalyst_source": "",
        "catalyst": "",
        "thesis": "no evaluator ran for this signal (mechanical scanner mode)",
        "entry_price": float(signal.entry_price),
        "stop_price": float(signal.stop_price),
        "target_price": float(signal.target_price),
        "updated_at": _iso(outcome.resolved_at if outcome is not None else signal.generated_at),
    }


def build_scanner_dashboard_snapshot(
    *,
    scanner_dir: Path,
    outcomes_dir: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Reads the most recent day's signals/outcomes plus the cumulative
    scorecard already written by `daybreak-scanner check-outcomes`."""
    now = (generated_at or datetime.now(UTC)).astimezone(UTC)

    signal_files = sorted(scanner_dir.glob("signals-*.json"))
    latest_signals: tuple[Signal, ...] = ()
    latest_trading_date: date | None = None
    latest_outcomes: dict[str, SignalOutcome] = {}
    if signal_files:
        latest_path = signal_files[-1]
        latest_trading_date = date.fromisoformat(latest_path.stem.removeprefix("signals-"))
        latest_signals = _load_signals(latest_path)
        latest_outcomes = _load_outcomes(
            outcomes_dir / f"outcomes-{latest_trading_date.isoformat()}.json"
        )

    scorecard_path = outcomes_dir / "scorecard.json"
    scorecard: dict[str, Any] = (
        json.loads(scorecard_path.read_text(encoding="utf-8")) if scorecard_path.exists() else {}
    )
    session_count = len(list(outcomes_dir.glob("outcomes-*.json")))

    win_rate_pct = scorecard.get("win_rate_pct")
    win_rate = float(win_rate_pct) / 100 if win_rate_pct is not None else None

    trading_date = latest_trading_date or now.date()
    ranked = sorted(latest_signals, key=lambda item: item.percent_change, reverse=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "data_mode": "local",
        "environment": "paper",
        "public_safe": False,
        "system": {
            "name": "Project Daybreak Scanner (mechanical, no evaluator, no orders)",
            "version": "unknown",
            "specification_version": "unknown",
            "phase": "scanning",
            "market_status": "unknown",
            "market_detail": "",
            "timezone": "America/New_York",
            "freshness_threshold_seconds": 900,
        },
        "safety": {
            "paper_only": True,
            "live_capital_eligible": False,
            "kill_switch_active": False,
            "entries_enabled": False,
            "all_positions_flat": True,
        },
        "account": {"currency": "USD"},
        "session": {
            "session_id": f"scanner-{trading_date.isoformat()}",
            "trading_date": trading_date.isoformat(),
            "state": "scanning",
            "approved_setup_count": len(latest_signals),
            "orders_submitted": 0,
            "orders_filled": 0,
        },
        "performance": {
            "summary": {
                "session_count": session_count,
                "trade_count": scorecard.get("total_signals", 0),
                "winning_trade_count": scorecard.get("wins", 0),
                "losing_trade_count": scorecard.get("losses", 0),
                "breakeven_trade_count": scorecard.get("expired", 0),
                "win_rate": win_rate,
                # Every one of these is a real UI card (app.mjs reads them with
                # `=== null` checks, not `?? default`, so a *missing* key
                # throws rather than showing "--"): genuinely null here
                # because scanner mode never sizes a real dollar position.
                "gross_pnl": None,
                "fees": None,
                "net_pnl": None,
                "profit_factor": None,
                "expectancy": None,
                "maximum_drawdown": None,
                "average_r_multiple": None,
                "average_entry_slippage_bps": None,
                # Not read by the current dashboard UI, kept for a future
                # scanner-aware view: mean signal return in percent terms.
                "average_return_pct": scorecard.get("average_return_pct"),
            },
            "equity_curve": [],
            "daily": [],
            "attributions": [],
            "trades": [],
        },
        "signals": [
            _map_signal(index + 1, signal, latest_outcomes.get(signal.ticker))
            for index, signal in enumerate(ranked)
        ],
        "positions": [],
        "orders": [],
        "services": [],
        "qualification": {"status": "unavailable", "items": [], "blockers": []},
        "release": {
            "status": "unavailable",
            "release_version": "unknown",
            "specification_version": "unknown",
            "live_capital_eligible": False,
        },
        "alerts": [],
    }
