from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Protocol

from .canonical import canonical_sha256
from .enums import LeadershipEventType
from .models import LeadershipEvent, LeadershipLease


class LeadershipRepository(Protocol):
    def acquire(
        self, session_id: str, holder_id: str, *, now: datetime, ttl_seconds: int
    ) -> LeadershipLease | None: ...
    def renew(
        self, lease: LeadershipLease, *, now: datetime, ttl_seconds: int
    ) -> LeadershipLease | None: ...
    def release(self, lease: LeadershipLease, *, now: datetime) -> None: ...
    def append_event(self, event: LeadershipEvent) -> None: ...


class MemoryLeadershipRepository:
    def __init__(self) -> None:
        self._leases: dict[str, LeadershipLease] = {}
        self.events: list[LeadershipEvent] = []
        self._token = 0
        self._lock = RLock()

    def acquire(
        self, session_id: str, holder_id: str, *, now: datetime, ttl_seconds: int
    ) -> LeadershipLease | None:
        now = now.astimezone(UTC)
        with self._lock:
            existing = self._leases.get(session_id)
            if existing is not None and existing.expires_at > now:
                return None
            self._token += 1
            lease = LeadershipLease(
                session_id=session_id,
                holder_id=holder_id,
                acquired_at=now,
                renewed_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
                fencing_token=self._token,
            )
            self._leases[session_id] = lease
            self._append_lease_event(lease, LeadershipEventType.ACQUIRED, now)
            return lease

    def renew(
        self, lease: LeadershipLease, *, now: datetime, ttl_seconds: int
    ) -> LeadershipLease | None:
        now = now.astimezone(UTC)
        with self._lock:
            current = self._leases.get(lease.session_id)
            if (
                current is None
                or current.holder_id != lease.holder_id
                or current.fencing_token != lease.fencing_token
            ):
                return None
            if current.expires_at <= now:
                return None
            renewed = current.model_copy(
                update={"renewed_at": now, "expires_at": now + timedelta(seconds=ttl_seconds)}
            )
            self._leases[lease.session_id] = renewed
            self._append_lease_event(renewed, LeadershipEventType.RENEWED, now)
            return renewed

    def release(self, lease: LeadershipLease, *, now: datetime) -> None:
        now = now.astimezone(UTC)
        with self._lock:
            current = self._leases.get(lease.session_id)
            if current is None:
                return
            if (
                current.holder_id == lease.holder_id
                and current.fencing_token == lease.fencing_token
            ):
                del self._leases[lease.session_id]
                self._append_lease_event(current, LeadershipEventType.RELEASED, now)

    def append_event(self, event: LeadershipEvent) -> None:
        self.events.append(event)

    def _append_lease_event(
        self, lease: LeadershipLease, event_type: LeadershipEventType, now: datetime
    ) -> None:
        core = {
            "session_id": lease.session_id,
            "holder_id": lease.holder_id,
            "event_type": event_type,
            "event_timestamp": now,
            "fencing_token": lease.fencing_token,
            "details": {"expires_at": lease.expires_at},
        }
        self.events.append(
            LeadershipEvent.model_validate({**core, "event_hash": canonical_sha256(core)})
        )


class PostgresLeadershipRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://")

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install project-daybreak[recorder] for PostgreSQL support") from exc
        return psycopg.connect(self._dsn)

    def acquire(
        self, session_id: str, holder_id: str, *, now: datetime, ttl_seconds: int
    ) -> LeadershipLease | None:
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestration_leases (
                    session_id, holder_id, acquired_at, renewed_at, expires_at,
                    fencing_token, active, released_at
                ) VALUES (%s,%s,%s,%s,%s,1,TRUE,NULL)
                ON CONFLICT (session_id) DO UPDATE SET
                    holder_id=EXCLUDED.holder_id,
                    acquired_at=EXCLUDED.acquired_at,
                    renewed_at=EXCLUDED.renewed_at,
                    expires_at=EXCLUDED.expires_at,
                    fencing_token=orchestration_leases.fencing_token+1,
                    active=TRUE,
                    released_at=NULL
                WHERE NOT orchestration_leases.active
                   OR orchestration_leases.expires_at <= EXCLUDED.renewed_at
                RETURNING session_id, holder_id, acquired_at, renewed_at, expires_at, fencing_token
                """,
                (session_id, holder_id, now, now, expires_at),
            )
            row = cur.fetchone()
        if row is None:
            return None
        lease = LeadershipLease(
            session_id=row[0],
            holder_id=row[1],
            acquired_at=row[2],
            renewed_at=row[3],
            expires_at=row[4],
            fencing_token=row[5],
        )
        self._save_lease_event(lease, LeadershipEventType.ACQUIRED, now)
        return lease

    def renew(
        self, lease: LeadershipLease, *, now: datetime, ttl_seconds: int
    ) -> LeadershipLease | None:
        expires_at = now + timedelta(seconds=ttl_seconds)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orchestration_leases
                SET renewed_at=%s, expires_at=%s
                WHERE session_id=%s AND holder_id=%s AND fencing_token=%s
                  AND active AND expires_at>%s
                RETURNING session_id, holder_id, acquired_at, renewed_at, expires_at, fencing_token
                """,
                (now, expires_at, lease.session_id, lease.holder_id, lease.fencing_token, now),
            )
            row = cur.fetchone()
        if row is None:
            return None
        renewed = LeadershipLease(
            session_id=row[0],
            holder_id=row[1],
            acquired_at=row[2],
            renewed_at=row[3],
            expires_at=row[4],
            fencing_token=row[5],
        )
        self._save_lease_event(renewed, LeadershipEventType.RENEWED, now)
        return renewed

    def release(self, lease: LeadershipLease, *, now: datetime) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orchestration_leases
                SET active=FALSE, released_at=%s, renewed_at=%s, expires_at=%s
                WHERE session_id=%s AND holder_id=%s AND fencing_token=%s AND active
                RETURNING session_id
                """,
                (now, now, now, lease.session_id, lease.holder_id, lease.fencing_token),
            )
            released = cur.fetchone()
        if released is not None:
            self._save_lease_event(lease, LeadershipEventType.RELEASED, now)

    def append_event(self, event: LeadershipEvent) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestration_leadership_events (
                    session_id, holder_id, event_type, event_timestamp,
                    fencing_token, event_hash, event_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (event_hash) DO NOTHING
                """,
                (
                    event.session_id,
                    event.holder_id,
                    event.event_type.value,
                    event.event_timestamp,
                    event.fencing_token,
                    event.event_hash,
                    json.dumps(event.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def _save_lease_event(
        self, lease: LeadershipLease, event_type: LeadershipEventType, now: datetime
    ) -> None:
        core = {
            "session_id": lease.session_id,
            "holder_id": lease.holder_id,
            "event_type": event_type,
            "event_timestamp": now,
            "fencing_token": lease.fencing_token,
            "details": {"expires_at": lease.expires_at},
        }
        self.append_event(
            LeadershipEvent.model_validate({**core, "event_hash": canonical_sha256(core)})
        )
