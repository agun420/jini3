"""Command-line entry point for the Phase 1 recorder."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from .adapters import (
    AlpacaCalendarAdapter,
    AlpacaNewsStreamAdapter,
    AlpacaStockStreamAdapter,
    AlpacaTradeUpdateStreamAdapter,
)
from .canonical import canonical_json_text
from .models import SubscriptionManifest
from .orchestration import RecorderService, SessionController
from .persistence import AsyncBatchWriter, PostgresRawEventRepository, RawEventRepository
from .replay import export_session_jsonl
from .sec import SecSubmissionsPoller
from .settings import RecorderSettings
from .util import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="daybreak-recorder")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate-config", help="validate environment settings")
    subparsers.add_parser("run", help="run today's exchange-calendar-aware capture session")

    replay = subparsers.add_parser("replay", help="export a session in exact ingest order")
    replay.add_argument("ingest_session_id", type=UUID)
    replay.add_argument("destination", type=Path)
    replay.add_argument("--after-ingest-seq", type=int, default=0)
    return parser


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except NotImplementedError:  # Windows
            pass


async def run_today(settings: RecorderSettings) -> int:
    api_key, secret_key = settings.require_alpaca_credentials()
    calendar = AlpacaCalendarAdapter(
        api_key=api_key,
        secret_key=secret_key,
        paper=settings.alpaca_paper,
    )
    controller = SessionController(calendar_provider=calendar, settings=settings)
    window = await controller.resolve_today()
    if window is None:
        print(canonical_json_text({"status": "skipped_non_trading_day"}))
        return 0
    now = datetime.now(UTC)
    if now >= window.stop_at:
        print(
            canonical_json_text(
                {
                    "status": "missed_capture_window",
                    "observed_at": now,
                    "scheduled_stop": window.stop_at,
                    "trading_date": window.trading_date,
                }
            )
        )
        # A persistent systemd timer may fire after downtime. This is an audited
        # skip, not a retryable process failure; returning zero prevents a restart loop.
        return 0
    await controller.wait_until_preconnect(window)

    repository = PostgresRawEventRepository(settings.database_url)

    def stream_factory(
        session_id: UUID,
        writer: AsyncBatchWriter,
        manifest: SubscriptionManifest,
    ) -> tuple[
        AlpacaStockStreamAdapter,
        AlpacaNewsStreamAdapter,
        AlpacaTradeUpdateStreamAdapter,
    ]:
        return (
            AlpacaStockStreamAdapter(
                api_key=api_key,
                secret_key=secret_key,
                ingest_session_id=session_id,
                writer=writer,
                manifest=manifest,
                connect_timeout_seconds=settings.stream_connect_timeout_seconds,
            ),
            AlpacaNewsStreamAdapter(
                api_key=api_key,
                secret_key=secret_key,
                ingest_session_id=session_id,
                writer=writer,
                symbols=settings.news_symbols,
                connect_timeout_seconds=settings.stream_connect_timeout_seconds,
            ),
            AlpacaTradeUpdateStreamAdapter(
                api_key=api_key,
                secret_key=secret_key,
                ingest_session_id=session_id,
                writer=writer,
                paper=settings.alpaca_paper,
                connect_timeout_seconds=settings.stream_connect_timeout_seconds,
            ),
        )

    def polling_factory(
        session_id: UUID,
        repository: RawEventRepository,
        writer: AsyncBatchWriter,
    ) -> tuple[SecSubmissionsPoller, ...]:
        if not settings.sec_ciks:
            return ()
        if not settings.sec_user_agent:
            raise RuntimeError("SEC_USER_AGENT is required when DAYBREAK_SEC_CIKS is set")
        return (
            SecSubmissionsPoller(
                ingest_session_id=session_id,
                repository=repository,
                writer=writer,
                ciks=settings.sec_ciks,
                user_agent=settings.sec_user_agent,
                poll_interval_seconds=settings.sec_poll_interval_seconds,
                bootstrap_lookback_hours=settings.sec_bootstrap_lookback_hours,
                requests_per_second=settings.sec_requests_per_second,
                timeout_seconds=settings.sec_timeout_seconds,
            ),
        )

    service = RecorderService(
        settings=settings,
        repository=repository,
        stream_factory=stream_factory,
        polling_factory=polling_factory,
    )
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    result = await service.run_capture(window, external_stop_event=stop_event)
    print(canonical_json_text(result.model_dump(mode="python")))
    return 0 if result.status.value in {"completed", "completed_partial"} else 1


async def replay_session(
    settings: RecorderSettings,
    ingest_session_id: UUID,
    destination: Path,
    after_ingest_seq: int,
) -> int:
    repository = PostgresRawEventRepository(settings.database_url)
    await repository.open()
    try:
        stats = await export_session_jsonl(
            repository,
            ingest_session_id=ingest_session_id,
            destination=destination,
            after_ingest_seq=after_ingest_seq,
        )
    finally:
        await repository.close()
    print(canonical_json_text(asdict(stats)))
    return 0


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = RecorderSettings.from_env()
    configure_logging(settings.log_level)

    if args.command == "validate-config":
        output = settings.model_dump(
            mode="json",
            exclude={"alpaca_api_key", "alpaca_secret_key"},
        )
        output["database_url"] = settings.redacted_database_url
        output["configuration_hash"] = settings.configuration_hash
        output["alpaca_credentials_present"] = (
            settings.alpaca_api_key is not None and settings.alpaca_secret_key is not None
        )
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    if args.command == "run":
        return await run_today(settings)
    if args.command == "replay":
        return await replay_session(
            settings,
            args.ingest_session_id,
            args.destination,
            args.after_ingest_seq,
        )
    raise AssertionError("unreachable command")


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))
