from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from daybreak_recorder.adapters.alpaca_streams import _BaseStreamAdapter
from daybreak_recorder.adapters.common import extract_symbols, model_to_payload, parse_timestamp
from daybreak_recorder.models import EventType, RecorderSource
from daybreak_recorder.persistence.batch_writer import AsyncBatchWriter
from daybreak_recorder.persistence.repository import InMemoryRawEventRepository


def test_nanosecond_provider_timestamp_is_deterministically_truncated_to_microseconds() -> None:
    value = parse_timestamp("2026-07-31T09:30:00.123456789Z")
    assert value.microsecond == 123456
    assert value.tzinfo == UTC


def test_symbol_extraction_handles_news_and_nested_orders() -> None:
    assert extract_symbols({"symbols": ["aapl", "MSFT", "AAPL"]}) == ("AAPL", "MSFT")
    assert extract_symbols({"order": {"symbol": "nvda"}}) == ("NVDA",)


class FakeNanosecondTimestamp:
    def __init__(self, seconds: int, nanoseconds: int) -> None:
        self.seconds = seconds
        self.nanoseconds = nanoseconds


def test_raw_provider_timestamp_preserves_nanoseconds_before_event_time_truncation() -> None:
    raw = FakeNanosecondTimestamp(1785504600, 123456789)
    payload = model_to_payload({"S": "AAPL", "t": raw})
    assert payload["t"].endswith(".123456789Z")
    parsed = parse_timestamp(payload["t"])
    assert parsed.microsecond == 123456


def test_unsupported_timestamp_type_does_not_silently_fallback() -> None:
    with pytest.raises(TypeError):
        parse_timestamp(123, fallback=datetime.now(UTC))


class LifecycleAdapter(_BaseStreamAdapter):
    source = RecorderSource.ALPACA_SIP
    channel = "test_stream"


class FakeSdkStream:
    def __init__(self, *, become_ready: bool = True) -> None:
        self._running = False
        self._become_ready = become_ready
        self._stop = threading.Event()

    def run(self) -> None:
        if self._become_ready:
            self._running = True
        self._stop.wait(timeout=2)
        self._running = False

    async def stop_ws(self) -> None:
        self._stop.set()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_stream_lifecycle_is_recorded_only_after_sdk_reports_ready() -> None:
    repository = InMemoryRawEventRepository()
    writer = AsyncBatchWriter(
        repository,
        queue_maxsize=100,
        batch_size=1,
        flush_interval_seconds=0.01,
        enqueue_timeout_seconds=1,
    )
    await writer.start()
    adapter = LifecycleAdapter(
        api_key="key",
        secret_key="secret",
        ingest_session_id=uuid4(),
        writer=writer,
        connect_timeout_seconds=0.5,
    )
    stream = FakeSdkStream()
    adapter._stream = stream

    task = asyncio.create_task(
        adapter._run_sdk_stream(
            stream,
            connected_payload={"adapter": "fake"},
        )
    )
    while not repository.events:
        await asyncio.sleep(0.01)
    assert repository.events[0].event.event_type == EventType.STREAM_CONNECTED
    await adapter.stop()
    await task
    await writer.stop()

    assert [item.event.event_type for item in repository.events] == [
        EventType.STREAM_CONNECTED,
        EventType.STREAM_DISCONNECTED,
    ]


@pytest.mark.asyncio
async def test_stream_connect_timeout_emits_error_and_stops_sdk_runner() -> None:
    repository = InMemoryRawEventRepository()
    writer = AsyncBatchWriter(
        repository,
        queue_maxsize=100,
        batch_size=1,
        flush_interval_seconds=0.01,
        enqueue_timeout_seconds=1,
    )
    await writer.start()
    adapter = LifecycleAdapter(
        api_key="key",
        secret_key="secret",
        ingest_session_id=uuid4(),
        writer=writer,
        connect_timeout_seconds=0.02,
    )
    stream = FakeSdkStream(become_ready=False)
    adapter._stream = stream

    with pytest.raises(TimeoutError):
        await adapter._run_sdk_stream(
            stream,
            connected_payload={"adapter": "fake"},
        )
    await writer.stop()

    assert [item.event.event_type for item in repository.events] == [EventType.ERROR]
    assert stream._stop.is_set()


@pytest.mark.asyncio
async def test_stream_monitor_records_sdk_disconnect_and_reconnect_generations() -> None:
    repository = InMemoryRawEventRepository()
    writer = AsyncBatchWriter(
        repository,
        queue_maxsize=100,
        batch_size=1,
        flush_interval_seconds=0.01,
        enqueue_timeout_seconds=1,
    )
    await writer.start()
    adapter = LifecycleAdapter(
        api_key="key",
        secret_key="secret",
        ingest_session_id=uuid4(),
        writer=writer,
        connect_timeout_seconds=0.5,
    )
    stream = FakeSdkStream()
    adapter._stream = stream
    task = asyncio.create_task(
        adapter._run_sdk_stream(stream, connected_payload={"adapter": "fake"})
    )

    while len(repository.events) < 1:
        await asyncio.sleep(0.01)
    stream._running = False
    while len(repository.events) < 2:
        await asyncio.sleep(0.01)
    stream._running = True
    while len(repository.events) < 3:
        await asyncio.sleep(0.01)
    await adapter.stop()
    await task
    await writer.stop()

    assert [item.event.event_type for item in repository.events] == [
        EventType.STREAM_CONNECTED,
        EventType.STREAM_DISCONNECTED,
        EventType.STREAM_CONNECTED,
        EventType.STREAM_DISCONNECTED,
    ]
    assert repository.events[0].event.payload["connection_generation"] == 1
    assert repository.events[2].event.payload["connection_generation"] == 2
