"""Recorder-session lifecycle and fail-closed stream supervision."""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from ..models import (
    EventType,
    IngestSession,
    RawEvent,
    RecorderSource,
    SessionStatus,
    SubscriptionManifest,
)
from ..persistence.batch_writer import AsyncBatchWriter, WriterStats
from ..persistence.repository import RawEventRepository
from ..settings import RecorderSettings
from .calendar import CaptureWindow


class StreamService(Protocol):
    async def run(self) -> None: ...

    async def stop(self) -> None: ...


class PollingService(Protocol):
    async def run(self, stop_event: asyncio.Event) -> None: ...


StreamFactory = Callable[
    [UUID, AsyncBatchWriter, SubscriptionManifest],
    Sequence[StreamService],
]
PollingFactory = Callable[[UUID, RawEventRepository, AsyncBatchWriter], Sequence[PollingService]]
_T = TypeVar("_T")


class RecorderSessionResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    ingest_session_id: UUID
    status: SessionStatus
    started_at: datetime
    ended_at: datetime
    writer_submitted: int
    writer_persisted: int
    writer_duplicates: int
    error_message: str | None = None


class RecorderService:
    def __init__(
        self,
        *,
        settings: RecorderSettings,
        repository: RawEventRepository,
        stream_factory: StreamFactory,
        polling_factory: PollingFactory | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._stream_factory = stream_factory
        self._polling_factory = polling_factory

    async def run_capture(
        self,
        window: CaptureWindow,
        *,
        external_stop_event: asyncio.Event | None = None,
    ) -> RecorderSessionResult:
        started_at = datetime.now(UTC)
        partial_capture = started_at > window.start_at
        session_id = uuid4()
        session = IngestSession(
            ingest_session_id=session_id,
            trading_date=window.trading_date,
            scheduled_start=window.start_at,
            scheduled_stop=window.stop_at,
            started_at=started_at,
            status=SessionStatus.RUNNING,
            configuration_hash=self._settings.configuration_hash,
            host_name=socket.gethostname(),
            process_id=os.getpid(),
            alpaca_feed="sip",
        )
        manifest = SubscriptionManifest(
            ingest_session_id=session_id,
            version=1,
            effective_at=started_at,
            wildcard_minute_bars=self._settings.wildcard_minute_bars,
            wildcard_trading_statuses=self._settings.wildcard_trading_statuses,
            tick_symbols=self._settings.tick_symbols,
            news_symbols=self._settings.news_symbols,
            configuration_hash=self._settings.configuration_hash,
        )

        writer = AsyncBatchWriter(
            self._repository,
            queue_maxsize=self._settings.queue_maxsize,
            batch_size=self._settings.batch_size,
            flush_interval_seconds=self._settings.flush_interval_seconds,
            enqueue_timeout_seconds=self._settings.enqueue_timeout_seconds,
        )
        streams: Sequence[StreamService] = ()
        pollers: Sequence[PollingService] = ()
        stream_tasks: list[asyncio.Task[None]] = []
        poller_tasks: list[asyncio.Task[None]] = []
        timer_task: asyncio.Task[None] | None = None
        external_task: asyncio.Task[bool] | None = None
        internal_stop = asyncio.Event()
        status = SessionStatus.FAILED
        errors: list[str] = []
        cancellation: asyncio.CancelledError | None = None

        await self._repository.open()
        await self._repository.create_session(session)
        try:
            await self._repository.save_manifest(manifest)
            await writer.start()
            # Persist the manifest event before opening any external stream. This
            # makes it the first replayable event for every successful session.
            await writer.submit_and_wait(
                RawEvent.create(
                    ingest_session_id=session_id,
                    connection_id=manifest.manifest_id,
                    source=RecorderSource.SYSTEM,
                    channel="subscription_manifest",
                    event_type=EventType.SUBSCRIPTION_MANIFEST,
                    event_timestamp=manifest.effective_at,
                    received_at=manifest.effective_at,
                    payload=manifest.model_dump(mode="python"),
                )
            )

            streams = self._stream_factory(session_id, writer, manifest)
            if not streams:
                raise RuntimeError("at least one required stream must be configured")
            pollers = (
                self._polling_factory(session_id, self._repository, writer)
                if self._polling_factory is not None
                else ()
            )
            stream_tasks = [
                asyncio.create_task(stream.run(), name=f"stream-{index}")
                for index, stream in enumerate(streams, start=1)
            ]
            poller_tasks = [
                asyncio.create_task(poller.run(internal_stop), name=f"poller-{index}")
                for index, poller in enumerate(pollers, start=1)
            ]

            timer_task = asyncio.create_task(
                self._sleep_until(window.stop_at), name="session-stop-timer"
            )
            external_task = (
                asyncio.create_task(external_stop_event.wait(), name="external-stop")
                if external_stop_event is not None
                else None
            )
            watched: list[asyncio.Task[object]] = [
                *stream_tasks,
                *poller_tasks,
                timer_task,
            ]
            if external_task is not None:
                watched.append(external_task)

            done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
            service_done = [task for task in done if task in stream_tasks or task in poller_tasks]
            if service_done:
                task = service_done[0]
                exception = task.exception()
                if exception is not None:
                    raise RuntimeError("a required ingestion service failed") from exception
                raise RuntimeError("a required ingestion service ended before the capture stop")

            status = SessionStatus.COMPLETED_PARTIAL if partial_capture else SessionStatus.COMPLETED
        except asyncio.CancelledError as exc:
            cancellation = exc
            errors.append("CancelledError: recorder task was cancelled")
            status = SessionStatus.FAILED
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            status = SessionStatus.FAILED
        finally:
            internal_stop.set()
            self._cancel_task(timer_task)
            self._cancel_task(external_task)
            auxiliary_tasks = [task for task in (timer_task, external_task) if task is not None]
            if auxiliary_tasks:
                await asyncio.gather(*auxiliary_tasks, return_exceptions=True)

            stop_errors = await self._stop_streams(streams)
            errors.extend(stop_errors)

            errors.extend(
                await self._settle_tasks(
                    stream_tasks,
                    label="stream tasks",
                )
            )
            errors.extend(
                await self._settle_tasks(
                    poller_tasks,
                    label="poller tasks",
                )
            )

            try:
                await asyncio.wait_for(
                    writer.stop(),
                    timeout=self._settings.shutdown_timeout_seconds,
                )
            except Exception as writer_exc:
                errors.append(f"writer shutdown failed: {writer_exc}")
                await writer.abort(writer_exc)

            if errors:
                status = SessionStatus.FAILED
            ended_at = datetime.now(UTC)
            error_message = self._format_errors(errors)
            try:
                await self._repository.finish_session(
                    session_id,
                    status=status,
                    ended_at=ended_at,
                    error_message=error_message,
                )
            finally:
                await self._repository.close()

        if cancellation is not None:
            raise cancellation

        return self._result(
            session_id=session_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            stats=writer.stats,
            error_message=error_message,
        )

    async def _stop_streams(self, streams: Sequence[StreamService]) -> list[str]:
        if not streams:
            return []
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(stream.stop() for stream in streams),
                    return_exceptions=True,
                ),
                timeout=self._settings.shutdown_timeout_seconds,
            )
        except TimeoutError:
            return [
                "stream stop timeout: one or more stream adapters did not stop "
                f"within {self._settings.shutdown_timeout_seconds} seconds"
            ]
        return [
            f"stream stop failed: {result}"
            for result in results
            if isinstance(result, BaseException)
        ]

    async def _settle_tasks(
        self,
        tasks: Sequence[asyncio.Task[None]],
        *,
        label: str,
    ) -> list[str]:
        if not tasks:
            return []
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._settings.shutdown_timeout_seconds,
            )
        except TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            return [
                f"{label} shutdown timeout after {self._settings.shutdown_timeout_seconds} seconds"
            ]
        return [
            f"{label} failed during shutdown: {result}"
            for result in results
            if isinstance(result, Exception)
        ]

    @staticmethod
    def _cancel_task(task: asyncio.Task[_T] | None) -> None:
        if task is not None and not task.done():
            task.cancel()

    @staticmethod
    async def _sleep_until(stop_at: datetime) -> None:
        delay = (stop_at - datetime.now(UTC)).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

    @staticmethod
    def _format_errors(errors: Sequence[str]) -> str | None:
        if not errors:
            return None
        return "; ".join(errors)[:4096]

    @staticmethod
    def _result(
        *,
        session_id: UUID,
        status: SessionStatus,
        started_at: datetime,
        ended_at: datetime,
        stats: WriterStats,
        error_message: str | None,
    ) -> RecorderSessionResult:
        return RecorderSessionResult(
            ingest_session_id=session_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            writer_submitted=stats.submitted,
            writer_persisted=stats.persisted,
            writer_duplicates=stats.duplicates,
            error_message=error_message,
        )
