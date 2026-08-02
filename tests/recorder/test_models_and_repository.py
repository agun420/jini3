from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from daybreak_recorder.models import EventType, RawEvent, RecorderSource
from daybreak_recorder.persistence.repository import InMemoryRawEventRepository


def make_event(*, provider_event_id: str = "123") -> RawEvent:
    timestamp = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    return RawEvent.create(
        ingest_session_id=uuid4(),
        connection_id=uuid4(),
        source=RecorderSource.ALPACA_SIP,
        channel="trades",
        event_type=EventType.TRADE,
        event_timestamp=timestamp,
        received_at=timestamp,
        payload={"T": "t", "S": "AAPL", "p": 210.25, "i": 123},
        symbols=("AAPL",),
        provider_event_id=provider_event_id,
    )


def test_raw_event_identity_is_deterministic() -> None:
    session_id = uuid4()
    connection_id = uuid4()
    timestamp = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    kwargs = dict(
        ingest_session_id=session_id,
        connection_id=connection_id,
        source=RecorderSource.ALPACA_SIP,
        channel="trades",
        event_type=EventType.TRADE,
        event_timestamp=timestamp,
        received_at=timestamp,
        payload={"T": "t", "S": "AAPL", "p": 210.25, "i": 123},
        symbols=("AAPL",),
        provider_event_id="123",
    )
    first = RawEvent.create(**kwargs)
    second = RawEvent.create(**kwargs)
    assert first.event_id == second.event_id
    assert first.idempotency_key == second.idempotency_key
    assert first.payload_sha256 == second.payload_sha256


def test_raw_event_rejects_tampered_payload() -> None:
    event = make_event()
    data = event.model_dump(mode="python")
    data["payload"] = {**data["payload"], "p": 999.0}
    with pytest.raises(ValidationError, match="payload_sha256"):
        RawEvent.model_validate(data)


@pytest.mark.asyncio
async def test_repository_deduplicates_exact_event() -> None:
    repository = InMemoryRawEventRepository()
    event = make_event()
    result = await repository.append_batch([event, event])
    assert result.attempted == 2
    assert result.inserted == 1
    assert result.duplicates == 1
    assert len(repository.events) == 1


def test_identical_provider_event_is_scoped_to_ingest_session() -> None:
    timestamp = datetime(2026, 7, 31, 13, 30, tzinfo=UTC)
    common = {
        "connection_id": uuid4(),
        "source": RecorderSource.ALPACA_SIP,
        "channel": "trades",
        "event_type": EventType.TRADE,
        "event_timestamp": timestamp,
        "received_at": timestamp,
        "payload": {"S": "AAPL", "i": 42, "p": 200.0},
        "symbols": ("AAPL",),
        "provider_event_id": "42",
    }
    first = RawEvent.create(ingest_session_id=uuid4(), **common)
    second = RawEvent.create(ingest_session_id=uuid4(), **common)

    assert first.idempotency_key != second.idempotency_key
    assert first.event_id != second.event_id
