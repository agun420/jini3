"""Alpaca-py stream adapters using raw-data mode for immutable persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from ..models import EventType, RawEvent, RecorderSource, SubscriptionManifest
from ..persistence.batch_writer import AsyncBatchWriter
from .common import CrossLoopEventSink, build_and_submit


class _BaseStreamAdapter:
    source: RecorderSource
    channel: str

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        ingest_session_id: UUID,
        writer: AsyncBatchWriter,
        connect_timeout_seconds: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._ingest_session_id = ingest_session_id
        self._writer = writer
        self._connect_timeout_seconds = connect_timeout_seconds
        self.connection_id = uuid4()
        self._stream: Any | None = None
        self._stop_requested = False
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._sink: CrossLoopEventSink | None = None

    async def _emit_system(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._main_loop is None:
            self._main_loop = asyncio.get_running_loop()
        if self._sink is None:
            self._sink = CrossLoopEventSink(self._writer, self._main_loop)
        now = datetime.now(UTC)
        event = RawEvent.create(
            ingest_session_id=self._ingest_session_id,
            connection_id=self.connection_id,
            source=RecorderSource.SYSTEM,
            channel=self.channel,
            event_type=event_type,
            event_timestamp=now,
            received_at=now,
            payload=payload,
        )
        await self._sink.submit(event)

    async def stop(self) -> None:
        self._stop_requested = True
        stream = self._stream
        if stream is None:
            return
        stop_ws = getattr(stream, "stop_ws", None)
        if stop_ws is not None:
            await stop_ws()
            return
        await asyncio.to_thread(stream.stop)

    async def _run_sdk_stream(
        self,
        stream: Any,
        *,
        connected_payload: dict[str, Any],
    ) -> None:
        """Run a pinned alpaca-py stream and persist truthful lifecycle events.

        alpaca-py exposes an internal ``_running`` flag only after authentication
        and subscription setup. Version 0.43.5 is pinned, so this compatibility
        boundary is deliberate and covered by adapter tests. State transitions
        are monitored to record SDK-managed disconnects and reconnects.
        """
        self._stop_requested = False
        runner = asyncio.create_task(
            asyncio.to_thread(stream.run),
            name=f"{type(self).__name__}-sdk-runner",
        )
        connected = False
        ever_connected = False
        generation = 0
        deadline = asyncio.get_running_loop().time() + self._connect_timeout_seconds
        try:
            while True:
                if runner.done():
                    await runner
                    if self._stop_requested:
                        return
                    if not ever_connected:
                        raise RuntimeError("Alpaca stream ended before becoming ready")
                    raise RuntimeError("Alpaca stream ended unexpectedly")

                sdk_running = bool(getattr(stream, "_running", False))
                if sdk_running and not connected:
                    generation += 1
                    connected = True
                    ever_connected = True
                    await self._emit_system(
                        EventType.STREAM_CONNECTED,
                        {
                            **connected_payload,
                            "connection_generation": generation,
                        },
                    )
                elif not sdk_running and connected:
                    await self._emit_system(
                        EventType.STREAM_DISCONNECTED,
                        {
                            "adapter": type(self).__name__,
                            "connection_id": str(self.connection_id),
                            "connection_generation": generation,
                            "reason": "sdk_not_running",
                        },
                    )
                    connected = False

                if not ever_connected and asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError(
                        "Alpaca stream did not authenticate and subscribe within "
                        f"{self._connect_timeout_seconds} seconds"
                    )
                await asyncio.sleep(0.05)
        except Exception as exc:
            await self._emit_system(
                EventType.ERROR,
                {
                    "adapter": type(self).__name__,
                    "connection_id": str(self.connection_id),
                    "error_type": type(exc).__qualname__,
                    "error_message": str(exc) or repr(exc),
                },
            )
            raise
        finally:
            if not runner.done():
                try:
                    await self.stop()
                    await asyncio.wait_for(
                        runner,
                        timeout=self._connect_timeout_seconds,
                    )
                except Exception:
                    runner.cancel()
                    await asyncio.gather(runner, return_exceptions=True)
            if connected:
                await self._emit_system(
                    EventType.STREAM_DISCONNECTED,
                    {
                        "adapter": type(self).__name__,
                        "connection_id": str(self.connection_id),
                        "connection_generation": generation,
                        "reason": "adapter_stopped",
                    },
                )


class AlpacaStockStreamAdapter(_BaseStreamAdapter):
    source = RecorderSource.ALPACA_SIP
    channel = "stock_data"

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        ingest_session_id: UUID,
        writer: AsyncBatchWriter,
        manifest: SubscriptionManifest,
        connect_timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            secret_key=secret_key,
            ingest_session_id=ingest_session_id,
            writer=writer,
            connect_timeout_seconds=connect_timeout_seconds,
        )
        self._manifest = manifest

    async def run(self) -> None:
        try:
            from alpaca.data.enums import DataFeed
            from alpaca.data.live import StockDataStream
        except ImportError as exc:  # pragma: no cover - production extra
            raise RuntimeError(
                "alpaca-py is required; install pip install -e '.[recorder]'"
            ) from exc

        self._main_loop = asyncio.get_running_loop()
        sink = CrossLoopEventSink(self._writer, self._main_loop)
        self._sink = sink
        stream = StockDataStream(
            self._api_key,
            self._secret_key,
            raw_data=True,
            feed=DataFeed.SIP,
        )
        self._stream = stream

        async def trade(message: Any) -> None:
            await build_and_submit(
                sink=sink,
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=self.source,
                channel="trades",
                event_type=EventType.TRADE,
                message=message,
            )

        async def quote(message: Any) -> None:
            await build_and_submit(
                sink=sink,
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=self.source,
                channel="quotes",
                event_type=EventType.QUOTE,
                message=message,
            )

        async def bar(message: Any) -> None:
            await build_and_submit(
                sink=sink,
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=self.source,
                channel="minute_bars",
                event_type=EventType.MINUTE_BAR,
                message=message,
            )

        async def updated_bar(message: Any) -> None:
            await build_and_submit(
                sink=sink,
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=self.source,
                channel="updated_bars",
                event_type=EventType.UPDATED_BAR,
                message=message,
            )

        async def trading_status(message: Any) -> None:
            await build_and_submit(
                sink=sink,
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=self.source,
                channel="trading_statuses",
                event_type=EventType.TRADING_STATUS,
                message=message,
            )

        async def trade_cancel(message: Any) -> None:
            await build_and_submit(
                sink=sink,
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=self.source,
                channel="trade_cancels",
                event_type=EventType.TRADE_CANCEL,
                message=message,
            )

        async def trade_correction(message: Any) -> None:
            await build_and_submit(
                sink=sink,
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=self.source,
                channel="trade_corrections",
                event_type=EventType.TRADE_CORRECTION,
                message=message,
            )

        stream.register_trade_cancels(trade_cancel)
        stream.register_trade_corrections(trade_correction)

        if self._manifest.wildcard_minute_bars:
            stream.subscribe_bars(bar, "*")
            stream.subscribe_updated_bars(updated_bar, "*")
        elif self._manifest.tick_symbols:
            stream.subscribe_bars(bar, *self._manifest.tick_symbols)
            stream.subscribe_updated_bars(updated_bar, *self._manifest.tick_symbols)

        if self._manifest.wildcard_trading_statuses:
            stream.subscribe_trading_statuses(trading_status, "*")
        elif self._manifest.tick_symbols:
            stream.subscribe_trading_statuses(trading_status, *self._manifest.tick_symbols)

        if self._manifest.tick_symbols:
            stream.subscribe_trades(trade, *self._manifest.tick_symbols)
            stream.subscribe_quotes(quote, *self._manifest.tick_symbols)

        await self._run_sdk_stream(
            stream,
            connected_payload={
                "adapter": type(self).__name__,
                "connection_id": str(self.connection_id),
                "feed": "sip",
                "manifest_version": self._manifest.version,
            },
        )


class AlpacaNewsStreamAdapter(_BaseStreamAdapter):
    source = RecorderSource.ALPACA_NEWS
    channel = "news"

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        ingest_session_id: UUID,
        writer: AsyncBatchWriter,
        symbols: tuple[str, ...] = ("*",),
        connect_timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            secret_key=secret_key,
            ingest_session_id=ingest_session_id,
            writer=writer,
            connect_timeout_seconds=connect_timeout_seconds,
        )
        self._symbols = symbols

    async def run(self) -> None:
        try:
            from alpaca.data.live.news import NewsDataStream
        except ImportError as exc:  # pragma: no cover - production extra
            raise RuntimeError(
                "alpaca-py NewsDataStream is required; install recorder extras"
            ) from exc

        self._main_loop = asyncio.get_running_loop()
        sink = CrossLoopEventSink(self._writer, self._main_loop)
        self._sink = sink
        stream = NewsDataStream(self._api_key, self._secret_key, raw_data=True)
        self._stream = stream

        async def news(message: Any) -> None:
            await build_and_submit(
                sink=sink,
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=self.source,
                channel="news",
                event_type=EventType.NEWS,
                message=message,
            )

        stream.subscribe_news(news, *self._symbols)
        await self._run_sdk_stream(
            stream,
            connected_payload={
                "adapter": type(self).__name__,
                "connection_id": str(self.connection_id),
                "symbols": list(self._symbols),
            },
        )


class AlpacaTradeUpdateStreamAdapter(_BaseStreamAdapter):
    source = RecorderSource.ALPACA_TRADING
    channel = "trade_updates"

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        ingest_session_id: UUID,
        writer: AsyncBatchWriter,
        paper: bool,
        connect_timeout_seconds: float = 20.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            secret_key=secret_key,
            ingest_session_id=ingest_session_id,
            writer=writer,
            connect_timeout_seconds=connect_timeout_seconds,
        )
        self._paper = paper

    async def run(self) -> None:
        try:
            from alpaca.trading.stream import TradingStream
        except ImportError as exc:  # pragma: no cover - production extra
            raise RuntimeError("alpaca-py TradingStream is required") from exc

        self._main_loop = asyncio.get_running_loop()
        sink = CrossLoopEventSink(self._writer, self._main_loop)
        self._sink = sink
        stream = TradingStream(
            self._api_key,
            self._secret_key,
            paper=self._paper,
            raw_data=True,
        )
        self._stream = stream

        async def update(message: Any) -> None:
            await build_and_submit(
                sink=sink,
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=self.source,
                channel="trade_updates",
                event_type=EventType.TRADE_UPDATE,
                message=message,
            )

        stream.subscribe_trade_updates(update)
        await self._run_sdk_stream(
            stream,
            connected_payload={
                "adapter": type(self).__name__,
                "connection_id": str(self.connection_id),
                "paper": self._paper,
            },
        )
