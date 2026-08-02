"""Bounded, loss-intolerant asynchronous batch writer.

Every source uses this single writer so PostgreSQL ``ingest_seq`` reflects one
process-wide acceptance order. Low-rate sources can request a durability
acknowledgement before advancing their own checkpoints.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Final

from ..models import RawEvent, RawIngestFailure
from .repository import RawEventRepository

_STOP: Final = object()


@dataclass(slots=True)
class WriterStats:
    submitted: int = 0
    persisted: int = 0
    duplicates: int = 0
    batches: int = 0
    max_queue_depth: int = 0


@dataclass(slots=True)
class _QueuedEvent:
    event: RawEvent
    durable_future: asyncio.Future[None] | None = None


class AsyncBatchWriter:
    def __init__(
        self,
        repository: RawEventRepository,
        *,
        queue_maxsize: int,
        batch_size: int,
        flush_interval_seconds: float,
        enqueue_timeout_seconds: float,
    ) -> None:
        self._repository = repository
        self._queue: asyncio.Queue[_QueuedEvent | object] = asyncio.Queue(maxsize=queue_maxsize)
        self._batch_size = batch_size
        self._flush_interval_seconds = flush_interval_seconds
        self._enqueue_timeout_seconds = enqueue_timeout_seconds
        self._task: asyncio.Task[None] | None = None
        self._fatal_error: BaseException | None = None
        self.stats = WriterStats()

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("writer already started")
        self._task = asyncio.create_task(self._run(), name="daybreak-batch-writer")

    async def submit(self, event: RawEvent) -> None:
        await self._enqueue(_QueuedEvent(event=event))

    async def submit_and_wait(self, event: RawEvent) -> None:
        loop = asyncio.get_running_loop()
        durable = loop.create_future()
        await self._enqueue(_QueuedEvent(event=event, durable_future=durable))
        await durable

    async def submit_many_and_wait(self, events: list[RawEvent]) -> None:
        if not events:
            return
        loop = asyncio.get_running_loop()
        futures: list[asyncio.Future[None]] = []
        for event in events:
            durable = loop.create_future()
            futures.append(durable)
            await self._enqueue(_QueuedEvent(event=event, durable_future=durable))
        await asyncio.gather(*futures)

    async def _enqueue(self, item: _QueuedEvent) -> None:
        if self._fatal_error is not None:
            raise RuntimeError("writer has failed") from self._fatal_error
        if self._task is None:
            raise RuntimeError("writer has not been started")
        try:
            await asyncio.wait_for(
                self._queue.put(item),
                timeout=self._enqueue_timeout_seconds,
            )
        except TimeoutError as exc:
            raise RuntimeError("raw-event queue remained full; fail closed") from exc
        self.stats.submitted += 1
        self.stats.max_queue_depth = max(self.stats.max_queue_depth, self._queue.qsize())

    async def record_failure(self, failure: RawIngestFailure) -> None:
        if self._fatal_error is not None:
            raise RuntimeError("writer has failed") from self._fatal_error
        await self._repository.append_failure(failure)

    async def stop(self) -> None:
        if self._task is None:
            return
        task = self._task
        if task.done():
            try:
                await task
            finally:
                self._task = None
            if self._fatal_error is not None:
                raise RuntimeError("writer failed before shutdown") from self._fatal_error
            return
        await self._queue.put(_STOP)
        try:
            await task
        finally:
            self._task = None
        if self._fatal_error is not None:
            raise RuntimeError("writer failed during shutdown") from self._fatal_error

    async def abort(self, reason: BaseException | None = None) -> None:
        """Cancel the writer and fail every pending durability acknowledgement."""
        if reason is None:
            reason = RuntimeError("writer aborted")
        self._fatal_error = self._fatal_error or reason
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except BaseException:
            pass
        finally:
            self._task = None

    async def _flush(self, batch: list[_QueuedEvent]) -> None:
        if not batch:
            return
        try:
            result = await self._repository.append_batch([item.event for item in batch])
        except BaseException as exc:
            for item in batch:
                if item.durable_future is not None and not item.durable_future.done():
                    item.durable_future.set_exception(exc)
            batch.clear()
            raise
        self.stats.persisted += result.inserted
        self.stats.duplicates += result.duplicates
        self.stats.batches += 1
        for item in batch:
            if item.durable_future is not None and not item.durable_future.done():
                item.durable_future.set_result(None)
        batch.clear()

    async def _run(self) -> None:
        batch: list[_QueuedEvent] = []
        deadline = monotonic() + self._flush_interval_seconds
        try:
            while True:
                timeout = max(0.0, deadline - monotonic())
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                except TimeoutError:
                    await self._flush(batch)
                    deadline = monotonic() + self._flush_interval_seconds
                    continue

                if item is _STOP:
                    self._queue.task_done()
                    while not self._queue.empty():
                        queued = self._queue.get_nowait()
                        self._queue.task_done()
                        if queued is not _STOP:
                            batch.append(queued)  # type: ignore[arg-type]
                    await self._flush(batch)
                    return

                batch.append(item)  # type: ignore[arg-type]
                self._queue.task_done()
                if len(batch) >= self._batch_size:
                    await self._flush(batch)
                    deadline = monotonic() + self._flush_interval_seconds
        except BaseException as exc:
            self._fatal_error = self._fatal_error or exc
            terminal_error = self._fatal_error
            for queued in batch:
                future = queued.durable_future
                if future is not None and not future.done():
                    future.set_exception(terminal_error)
            batch.clear()
            while not self._queue.empty():
                queued = self._queue.get_nowait()
                self._queue.task_done()
                if isinstance(queued, _QueuedEvent):
                    future = queued.durable_future
                    if future is not None and not future.done():
                        future.set_exception(terminal_error)
            raise
