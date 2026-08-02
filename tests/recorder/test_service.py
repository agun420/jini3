from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from daybreak_recorder.models import SessionStatus
from daybreak_recorder.orchestration.calendar import CaptureWindow
from daybreak_recorder.orchestration.service import RecorderService
from daybreak_recorder.persistence.repository import InMemoryRawEventRepository
from daybreak_recorder.settings import RecorderSettings


class FakeStream:
    def __init__(self) -> None:
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        await self._stopped.wait()

    async def stop(self) -> None:
        self._stopped.set()


@pytest.mark.asyncio
async def test_service_records_manifest_and_closes_cleanly() -> None:
    now = datetime.now(UTC)
    window = CaptureWindow(
        trading_date=date.today(),
        start_at=now + timedelta(milliseconds=20),
        stop_at=now + timedelta(milliseconds=80),
        regular_open_at=now - timedelta(hours=1),
        regular_close_at=now + timedelta(hours=6),
    )
    settings = RecorderSettings.model_validate(
        {
            "batch_size": 1,
            "flush_interval_seconds": 0.01,
            "queue_maxsize": 1000,
        }
    )
    repository = InMemoryRawEventRepository()

    def stream_factory(session_id, writer, manifest):
        del session_id, writer, manifest
        return (FakeStream(),)

    result = await RecorderService(
        settings=settings,
        repository=repository,
        stream_factory=stream_factory,
    ).run_capture(window)

    assert result.status == SessionStatus.COMPLETED
    assert result.writer_submitted == 1
    assert result.writer_persisted == 1
    assert repository.events[0].event.event_type.value == "subscription_manifest"


class HangingStream:
    async def run(self) -> None:
        await asyncio.Event().wait()

    async def stop(self) -> None:
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_service_fails_closed_when_stream_shutdown_times_out() -> None:
    now = datetime.now(UTC)
    window = CaptureWindow(
        trading_date=date.today(),
        start_at=now - timedelta(seconds=1),
        stop_at=now + timedelta(milliseconds=30),
        regular_open_at=now - timedelta(hours=1),
        regular_close_at=now + timedelta(hours=6),
    )
    settings = RecorderSettings.model_validate(
        {
            "batch_size": 1,
            "flush_interval_seconds": 0.01,
            "queue_maxsize": 1000,
            "shutdown_timeout_seconds": 0.02,
        }
    )
    repository = InMemoryRawEventRepository()

    def stream_factory(session_id, writer, manifest):
        del session_id, writer, manifest
        return (HangingStream(),)

    result = await RecorderService(
        settings=settings,
        repository=repository,
        stream_factory=stream_factory,
    ).run_capture(window)

    assert result.status == SessionStatus.FAILED
    assert result.error_message is not None
    assert "stream stop timeout" in result.error_message


@pytest.mark.asyncio
async def test_successful_late_start_is_marked_completed_partial() -> None:
    now = datetime.now(UTC)
    window = CaptureWindow(
        trading_date=date.today(),
        start_at=now - timedelta(minutes=5),
        stop_at=now + timedelta(milliseconds=40),
        regular_open_at=now - timedelta(hours=1),
        regular_close_at=now + timedelta(hours=6),
    )
    settings = RecorderSettings.model_validate(
        {
            "batch_size": 1,
            "flush_interval_seconds": 0.01,
            "queue_maxsize": 1000,
        }
    )
    repository = InMemoryRawEventRepository()

    def stream_factory(session_id, writer, manifest):
        del session_id, writer, manifest
        return (FakeStream(),)

    result = await RecorderService(
        settings=settings,
        repository=repository,
        stream_factory=stream_factory,
    ).run_capture(window)

    assert result.status == SessionStatus.COMPLETED_PARTIAL
