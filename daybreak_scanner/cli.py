from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .alpaca_data import AlpacaMarketDataClient
from .dashboard_export import build_scanner_dashboard_snapshot
from .discovery import qualify_candidates, qualifying_tickers
from .errors import ScannerError
from .forecast import (
    DEFAULT_HORIZON,
    ForecastError,
    TimesFMForecaster,
    daily_closes_by_ticker,
    trend_pct,
)
from .models import ScannerPolicy, Signal, SignalOutcome
from .outcomes import expire_at_close, resolve_outcome
from .rvol import average_daily_volume
from .scorecard import build_scorecard
from .signals import build_signals

ET = ZoneInfo("America/New_York")
SESSION_CLOSE_ET = time(16, 0, 0)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daybreak-scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser(
        "scan",
        help=(
            "Discover today's dynamic candidate watchlist, build ATR-based "
            "entry/stop/target signals, and write both to JSON files"
        ),
    )
    scan.add_argument("--top", type=int, default=50, help="Gainers/most-actives rows to fetch")
    scan.add_argument(
        "--rvol-lookback-days",
        type=int,
        default=45,
        help="Calendar days of historical bars to fetch for the RVOL/ATR baseline",
    )
    scan.add_argument("--output-dir", required=True)
    scan.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Overwrite an existing signals-<date>.json for today's trading date instead of "
            "refusing. scan is meant to run once per trading day; a second run silently "
            "replacing the first orphans any outcomes check-outcomes already resolved against "
            "it (they keep counting toward the scorecard even though their signal is gone). "
            "Only pass this for a deliberate, intentional re-scan."
        ),
    )
    scan.add_argument(
        "--with-forecast",
        action="store_true",
        help=(
            "Also compute a TimesFM short-horizon trend forecast per qualifying candidate "
            "(informational only; requires pip install '.[forecast]'). Unverified against "
            "the real model in this project's own CI/dev environment -- see "
            "daybreak_scanner/forecast.py."
        ),
    )

    check = sub.add_parser(
        "check-outcomes",
        help="Resolve pending signals against real subsequent prices and update the scorecard",
    )
    check.add_argument("--signals-dir", required=True)
    check.add_argument("--outcomes-dir", required=True)
    check.add_argument(
        "--trading-date",
        help="Exchange date in YYYY-MM-DD; defaults to today (America/New_York)",
    )

    snapshot = sub.add_parser(
        "dashboard-snapshot",
        help=(
            "Export a dashboard.schema.json-shaped snapshot of scanner state "
            "(latest day's signals + the cumulative scorecard)."
        ),
    )
    snapshot.add_argument(
        "--scanner-dir", required=True, help="Directory 'scan' writes candidates-/signals- to"
    )
    snapshot.add_argument(
        "--outcomes-dir",
        required=True,
        help="Directory 'check-outcomes' writes outcomes-*.json/scorecard.json to",
    )
    snapshot.add_argument("--output", required=True)
    snapshot.add_argument(
        "--public",
        action="store_true",
        help=(
            "Mark the snapshot data_mode=published, public_safe=true, fit to commit as the "
            "live dashboard/data/dashboard.json (e.g. from the GitHub Actions automation). "
            "Without this flag the snapshot is private (data_mode=local) and must never be "
            "committed -- load it only via the dashboard's 'Load private snapshot' control."
        ),
    )
    return parser


