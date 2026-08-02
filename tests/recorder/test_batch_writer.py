from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from daybreak_recorder.models import EventType, RawEvent, RecorderSource
from daybreak_recorder.persistence.batch_writer import AsyncBatchWriter
from daybreak_recorder.persistence.repository import InMemoryRawEventRepository


def event(number: int) -> RawEvent:
    timestamp = datetime(2026, 7, 31, 12, 0, number, tzinfo=UTC)
    return RawEvent.create(
        ingest_session_id=SESSION_ID,
        connection_id=CONNECTION_ID,
        source=RecorderSource.ALPACA_SIP,
        channel="quotes",
        event_type=EventType.QUOTE,
        event_timestamp=timestamp,
        received_at=timestamp,
        payload={"S": "MSFT", "bp": 500 + number, "ap": 501 + number},
        symbols=("MSFT",),
    )


SESSION_ID = uuid4()
CONNECTION_ID = uuid4()


@pytest.mark.asyncio
async def test_batch_writer_flushes_and_counts_duplicates() -> None:
    repository = InMemoryRawEventRepository()
    writer = AsyncBatchWriter(
        repository,
        queue_maxsize=10,
        batch_size=2,
        flush_interval_seconds=0.01,
        enqueue_timeout_seconds=1,
    )
    await writer.start()
    first = event(1)
    await writer.submit(first)
    await writer.submit(event(2))
    await writer.submit(first)
    await writer.stop()

    assert writer.stats.submitted == 3
    assert writer.stats.persisted == 2
    assert writer.stats.duplicates == 1
    assert writer.stats.batches >= 2


@pytest.mark.asyncio
async def test_submit_and_wait_preserves_single_writer_acceptance_order() -> None:
    repository = InMemoryRawEventRepository()
    writer = AsyncBatchWriter(
        repository,
        queue_maxsize=10,
        batch_size=10,
        flush_interval_seconds=0.01,
        enqueue_timeout_seconds=1,
    )
    await writer.start()
    await writer.submit(event(3))
    await writer.submit_and_wait(event(4))
    await writer.submit(event(5))
    await writer.stop()

    assert [item.event.payload["bp"] for item in repository.events] == [503, 504, 505]
    assert [item.ingest_seq for item in repository.events] == [1, 2, 3]
