"""Append-only persistence for immutable feature contexts and snapshots."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Protocol

from .canonical import canonical_json_text, canonical_sha256
from .models import FeatureContext, FeatureSnapshot


class FeatureArtifactRepository(Protocol):
    async def save_context(self, context: FeatureContext) -> str: ...
    async def get_context(self, context_hash: str) -> FeatureContext | None: ...
    async def save_snapshot(self, snapshot: FeatureSnapshot) -> None: ...
    async def get_snapshot(self, snapshot_id: str) -> FeatureSnapshot | None: ...


class InMemoryFeatureArtifactRepository:
    def __init__(self) -> None:
        self._contexts: dict[str, FeatureContext] = {}
        self._snapshots: dict[str, FeatureSnapshot] = {}
        self._lock = asyncio.Lock()

    async def save_context(self, context: FeatureContext) -> str:
        context_hash = canonical_sha256(context)
        async with self._lock:
            existing = self._contexts.get(context_hash)
            if existing is not None and canonical_json_text(existing) != canonical_json_text(
                context
            ):
                raise RuntimeError("feature context hash collision")
            self._contexts[context_hash] = context
        return context_hash

    async def get_context(self, context_hash: str) -> FeatureContext | None:
        return self._contexts.get(context_hash)

    async def save_snapshot(self, snapshot: FeatureSnapshot) -> None:
        async with self._lock:
            existing = self._snapshots.get(snapshot.snapshot_id)
            if existing is not None and canonical_json_text(existing) != canonical_json_text(
                snapshot
            ):
                raise RuntimeError("feature snapshot id collision")
            self._snapshots[snapshot.snapshot_id] = snapshot

    async def get_snapshot(self, snapshot_id: str) -> FeatureSnapshot | None:
        return self._snapshots.get(snapshot_id)


class PostgresFeatureArtifactRepository:
    """Psycopg 3 persistence with lazy imports and immutable inserts."""

    def __init__(self, database_url: str, *, min_size: int = 1, max_size: int = 4) -> None:
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://")
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Any | None = None

    async def open(self) -> None:
        try:
            from psycopg_pool import AsyncConnectionPool
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Install recorder dependencies to use PostgreSQL persistence"
            ) from exc
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

    async def save_context(self, context: FeatureContext) -> str:
        context_hash = canonical_sha256(context)
        payload = canonical_json_text(context)
        sql = """
        INSERT INTO feature_contexts (
            context_hash, trading_date, evaluation_timestamp, payload_timestamp,
            context_json, engine_version, configuration_hash
        ) VALUES (
            %(context_hash)s, %(trading_date)s, %(evaluation_timestamp)s,
            %(payload_timestamp)s, %(context_json)s::jsonb, %(engine_version)s,
            %(configuration_hash)s
        ) ON CONFLICT (context_hash) DO NOTHING
        """
        values = {
            "context_hash": context_hash,
            "trading_date": context.payload_timestamp.date(),
            "evaluation_timestamp": context.evaluation_timestamp,
            "payload_timestamp": context.payload_timestamp,
            "context_json": payload,
            "engine_version": context.config.engine_version,
            "configuration_hash": canonical_sha256(context.config),
        }
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, values)
                if cursor.rowcount == 0:
                    await cursor.execute(
                        "SELECT context_json::text FROM feature_contexts WHERE context_hash = %s",
                        (context_hash,),
                    )
                    row = await cursor.fetchone()
                    if (
                        row is None
                        or canonical_json_text(FeatureContext.model_validate_json(row[0]))
                        != payload
                    ):
                        raise RuntimeError("feature context hash collision or persistence mismatch")
            await conn.commit()
        return context_hash

    async def get_context(self, context_hash: str) -> FeatureContext | None:
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT context_json::text FROM feature_contexts WHERE context_hash = %s",
                    (context_hash,),
                )
                row = await cursor.fetchone()
        return None if row is None else FeatureContext.model_validate_json(row[0])

    async def save_snapshot(self, snapshot: FeatureSnapshot) -> None:
        sql = """
        INSERT INTO feature_snapshots (
            snapshot_id, context_hash, trading_date, payload_timestamp, payload_hash,
            feature_hash, audit_hash, configuration_hash, snapshot_json, payload_json,
            module_manifest
        ) VALUES (
            %(snapshot_id)s, %(context_hash)s, %(trading_date)s, %(payload_timestamp)s,
            %(payload_hash)s, %(feature_hash)s, %(audit_hash)s, %(configuration_hash)s,
            %(snapshot_json)s::jsonb, %(payload_json)s::jsonb,
            %(module_manifest)s::jsonb
        ) ON CONFLICT (snapshot_id) DO NOTHING
        """
        snapshot_json = canonical_json_text(snapshot)
        values = {
            "snapshot_id": snapshot.snapshot_id,
            "context_hash": snapshot.context_hash,
            "trading_date": datetime.fromisoformat(
                snapshot.payload.payload_timestamp.replace("Z", "+00:00")
            ).date(),
            "payload_timestamp": datetime.fromisoformat(
                snapshot.payload.payload_timestamp.replace("Z", "+00:00")
            ),
            "payload_hash": snapshot.payload_hash,
            "feature_hash": snapshot.feature_hash,
            "audit_hash": snapshot.audit_hash,
            "configuration_hash": snapshot.configuration_hash,
            "snapshot_json": snapshot_json,
            "payload_json": canonical_json_text(snapshot.payload),
            "module_manifest": canonical_json_text(snapshot.module_manifest),
        }
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(sql, values)
                if cursor.rowcount == 0:
                    await cursor.execute(
                        "SELECT snapshot_json::text FROM feature_snapshots WHERE snapshot_id = %s",
                        (snapshot.snapshot_id,),
                    )
                    row = await cursor.fetchone()
                    if (
                        row is None
                        or canonical_json_text(FeatureSnapshot.model_validate_json(row[0]))
                        != snapshot_json
                    ):
                        raise RuntimeError("feature snapshot id collision or persistence mismatch")
            await conn.commit()

    async def get_snapshot(self, snapshot_id: str) -> FeatureSnapshot | None:
        pool = self._require_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT snapshot_json::text FROM feature_snapshots WHERE snapshot_id = %s",
                    (snapshot_id,),
                )
                row = await cursor.fetchone()
        return None if row is None else FeatureSnapshot.model_validate_json(row[0])
