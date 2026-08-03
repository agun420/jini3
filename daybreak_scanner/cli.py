from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .alpaca_data import AlpacaMarketDataClient
from .discovery import qualify_candidates, qualifying_tickers
from .errors import ScannerError
from .models import ScannerPolicy
from .rvol import average_daily_volume

ET = ZoneInfo("America/New_York")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daybreak-scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser(
        "scan", help="Discover today's dynamic candidate watchlist and write it to a JSON file"
    )
    scan.add_argument("--top", type=int, default=50, help="Gainers/most-actives rows to fetch")
    scan.add_argument(
        "--rvol-lookback-days",
        type=int,
        default=45,
        help="Calendar days of historical bars to fetch for the RVOL baseline",
    )
    scan.add_argument("--output-dir", required=True)
    return parser


def _run_scan(args: argparse.Namespace) -> int:
    api_key = os.environ.get("APCA_API_KEY_ID")
    secret_key = os.environ.get("APCA_API_SECRET_KEY")
    if not api_key or not secret_key:
        print("daybreak-scanner: missing APCA_API_KEY_ID/APCA_API_SECRET_KEY", file=sys.stderr)
        return 2

    trading_date = datetime.now(ET).date()
    client = AlpacaMarketDataClient(api_key=api_key, secret_key=secret_key)
    try:
        gainers = client.get_gainers(top=args.top)
        actives = client.get_most_actives(top=args.top)
        bars_by_symbol = client.get_daily_bars(
            [item.ticker for item in gainers],
            start=trading_date - timedelta(days=args.rvol_lookback_days),
            end=trading_date - timedelta(days=1),
        )
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
        gainers, actives, policy=policy, average_volume_by_ticker=average_volume_by_ticker
    )
    qualifying = qualifying_tickers(candidates, limit=policy.max_candidates)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"candidates-{trading_date.isoformat()}.json"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "trading_date": trading_date.isoformat(),
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "qualifying_tickers": list(qualifying),
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8"
    )
    print(
        f"daybreak-scanner: scanned {len(candidates)} gainers, "
        f"{len(qualifying)} qualified, wrote {output_path}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "scan":
        return _run_scan(args)
    return 64
