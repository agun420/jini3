"""Shared adapter normalization helpers."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from ..models import EventType, RawEvent, RawIngestFailure, RecorderSource
from ..persistence.batch_writer import AsyncBatchWriter

_FRACTION_RE = re.compile(
    r"^(?P<prefix>.*T\d{2}:\d{2}:\d{2})\.(?P<fraction>\d+)(?P<suffix>Z|[+-]\d{2}:\d{2})$"
)


def _timestamp_like_to_text(value: Any) -> str | None:
    """Preserve provider nanosecond timestamps as ISO-8601 text when possible."""
    seconds = getattr(value, "seconds", None)
    nanoseconds = getattr(value, "nanoseconds", None)
    if isinstance(seconds, int) and isinstance(nanoseconds, int):
        if not 0 <= nanoseconds < 1_000_000_000:
            raise ValueError("provider timestamp nanoseconds are outside [0, 1e9)")
        base = datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
        return f"{base}.{nanoseconds:09d}Z"
    converter = getattr(value, "to_datetime", None)
    if callable(converter):
        converted = converter()
        if not isinstance(converted, datetime):
            raise TypeError("provider to_datetime() did not return datetime")
        if converted.tzinfo is None or converted.utcoffset() is None:
            converted = converted.replace(tzinfo=UTC)
        return converted.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return None


def _normalize_provider_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    timestamp_text = _timestamp_like_to_text(value)
    if timestamp_text is not None:
        return timestamp_text
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider datetime is timezone-naive")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, Enum):
        return _normalize_provider_value(value.value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_provider_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_provider_value(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return {"__daybreak_bytes_hex__": bytes(value).hex()}
    if hasattr(value, "model_dump"):
        return _normalize_provider_value(value.model_dump(mode="python"))
    raise TypeError(f"unsupported provider payload value: {type(value)!r}")


def model_to_payload(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        normalized = _normalize_provider_value(message)
    elif hasattr(message, "model_dump"):
        normalized = _normalize_provider_value(message.model_dump(mode="python"))
    elif hasattr(message, "_raw_data") and isinstance(message._raw_data, dict):
        normalized = _normalize_provider_value(message._raw_data)
    else:
        raise TypeError(f"unsupported provider message type: {type(message)!r}")
    if not isinstance(normalized, dict):
        raise TypeError("provider message did not normalize to a dictionary")
    return normalized


def parse_timestamp(value: Any, *, fallback: datetime | None = None) -> datetime:
    timestamp_text = _timestamp_like_to_text(value)
    if timestamp_text is not None:
        return parse_timestamp(timestamp_text, fallback=fallback)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider timestamp is timezone-naive")
        return value.astimezone(UTC)
    if isinstance(value, str):
        text = value.strip()
        match = _FRACTION_RE.match(text)
        if match and len(match.group("fraction")) > 6:
            text = match.group("prefix") + "." + match.group("fraction")[:6] + match.group("suffix")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("provider timestamp is timezone-naive")
        return parsed.astimezone(UTC)
    if value is None and fallback is not None:
        return fallback.astimezone(UTC)
    if value is None:
        raise ValueError("provider timestamp is missing")
    raise TypeError(f"unsupported provider timestamp type: {type(value)!r}")


def extract_event_timestamp(payload: dict[str, Any], *, received_at: datetime) -> datetime:
    for key in ("t", "timestamp", "created_at", "updated_at", "acceptanceDateTime"):
        if key in payload and payload[key] is not None:
            return parse_timestamp(payload[key], fallback=received_at)
    order = payload.get("order")
    if isinstance(order, dict):
        for key in ("updated_at", "submitted_at", "created_at"):
            if order.get(key) is not None:
                return parse_timestamp(order[key], fallback=received_at)
    return received_at


def extract_symbols(payload: dict[str, Any]) -> tuple[str, ...]:
    candidates: list[str] = []
    for key in ("S", "symbol"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    value = payload.get("symbols")
    if isinstance(value, (list, tuple)):
        candidates.extend(str(item) for item in value if item)
    order = payload.get("order")
    if isinstance(order, dict) and isinstance(order.get("symbol"), str):
        candidates.append(order["symbol"])
    normalized = [symbol.strip().upper() for symbol in candidates if symbol.strip()]
    return tuple(dict.fromkeys(normalized))


def extract_provider_event_id(payload: dict[str, Any]) -> str | None:
    for key in ("i", "id", "news_id", "execution_id", "accessionNumber"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    order = payload.get("order")
    if isinstance(order, dict) and order.get("id") is not None:
        event = payload.get("event", "trade_update")
        return f"{order['id']}:{event}:{payload.get('timestamp', '')}"
    return None


class CrossLoopEventSink:
    """Submit from Alpaca's stream thread into the recorder's main event loop."""

    def __init__(self, writer: AsyncBatchWriter, target_loop: asyncio.AbstractEventLoop) -> None:
        self._writer = writer
        self._target_loop = target_loop

    async def submit(self, event: RawEvent) -> None:
        await self._run_on_target(self._writer.submit(event))

    async def record_failure(self, failure: RawIngestFailure) -> None:
        await self._run_on_target(self._writer.record_failure(failure))

    async def _run_on_target(self, coroutine: Any) -> None:
        current = asyncio.get_running_loop()
        if current is self._target_loop:
            await coroutine
            return
        future = asyncio.run_coroutine_threadsafe(coroutine, self._target_loop)
        await asyncio.wrap_future(future)


async def build_and_submit(
    *,
    sink: CrossLoopEventSink,
    ingest_session_id: Any,
    connection_id: Any,
    source: RecorderSource,
    channel: str,
    event_type: EventType,
    message: Any,
) -> None:
    received_at = datetime.now(UTC)
    try:
        payload = model_to_payload(message)
        event = RawEvent.create(
            ingest_session_id=ingest_session_id,
            connection_id=connection_id,
            source=source,
            channel=channel,
            event_type=event_type,
            event_timestamp=extract_event_timestamp(payload, received_at=received_at),
            received_at=received_at,
            payload=payload,
            symbols=extract_symbols(payload),
            provider_event_id=extract_provider_event_id(payload),
        )
        await sink.submit(event)
    except Exception as exc:
        try:
            raw_payload = model_to_payload(message)
        except Exception:
            raw_payload = {"repr": repr(message), "type": type(message).__qualname__}
        failure = RawIngestFailure.create(
            ingest_session_id=ingest_session_id,
            connection_id=connection_id,
            source=source,
            channel=channel,
            received_at=received_at,
            error_type=type(exc).__qualname__,
            error_message=str(exc) or repr(exc),
            raw_payload=raw_payload,
        )
        await sink.record_failure(failure)
        raise