def _run_scan(args: argparse.Namespace) -> int:
    api_key = os.environ.get("APCA_API_KEY_ID")
    secret_key = os.environ.get("APCA_API_SECRET_KEY")
    if not api_key or not secret_key:
        print("daybreak-scanner: missing APCA_API_KEY_ID/APCA_API_SECRET_KEY", file=sys.stderr)
        return 2

    trading_date = datetime.now(ET).date()
    output_dir = Path(args.output_dir)
    signals_path = output_dir / f"signals-{trading_date.isoformat()}.json"
    if signals_path.exists() and not args.replace:
        print(
            f"daybreak-scanner: {signals_path} already exists; scan already ran for "
            f"{trading_date.isoformat()}. Pass --replace to overwrite anyway (only for a "
            "deliberate re-scan -- see --replace's help text for why this is otherwise refused)",
            file=sys.stderr,
        )
        return 5

    client = AlpacaMarketDataClient(api_key=api_key, secret_key=secret_key)
    try:
        gainers = client.get_gainers(top=args.top)
        tickers = [item.ticker for item in gainers]
        try:
            volume_by_ticker = client.get_current_volumes(tickers)
        except ScannerError as exc:
            # Per-ticker current volume is a hard qualification input (unlike
            # RVOL below): without it every candidate would look "absent" and
            # falsely disqualify, so a fetch failure here is fatal.
            print(f"daybreak-scanner: {exc}", file=sys.stderr)
            return 3
        try:
            bars_by_symbol = client.get_daily_bars(
                tickers,
                start=trading_date - timedelta(days=args.rvol_lookback_days),
                end=trading_date - timedelta(days=1),
            )
        except ScannerError as exc:
            # RVOL/ATR are both derived from this same bar history and are
            # already designed to be skipped gracefully without it (see
            # qualify_candidates/build_signals), so degrade rather than
            # discarding an otherwise-valid day's scan.
            print(
                f"daybreak-scanner: historical bars unavailable, skipping RVOL/ATR: {exc}",
                file=sys.stderr,
            )
            bars_by_symbol = {}
    except ScannerError as exc:
        print(f"daybreak-scanner: {exc}", file=sys.stderr)
        return 3
    finally:
        client.close()

    policy = ScannerPolicy()
    average_volume_by_ticker = {}
    for symbol, bars in bars_by_symbol.items():
        average = average_daily_volume(bars, lookback_sessions=policy.rvol_lookback_sessions)
        if average is not None:
            average_volume_by_ticker[symbol] = average

    candidates = qualify_candidates(
        gainers,
        volume_by_ticker,
        policy=policy,
        average_volume_by_ticker=average_volume_by_ticker,
    )
    qualifying = qualifying_tickers(candidates, limit=policy.max_candidates)
    generated_at = datetime.now(UTC)

    forecast_trend_by_ticker = {}
    if args.with_forecast:
        qualifying_bars = {
            ticker: bars for ticker, bars in bars_by_symbol.items() if ticker in qualifying
        }
        closes_by_ticker = daily_closes_by_ticker(qualifying_bars)
        try:
            point_forecast_by_ticker = TimesFMForecaster().forecast(
                closes_by_ticker, horizon=DEFAULT_HORIZON
            )
            forecast_trend_by_ticker = {
                ticker: trend
                for ticker, forecast_values in point_forecast_by_ticker.items()
                if (trend := trend_pct(closes_by_ticker[ticker], forecast_values)) is not None
            }
        except ForecastError as exc:
            # Purely informational (see daybreak_scanner.forecast): a failure here
            # never invalidates the mechanical signals already computed above.
            print(
                f"daybreak-scanner: forecast unavailable, continuing without it: {exc}",
                file=sys.stderr,
            )

    signals = build_signals(
        candidates,
        bars_by_symbol,
        trading_date=trading_date,
        generated_at=generated_at,
        forecast_trend_by_ticker=forecast_trend_by_ticker,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = output_dir / f"candidates-{trading_date.isoformat()}.json"
    candidates_payload = {
        "generated_at": generated_at.isoformat(),
        "trading_date": trading_date.isoformat(),
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "qualifying_tickers": list(qualifying),
    }
    candidates_path.write_text(
        json.dumps(candidates_payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    signals_payload = {
        "generated_at": generated_at.isoformat(),
        "trading_date": trading_date.isoformat(),
        "signals": [item.model_dump(mode="json") for item in signals],
    }
    signals_path.write_text(
        json.dumps(signals_payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    print(
        f"daybreak-scanner: scanned {len(candidates)} gainers, {len(qualifying)} qualified, "
        f"{len(signals)} signals -> {candidates_path.name}, {signals_path.name}"
    )
    return 0


def _run_check_outcomes(args: argparse.Namespace) -> int:
    api_key = os.environ.get("APCA_API_KEY_ID")
    secret_key = os.environ.get("APCA_API_SECRET_KEY")
    if not api_key or not secret_key:
        print("daybreak-scanner: missing APCA_API_KEY_ID/APCA_API_SECRET_KEY", file=sys.stderr)
        return 2

    trading_date = (
        date.fromisoformat(args.trading_date) if args.trading_date else datetime.now(ET).date()
    )
    signals_path = Path(args.signals_dir) / f"signals-{trading_date.isoformat()}.json"
    if not signals_path.exists():
        print(f"daybreak-scanner: no signals file at {signals_path}", file=sys.stderr)
        return 4
    # Signal/SignalOutcome are strict models: model_validate() on an
    # already-parsed dict demands exact Python types (Decimal, date), but
    # json.loads() only ever produces str/int/float. model_validate_json()
    # uses pydantic's JSON-mode coercion instead, which is what round-tripping
    # through a JSON file actually needs.
    raw_signals = json.loads(signals_path.read_text(encoding="utf-8"))["signals"]
    signals = [Signal.model_validate_json(json.dumps(item)) for item in raw_signals]
    signal_tickers = {signal.ticker for signal in signals}

    outcomes_dir = Path(args.outcomes_dir)
    outcomes_dir.mkdir(parents=True, exist_ok=True)
    outcomes_path = outcomes_dir / f"outcomes-{trading_date.isoformat()}.json"
    resolved: dict[str, SignalOutcome] = {}
    if outcomes_path.exists():
        raw_outcomes = json.loads(outcomes_path.read_text(encoding="utf-8"))["outcomes"]
        # A prior run's signals-<date>.json can have since been replaced (`scan --replace`):
        # drop any already-resolved outcome whose ticker isn't in *today's current* signal set
        # rather than carrying it forward forever -- it would otherwise count toward the
        # scorecard's all-time win rate for a signal that, as far as the dashboard is
        # concerned, no longer exists.
        resolved = {
            item["ticker"]: SignalOutcome.model_validate_json(json.dumps(item))
            for item in raw_outcomes
            if item["ticker"] in signal_tickers
        }

    session_close = datetime.combine(trading_date, SESSION_CLOSE_ET, tzinfo=ET).astimezone(UTC)
    now = datetime.now(UTC)
    client = AlpacaMarketDataClient(api_key=api_key, secret_key=secret_key)
    try:
        for signal in signals:
            if signal.ticker in resolved:
                continue
            end = min(now, session_close)
            try:
                bars = client.get_minute_bars(signal.ticker, start=signal.generated_at, end=end)
            except ScannerError as exc:
                print(
                    f"daybreak-scanner: skipping {signal.ticker}, bars unavailable: {exc}",
                    file=sys.stderr,
                )
                continue
            outcome = resolve_outcome(signal, bars)
            if outcome is None and now >= session_close:
                close_price = bars[-1].close if bars else signal.entry_price
                outcome = expire_at_close(signal, close_price=close_price, closed_at=session_close)
            if outcome is not None:
                resolved[signal.ticker] = outcome
    finally:
        client.close()

    outcomes_payload = {
        "trading_date": trading_date.isoformat(),
        "checked_at": now.isoformat(),
        "outcomes": [item.model_dump(mode="json") for item in resolved.values()],
    }
    outcomes_path.write_text(
        json.dumps(outcomes_payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    all_outcomes: list[SignalOutcome] = []
    for path in sorted(outcomes_dir.glob("outcomes-*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))["outcomes"]
        all_outcomes.extend(SignalOutcome.model_validate_json(json.dumps(item)) for item in raw)
    scorecard = build_scorecard(all_outcomes)
    scorecard_path = outcomes_dir / "scorecard.json"
    scorecard_path.write_text(
        json.dumps(
            {"updated_at": now.isoformat(), **scorecard},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    wins = sum(1 for item in resolved.values() if item.outcome == "win")
    losses = sum(1 for item in resolved.values() if item.outcome == "loss")
    expired = sum(1 for item in resolved.values() if item.outcome == "expired")
    print(
        f"daybreak-scanner: {len(resolved)}/{len(signals)} signals resolved "
        f"({wins} win, {losses} loss, {expired} expired) -> {outcomes_path}; "
        f"scorecard now {scorecard['total_signals']} signals, "
        f"win rate {scorecard['win_rate_pct']}%"
    )
    return 0


def _run_dashboard_snapshot(args: argparse.Namespace) -> int:
    snapshot = build_scanner_dashboard_snapshot(
        scanner_dir=Path(args.scanner_dir),
        outcomes_dir=Path(args.outcomes_dir),
        public=args.public,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    if args.public:
        print(
            f"daybreak-scanner: wrote a public dashboard snapshot to {output_path} "
            "(data_mode=published, public_safe=true).",
            file=sys.stderr,
        )
    else:
        print(
            f"daybreak-scanner: wrote a private dashboard snapshot to {output_path}. "
            "It may contain real ticker/price data: never commit it, and load it only via "
            "the dashboard's 'Load private snapshot' control.",
            file=sys.stderr,
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "scan":
        return _run_scan(args)
    if args.command == "check-outcomes":
        return _run_check_outcomes(args)
    if args.command == "dashboard-snapshot":
        return _run_dashboard_snapshot(args)
    return 64
