"""Deterministic ingest-sequence replay."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO
from uuid import UUID

from ..canonical import canonical_json_text, sha256_hex
from ..models import PersistedRawEvent, RawEvent
from ..persistence.repository import RawEventRepository

ReplayHandler = Callable[[PersistedRawEvent], Awaitable[None]]


@dataclass(slots=True)
class ReplayStats:
    event_count: int = 0
    first_ingest_seq: int | None = None
    last_ingest_seq: int | None = None
    first_received_at: str | None = None
    last_received_at: str | None = None


def verify_event_integrity(event: RawEvent) -> None:
    if sha256_hex(event.payload) != event.payload_sha256:
        raise ValueError(f"payload hash mismatch for event {event.event_id}")


class ReplayEngine:
    def __init__(self, repository: RawEventRepository) -> None:
        self._repository = repository

    async def replay(
        self,
        *,
        ingest_session_id: UUID,
        handler: ReplayHandler,
        after_ingest_seq: int = 0,
        speed: float = 0.0,
    ) -> ReplayStats:
        if speed < 0:
            raise ValueError("speed must be nonnegative")
        stats = ReplayStats()
        previous_received_at = None
        previous_seq = after_ingest_seq

        async for item in self._repository.iter_events(
            ingest_session_id=ingest_session_id,
            after_ingest_seq=after_ingest_seq,
        ):
            if item.ingest_seq <= previous_seq:
                raise ValueError("repository returned non-monotonic ingest sequence")
            previous_seq = item.ingest_seq
            verify_event_integrity(item.event)
            if speed > 0 and previous_received_at is not None:
                delay = (item.event.received_at - previous_received_at).total_seconds() / speed
                if delay > 0:
                    await asyncio.sleep(delay)
            await handler(item)
            previous_received_at = item.event.received_at

            stats.event_count += 1
            stats.first_ingest_seq = stats.first_ingest_seq or item.ingest_seq
            stats.last_ingest_seq = item.ingest_seq
            if stats.first_received_at is None:
                stats.first_received_at = item.event.received_at.isoformat()
            stats.last_received_at = item.event.received_at.isoformat()
        return stats


async def export_session_jsonl(
    repository: RawEventRepository,
    *,
    ingest_session_id: UUID,
    destination: Path,
    after_ingest_seq: int = 0,
) -> ReplayStats:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle: TextIO
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        engine = ReplayEngine(repository)

        async def write(item: PersistedRawEvent) -> None:
            record = {
                "ingest_seq": item.ingest_seq,
                "event": item.event.model_dump(mode="python"),
            }
            handle.write(canonical_json_text(record))
            handle.write("\n")

        return await engine.replay(
            ingest_session_id=ingest_session_id,
            handler=write,
            after_ingest_seq=after_ingest_seq,
            speed=0,
        )
