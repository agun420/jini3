from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol

from daybreak_risk.enums import ReservationStatus


class ReservationEventSink(Protocol):
    def append_status(
        self,
        reservation_id: str,
        status: ReservationStatus,
        event_timestamp: datetime,
        details: dict[str, object] | None = None,
    ) -> None: ...


class NullReservationEventSink:
    def append_status(
        self,
        reservation_id: str,
        status: ReservationStatus,
        event_timestamp: datetime,
        details: dict[str, object] | None = None,
    ) -> None:
        return None


class MemoryReservationEventSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, ReservationStatus, datetime, dict[str, object]]] = []

    def append_status(
        self,
        reservation_id: str,
        status: ReservationStatus,
        event_timestamp: datetime,
        details: dict[str, object] | None = None,
    ) -> None:
        self.events.append((reservation_id, status, event_timestamp, details or {}))


class PostgresReservationEventSink:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://")

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install project-daybreak[recorder] for PostgreSQL support") from exc
        return psycopg.connect(self._dsn)

    def append_status(
        self,
        reservation_id: str,
        status: ReservationStatus,
        event_timestamp: datetime,
        details: dict[str, object] | None = None,
    ) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (reservation_id,))
            cur.execute(
                "SELECT COALESCE(MAX(event_sequence),0)+1 "
                "FROM risk_reservation_events WHERE reservation_id=%s",
                (reservation_id,),
            )
            sequence = int(cur.fetchone()[0])
            payload = {
                "status": status.value,
                "event_timestamp": event_timestamp.isoformat(),
                "details": details or {},
            }
            cur.execute(
                """
                INSERT INTO risk_reservation_events (
                    reservation_id, event_sequence, status, event_timestamp, event_json
                ) VALUES (%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    reservation_id,
                    sequence,
                    status.value,
                    event_timestamp,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
