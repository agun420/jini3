"""Append-only raw-event repositories."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from ..canonical import canonical_json_text
from ..models import (
    AppendBatchResult,
    EventType,
    IngestSession,
    PersistedRawEvent,
    RawEvent,
    RawIngestFailure,
    RecorderSource,
    SessionStatus,
    SubscriptionManifest,
)


class RawEventRepository(Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def create_session(self, session: IngestSession) -> None: ...

    async def finish_session(
        self,
        ingest_session_id: UUID,
        *,
        status: SessionStatus,
        ended_at: datetime,
        error_message: str | None = None,
    ) -> None: ...

    async def save_manifest(self, manifest: SubscriptionManifest) -> None: ...

    async def append_batch(self, events: Sequence[RawEvent]) -> AppendBatchResult: ...

    async def append_failure(self, failure: RawIngestFailure) -> None: ...

    def iter_events(
        self,
        *,
        ingest_session_id: UUID,
        after_ingest_seq: int = 0,
    ) -> AsyncIterator[PersistedRawEvent]: ...

    async def get_sec_seen_accessions(self, cik: str) -> set[str]: ...

    async def mark_sec_accessions_seen(
        self,
        *,
        cik: str,
        accession_numbers: Sequence[str],
        fetched_at: datetime,
    ) -> None: ...


@dataclass(slots=True)
class _MemorySession:
    session: IngestSession
    status: SessionStatus
    ended_at: datetime | None = None
    error_message: str | None = None


class InMemoryRawEventRepository:
    """Deterministic repository used by unit tests and local dry runs."""

    def __init__(self) -> None:
        self._events: list[PersistedRawEvent] = []
        self._by_idempotency: dict[str, PersistedRawEvent] = {}
        self._failures: list[RawIngestFailure] = []
        self._manifests: list[SubscriptionManifest] = []
        self._sessions: dict[UUID, _MemorySession] = {}
        self._sec_seen: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def create_session(self, session: IngestSession) -> None:
        async with self._lock:
            if session.ingest_session_id in self._sessions:
                raise ValueError("ingest session already exists")
            self._sessions[session.ingest_session_id] = _MemorySession(
                session=session,
                status=session.status,
            )

    async def finish_session(
        self,
        ingest_session_id: UUID,
        *,
        status: SessionStatus,
        ended_at: datetime,
        error_message: str | None = None,
    ) -> None:
        async with self._lock:
            state = self._sessions[ingest_session_id]
            state.status = status
            state.ended_at = ended_at
            state.error_message = error_message

    async def save_manifest(self, manifest: SubscriptionManifest) -> None:
        async with self._lock:
            if any(
                existing.ingest_session_id == manifest.ingest_session_id
                and existing.version == manifest.version
                for existing in self._manifests
            ):
                raise ValueError("manifest version already exists for session")
            self._manifests.append(manifest)

    async def append_batch(self, events: Sequence[RawEvent]) -> AppendBatchResult:
        inserted = 0
        duplicates = 0
        async with self._lock:
            for event in events:
                if event.idempotency_key in self._by_idempotency:
                    duplicates += 1
                    continue
                persisted = PersistedRawEvent(
                    ingest_seq=len(self._events) + 1,
                    event=event,
                )
                self._events.append(persisted)
                self._by_idempotency[event.idempotency_key] = persisted
                inserted += 1
        return AppendBatchResult(
            attempted=len(events),
            inserted=inserted,
            duplicates=duplicates,
        )

    async def append_failure(self, failure: RawIngestFailure) -> None:
        async with self._lock:
            self._failures.append(failure)

    async def iter_events(
        self,
        *,
        ingest_session_id: UUID,
        after_ingest_seq: int = 0,
    ) -> AsyncIterator[PersistedRawEvent]:
        snapshot = [
            item
            for item in self._events
            if item.ingest_seq > after_ingest_seq
            and item.event.ingest_session_id == ingest_session_id
        ]
        for item in snapshot:
            yield item

    async def get_sec_seen_accessions(self, cik: str) -> set[str]:
        return set(self._sec_seen.get(cik, set()))

    async def mark_sec_accessions_seen(
        self,
        *,
        cik: str,
        accession_numbers: Sequence[str],
        fetched_at: datetime,
    ) -> None:
        del fetched_at
        self._sec_seen.setdefault(cik, set()).update(accession_numbers)

    @property
    def events(self) -> tuple[PersistedRawEvent, ...]:
        return tuple(self._events)

    @property
    def failures(self) -> tuple[RawIngestFailure, ...]:
        return tuple(self._failures)

    @property
    def manifests(self) -> tuple[SubscriptionManifest, ...]:
        return tuple(self._manifests)


class PostgresRawEventRepository:
    """Psycopg 3 append-only repository.

    Imports are intentionally lazy so contract-only tooling can run without the
    production PostgreSQL driver installed.
    """

    def __init__(self, database_url: str, *, min_size: int = 1, max_size: int = 4) -> None:
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://")
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Any | None = None

    async def open(self) -> None:
        try:
            from psycopg_pool import AsyncConnectionPool
        except ImportError as exc:  # pragma: no cover - depends on production extra
            raise RuntimeError("Install the recorder extra: pip install -e '.[recorder]'") from exc
        self._pool = AsyncConnectionPool(
            conninfo=self._database_url,
            min_size=self._min_size,
            max_size=self._max_size,
            open=False,
            kwargs={"autocommit": False},
        )
        await self._pool.open()
        await self._pool.wait()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _require_pool(self) -> Any:
        if self._pool is None:
            raise RuntimeError("repository has not been opened")
        return self._pool

    async def create_session(self, session: IngestSession) -> None:
        sql = """
        INSERT INTO ingest_sessions (
            ingest_session_id, trading_date, scheduled_start, scheduled_stop,
            started_at, status, configuration_hash, host_name, process_id,
            alpaca_feed, error_message
        ) VALUES (
            %(ingest_session_id)s, %(trading_date)s, %(scheduled_start)s,
            %(scheduled_stop)s, %(started_at)s, %(status)s,
            %(configuration_hash)s, %(host_name)s, %(process_id)s,
            %(alpaca_feed)s, %(error_message)s
        )
        """
        values = session.model_dump(mode="python")
        values["status"] = session.status.value
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, values)
            await conn.commit()

    async def finish_session(
        self,
        ingest_session_id: UUID,
        *,
        status: SessionStatus,
        ended_at: datetime,
        error_message: str | None = None,
    ) -> None:
        sql = """
        UPDATE ingest_sessions
        SET status = %(status)s, ended_at = %(ended_at)s,
            error_message = %(error_message)s
        WHERE ingest_session_id = %(ingest_session_id)s
        """
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    sql,
                    {
                        "ingest_session_id": ingest_session_id,
                        "status": status.value,
                        "ended_at": ended_at,
                        "error_message": error_message,
                    },
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("ingest session finalization affected no row")
            await conn.commit()

    async def save_manifest(self, manifest: SubscriptionManifest) -> None:
        sql = """
        INSERT INTO subscription_manifests (
            manifest_id, ingest_session_id, version, effective_at,
            feed, manifest, configuration_hash
        ) VALUES (
            %(manifest_id)s, %(ingest_session_id)s, %(version)s,
            %(effective_at)s, %(feed)s, %(manifest)s::jsonb,
            %(configuration_hash)s
        )
        """
        data = manifest.model_dump(mode="json")
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    sql,
                    {
                        "manifest_id": manifest.manifest_id,
                        "ingest_session_id": manifest.ingest_session_id,
                        "version": manifest.version,
                        "effective_at": manifest.effective_at,
                        "feed": manifest.feed,
                        "manifest": canonical_json_text(data),
                        "configuration_hash": manifest.configuration_hash,
                    },
                )
            await conn.commit()

    async def append_batch(self, events: Sequence[RawEvent]) -> AppendBatchResult:
        if not events:
            return AppendBatchResult(attempted=0, inserted=0, duplicates=0)

        sql = """
        INSERT INTO raw_events (
            event_id, ingest_session_id, connection_id, source, channel,
            event_type, symbol, symbols, provider_event_id, event_timestamp,
            received_at, trading_date, sequence_hint, payload,
            payload_sha256, idempotency_key, schema_version
        ) VALUES (
            %(event_id)s, %(ingest_session_id)s, %(connection_id)s,
            %(source)s, %(channel)s, %(event_type)s, %(symbol)s,
            %(symbols)s, %(provider_event_id)s, %(event_timestamp)s,
            %(received_at)s, %(trading_date)s, %(sequence_hint)s,
            %(payload)s::jsonb, %(payload_sha256)s, %(idempotency_key)s,
            %(schema_version)s
        ) ON CONFLICT (idempotency_key) DO NOTHING
        """
        rows: list[dict[str, Any]] = []
        for event in events:
            rows.append(
                {
                    "event_id": event.event_id,
                    "ingest_session_id": event.ingest_session_id,
                    "connection_id": event.connection_id,
                    "source": event.source.value,
                    "channel": event.channel,
                    "event_type": event.event_type.value,
                    "symbol": event.symbol,
                    "symbols": list(event.symbols),
                    "provider_event_id": event.provider_event_id,
                    "event_timestamp": event.event_timestamp,
                    "received_at": event.received_at,
                    "trading_date": event.trading_date,
                    "sequence_hint": event.sequence_hint,
                    "payload": canonical_json_text(event.payload),
                    "payload_sha256": event.payload_sha256,
                    "idempotency_key": event.idempotency_key,
                    "schema_version": event.schema_version,
                }
            )

        pool = self._require_pool()
        inserted = 0
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                for row in rows:
                    await cursor.execute(sql, row)
                    inserted += max(cursor.rowcount, 0)
            await conn.commit()
        return AppendBatchResult(
            attempted=len(events),
            inserted=inserted,
            duplicates=len(events) - inserted,
        )

    async def append_failure(self, failure: RawIngestFailure) -> None:
        sql = """
        INSERT INTO raw_ingest_failures (
            failure_id, ingest_session_id, connection_id, source, channel,
            received_at, error_type, error_message, raw_payload,
            raw_payload_sha256, schema_version
        ) VALUES (
            %(failure_id)s, %(ingest_session_id)s, %(connection_id)s,
            %(source)s, %(channel)s, %(received_at)s, %(error_type)s,
            %(error_message)s, %(raw_payload)s::jsonb,
            %(raw_payload_sha256)s, %(schema_version)s
        )
        """
        raw_json = (
            canonical_json_text(failure.raw_payload) if failure.raw_payload is not None else None
        )
        values = failure.model_dump(mode="python")
        values["source"] = failure.source.value
        values["raw_payload"] = raw_json
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, values)
            await conn.commit()

    async def iter_events(
        self,
        *,
        ingest_session_id: UUID,
        after_ingest_seq: int = 0,
    ) -> AsyncIterator[PersistedRawEvent]:
        sql = """
        SELECT ingest_seq, event_id, ingest_session_id, connection_id,
               source, channel, event_type, symbol, symbols,
               provider_event_id, event_timestamp, received_at, trading_date,
               sequence_hint, payload, payload_sha256, idempotency_key,
               schema_version
        FROM raw_events
        WHERE ingest_session_id = %(ingest_session_id)s
          AND ingest_seq > %(after_ingest_seq)s
        ORDER BY ingest_seq ASC
        """
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    sql,
                    {
                        "ingest_session_id": ingest_session_id,
                        "after_ingest_seq": after_ingest_seq,
                    },
                )
                async for row in cursor:
                    (
                        ingest_seq,
                        event_id,
                        session_id,
                        connection_id,
                        source,
                        channel,
                        event_type,
                        symbol,
                        symbols,
                        provider_event_id,
                        event_timestamp,
                        received_at,
                        trading_date,
                        sequence_hint,
                        payload,
                        payload_sha256,
                        idempotency_key,
                        schema_version,
                    ) = row
                    event = RawEvent.model_validate(
                        {
                            "schema_version": schema_version,
                            "event_id": event_id,
                            "ingest_session_id": session_id,
                            "connection_id": connection_id,
                            "source": RecorderSource(source),
                            "channel": channel,
                            "event_type": EventType(event_type),
                            "symbol": symbol,
                            "symbols": tuple(symbols or ()),
                            "provider_event_id": provider_event_id,
                            "event_timestamp": event_timestamp,
                            "received_at": received_at,
                            "trading_date": trading_date,
                            "sequence_hint": sequence_hint,
                            "payload": payload,
                            "payload_sha256": payload_sha256,
                            "idempotency_key": idempotency_key,
                        }
                    )
                    yield PersistedRawEvent(ingest_seq=ingest_seq, event=event)

    async def get_sec_seen_accessions(self, cik: str) -> set[str]:
        sql = "SELECT accession_number FROM sec_seen_accessions WHERE cik = %(cik)s"
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, {"cik": cik})
                rows = await cursor.fetchall()
        return {row[0] for row in rows}

    async def mark_sec_accessions_seen(
        self,
        *,
        cik: str,
        accession_numbers: Sequence[str],
        fetched_at: datetime,
    ) -> None:
        if not accession_numbers:
            return
        sql = """
        INSERT INTO sec_seen_accessions (cik, accession_number, first_seen_at)
        VALUES (%(cik)s, %(accession_number)s, %(first_seen_at)s)
        ON CONFLICT (cik, accession_number) DO NOTHING
        """
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                for accession in accession_numbers:
                    await cursor.execute(
                        sql,
                        {
                            "cik": cik,
                            "accession_number": accession,
                            "first_seen_at": fetched_at,
                        },
                    )
            await conn.commit()
