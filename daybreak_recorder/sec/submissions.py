"""Official SEC submissions API polling and filing-event persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..adapters.common import parse_timestamp
from ..canonical import sha256_hex
from ..models import EventType, RawEvent, RawIngestFailure, RecorderSource
from ..persistence.batch_writer import AsyncBatchWriter
from ..persistence.repository import RawEventRepository


class SecFilingRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    accession_number: str = Field(min_length=1)
    form: str = Field(min_length=1)
    filing_date: date
    report_date: date | None = None
    acceptance_timestamp: datetime
    primary_document: str | None = None
    primary_document_description: str | None = None
    items: str | None = None
    size: int | None = Field(default=None, ge=0)
    is_xbrl: bool | None = None
    is_inline_xbrl: bool | None = None
    raw_record: dict[str, Any]

    @field_validator("acceptance_timestamp")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acceptance_timestamp must be timezone-aware")
        return value.astimezone(UTC)


class AsyncRateLimiter:
    def __init__(self, rate_per_second: float) -> None:
        self._interval = 1.0 / rate_per_second
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            delay = self._next_allowed - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = loop.time()
            self._next_allowed = now + self._interval


def _column(recent: dict[str, Any], name: str) -> list[Any]:
    value = recent.get(name, [])
    return value if isinstance(value, list) else []


def _parse_optional_sec_bool(value: Any, *, field_name: str) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip() in {"0", "1"}:
        return value.strip() == "1"
    raise ValueError(f"{field_name} must be a SEC 0/1 Boolean value")


def parse_recent_filings(cik: str, payload: dict[str, Any]) -> list[SecFilingRecord]:
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        raise ValueError("SEC submissions response is missing filings object")
    recent = filings.get("recent")
    if not isinstance(recent, dict):
        raise ValueError("SEC submissions response is missing filings.recent object")

    accessions = _column(recent, "accessionNumber")
    records: list[SecFilingRecord] = []
    for index, accession in enumerate(accessions):
        if not isinstance(accession, str) or not accession.strip():
            raise ValueError(f"SEC accession at index {index} is missing or invalid")

        def get(name: str, *, _index: int = index) -> Any | None:
            values = _column(recent, name)
            return values[_index] if _index < len(values) else None

        raw_record = {
            name: values[index]
            for name, values in recent.items()
            if isinstance(values, list) and index < len(values)
        }
        filing_date_raw = get("filingDate")
        if not isinstance(filing_date_raw, str) or not filing_date_raw:
            raise ValueError(f"filingDate is missing for accession {accession}")
        filing_date = date.fromisoformat(filing_date_raw)

        acceptance_raw = get("acceptanceDateTime")
        if not isinstance(acceptance_raw, str) or not acceptance_raw:
            raise ValueError(f"acceptanceDateTime is missing for accession {accession}")
        acceptance = parse_timestamp(acceptance_raw)

        form_raw = get("form")
        if not isinstance(form_raw, str) or not form_raw.strip():
            raise ValueError(f"form is missing for accession {accession}")

        report_raw = get("reportDate")
        report_date = (
            date.fromisoformat(report_raw) if isinstance(report_raw, str) and report_raw else None
        )
        size_raw = get("size")
        if size_raw in (None, ""):
            size = None
        else:
            size = int(size_raw)
            if size < 0:
                raise ValueError(f"size is negative for accession {accession}")

        records.append(
            SecFilingRecord(
                cik=cik,
                accession_number=accession,
                form=form_raw.strip(),
                filing_date=filing_date,
                report_date=report_date,
                acceptance_timestamp=acceptance,
                primary_document=(str(get("primaryDocument")) if get("primaryDocument") else None),
                primary_document_description=(
                    str(get("primaryDocDescription")) if get("primaryDocDescription") else None
                ),
                items=(str(get("items")) if get("items") else None),
                size=size,
                is_xbrl=_parse_optional_sec_bool(get("isXBRL"), field_name="isXBRL"),
                is_inline_xbrl=_parse_optional_sec_bool(
                    get("isInlineXBRL"),
                    field_name="isInlineXBRL",
                ),
                raw_record=raw_record,
            )
        )
    return records


class SecSubmissionsPoller:
    def __init__(
        self,
        *,
        ingest_session_id: UUID,
        repository: RawEventRepository,
        writer: AsyncBatchWriter,
        ciks: tuple[str, ...],
        user_agent: str,
        poll_interval_seconds: float,
        bootstrap_lookback_hours: float,
        requests_per_second: float,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("SEC user agent is required")
        self._ingest_session_id = ingest_session_id
        self._repository = repository
        self._writer = writer
        self._ciks = ciks
        self._user_agent = user_agent
        self._poll_interval_seconds = poll_interval_seconds
        self._bootstrap_lookback_hours = bootstrap_lookback_hours
        self._limiter = AsyncRateLimiter(requests_per_second)
        self._timeout_seconds = timeout_seconds
        self._external_client = client
        self.connection_id = uuid4()

    async def run(self, stop_event: asyncio.Event) -> None:
        if not self._ciks:
            return
        while not stop_event.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._poll_interval_seconds,
                )
            except TimeoutError:
                continue

    async def poll_once(self) -> int:
        client = self._external_client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(
                timeout=self._timeout_seconds,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept-Encoding": "gzip, deflate",
                    "Accept": "application/json",
                },
            )
        inserted_total = 0
        try:
            for cik in self._ciks:
                inserted_total += await self._poll_cik(client, cik)
        finally:
            if owns_client:
                await client.aclose()
        return inserted_total

    async def _poll_cik(self, client: httpx.AsyncClient, cik: str) -> int:
        await self._limiter.wait()
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        response: httpx.Response | None = None
        payload: dict[str, Any] | None = None
        try:
            response = await client.get(url)
            received_at = datetime.now(UTC)
            response.raise_for_status()
            decoded = response.json()
            if not isinstance(decoded, dict):
                raise ValueError("SEC submissions response is not a JSON object")
            payload = decoded
            all_records = parse_recent_filings(cik, payload)
        except Exception as exc:
            received_at = datetime.now(UTC)
            if payload is not None:
                raw_failure_payload: Any = payload
            elif response is not None:
                raw_failure_payload = {
                    "url": url,
                    "status_code": response.status_code,
                    "response_text": response.text,
                }
            else:
                raw_failure_payload = {"url": url}
            await self._writer.record_failure(
                RawIngestFailure.create(
                    ingest_session_id=self._ingest_session_id,
                    connection_id=self.connection_id,
                    source=RecorderSource.SEC_EDGAR,
                    channel="submissions",
                    received_at=received_at,
                    error_type=type(exc).__qualname__,
                    error_message=str(exc) or repr(exc),
                    raw_payload=raw_failure_payload,
                )
            )
            raise

        seen = await self._repository.get_sec_seen_accessions(cik)
        if seen:
            records = [record for record in all_records if record.accession_number not in seen]
            accessions_to_mark = [record.accession_number for record in records]
        else:
            cutoff = received_at - timedelta(hours=self._bootstrap_lookback_hours)
            records = [record for record in all_records if record.acceptance_timestamp >= cutoff]
            # Seed the full current SEC window so older filings are not emitted on
            # every future poll, while retaining only the configured catalyst horizon.
            accessions_to_mark = [record.accession_number for record in all_records]

        records.sort(key=lambda record: (record.acceptance_timestamp, record.accession_number))
        symbols = tuple(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in payload.get("tickers", [])
                if isinstance(symbol, str) and symbol.strip()
            )
        )
        latest_source_timestamp = max(
            (record.acceptance_timestamp for record in all_records),
            default=received_at,
        )
        snapshot_hash = sha256_hex(payload)
        snapshot_event = RawEvent.create(
            ingest_session_id=self._ingest_session_id,
            connection_id=self.connection_id,
            source=RecorderSource.SEC_EDGAR,
            channel="submissions_snapshot",
            event_type=EventType.SEC_SUBMISSIONS_SNAPSHOT,
            event_timestamp=latest_source_timestamp,
            received_at=received_at,
            payload=payload,
            symbols=symbols,
            provider_event_id=f"CIK{cik}:{snapshot_hash}",
        )
        filing_events = [
            RawEvent.create(
                ingest_session_id=self._ingest_session_id,
                connection_id=self.connection_id,
                source=RecorderSource.SEC_EDGAR,
                channel="submissions",
                event_type=EventType.SEC_SUBMISSION,
                event_timestamp=record.acceptance_timestamp,
                received_at=received_at,
                payload={
                    "company_name": payload.get("name"),
                    "tickers": payload.get("tickers", []),
                    "exchanges": payload.get("exchanges", []),
                    **record.model_dump(mode="python"),
                },
                symbols=symbols,
                provider_event_id=record.accession_number,
            )
            for record in records
        ]
        # A full decoded provider snapshot precedes its derived accession events in
        # the same process-wide writer order. Unchanged snapshots with the same latest
        # filing timestamp dedupe through deterministic event identity.
        await self._writer.submit_many_and_wait([snapshot_event, *filing_events])
        await self._repository.mark_sec_accessions_seen(
            cik=cik,
            accession_numbers=accessions_to_mark,
            fetched_at=received_at,
        )
        return len(filing_events)
