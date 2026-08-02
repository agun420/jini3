from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from daybreak_recorder.models import EventType, RawEvent, RecorderSource
from daybreak_recorder.persistence.repository import InMemoryRawEventRepository
from daybreak_recorder.replay.engine import ReplayEngine


@pytest.mark.asyncio
async def test_replay_uses_global_ingest_sequence() -> None:
    repository = InMemoryRawEventRepository()
    session_id = uuid4()
    connection_id = uuid4()
    base = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    events = [
        RawEvent.create(
            ingest_session_id=session_id,
            connection_id=connection_id,
            source=RecorderSource.ALPACA_SIP,
            channel="minute_bars",
            event_type=EventType.MINUTE_BAR,
            event_timestamp=base + timedelta(seconds=offset),
            received_at=base + timedelta(seconds=offset),
            payload={"S": "AAPL", "offset": offset},
            symbols=("AAPL",),
        )
        for offset in (2, 0, 1)
    ]
    await repository.append_batch(events)
    seen: list[int] = []

    async def handler(item):
        seen.append(item.event.payload["offset"])

    stats = await ReplayEngine(repository).replay(
        ingest_session_id=session_id,
        handler=handler,
    )
    assert seen == [2, 0, 1]
    assert stats.event_count == 3
    assert stats.first_ingest_seq == 1
    assert stats.last_ingest_seq == 3
