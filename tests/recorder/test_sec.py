from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from daybreak_recorder.persistence.batch_writer import AsyncBatchWriter
from daybreak_recorder.persistence.repository import InMemoryRawEventRepository
from daybreak_recorder.sec.submissions import SecSubmissionsPoller, parse_recent_filings

# Computed relative to "now" rather than hardcoded: the poller's bootstrap path
# drops any filing older than `bootstrap_lookback_hours` (see
# SecSubmissionsPoller.poll_once), so a fixed past timestamp eventually ages out
# of that window and starts failing the suite on whatever day it crosses it.
_FILING_1 = datetime.now(UTC) - timedelta(hours=2)
_FILING_2 = _FILING_1 + timedelta(minutes=1)

SEC_PAYLOAD = {
    "name": "Example Corp",
    "tickers": ["EXMP"],
    "exchanges": ["Nasdaq"],
    "filings": {
        "recent": {
            "accessionNumber": ["0000000000-26-000001", "0000000000-26-000002"],
            "filingDate": [_FILING_1.date().isoformat(), _FILING_2.date().isoformat()],
            "reportDate": [_FILING_1.date().isoformat(), _FILING_2.date().isoformat()],
            "acceptanceDateTime": [
                _FILING_1.strftime("%Y-%m-%dT%H:%M:%S.123456789Z"),
                _FILING_2.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ],
            "form": ["8-K", "8-K"],
            "primaryDocument": ["exmp-8k.htm", "exmp2-8k.htm"],
            "primaryDocDescription": ["Current report", "Current report"],
            "items": ["1.01", "2.02"],
            "size": [1234, 2345],
            "isXBRL": [1, 1],
            "isInlineXBRL": [1, 1],
        }
    },
}


def test_parse_recent_filings_preserves_accessions_and_time_order() -> None:
    records = parse_recent_filings("0000000000", SEC_PAYLOAD)
    assert [record.accession_number for record in records] == [
        "0000000000-26-000001",
        "0000000000-26-000002",
    ]
    assert records[0].acceptance_timestamp.microsecond == 123456
    assert records[0].form == "8-K"
    assert records[0].raw_record["accessionNumber"] == "0000000000-26-000001"


@pytest.mark.asyncio
async def test_sec_poller_persists_each_accession_once() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("CIK0000000000.json")
        return httpx.Response(200, json=SEC_PAYLOAD)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    repository = InMemoryRawEventRepository()
    writer = AsyncBatchWriter(
        repository,
        queue_maxsize=100,
        batch_size=10,
        flush_interval_seconds=0.01,
        enqueue_timeout_seconds=1,
    )
    await writer.start()
    poller = SecSubmissionsPoller(
        ingest_session_id=uuid4(),
        repository=repository,
        writer=writer,
        ciks=("0000000000",),
        user_agent="Daybreak test test@example.com",
        poll_interval_seconds=60,
        bootstrap_lookback_hours=96,
        requests_per_second=10,
        timeout_seconds=5,
        client=client,
    )
    try:
        assert await poller.poll_once() == 2
        assert await poller.poll_once() == 0
    finally:
        await writer.stop()
        await client.aclose()

    # The exact decoded snapshot and unseen accession events are persisted once;
    # the unchanged second snapshot dedupes deterministically.
    assert len(repository.events) == 3
    assert repository.events[0].event.event_type.value == "sec_submissions_snapshot"
    assert repository.events[1].event.provider_event_id == "0000000000-26-000001"
    assert repository.events[2].event.provider_event_id == "0000000000-26-000002"
    assert all(item.event.symbol == "EXMP" for item in repository.events)


@pytest.mark.asyncio
async def test_sec_malformed_response_is_persisted_as_raw_failure() -> None:
    malformed = {
        "name": "Broken Corp",
        "tickers": ["BRKN"],
        "filings": {
            "recent": {
                "accessionNumber": ["0000000000-26-999999"],
                "filingDate": ["2026-07-31"],
                "acceptanceDateTime": [None],
                "form": ["8-K"],
            }
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=malformed)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    repository = InMemoryRawEventRepository()
    writer = AsyncBatchWriter(
        repository,
        queue_maxsize=100,
        batch_size=10,
        flush_interval_seconds=0.01,
        enqueue_timeout_seconds=1,
    )
    await writer.start()
    poller = SecSubmissionsPoller(
        ingest_session_id=uuid4(),
        repository=repository,
        writer=writer,
        ciks=("0000000000",),
        user_agent="Daybreak test test@example.com",
        poll_interval_seconds=60,
        bootstrap_lookback_hours=96,
        requests_per_second=10,
        timeout_seconds=5,
        client=client,
    )
    try:
        with pytest.raises(ValueError, match="acceptanceDateTime"):
            await poller.poll_once()
    finally:
        await writer.stop()
        await client.aclose()

    assert len(repository.failures) == 1
    assert repository.failures[0].raw_payload == malformed
    assert repository.events == ()
