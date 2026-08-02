"""Canonical serialization and hashing used by the raw recorder."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast
from uuid import UUID


def ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime; reject naive values."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("non-finite floats are not canonicalizable")
        return value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        utc = ensure_utc(value)
        text = utc.isoformat(timespec="microseconds")
        return text.replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value):
        return _normalize(dataclasses.asdict(cast(Any, value)))
    if hasattr(value, "model_dump"):
        return _normalize(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        normalized = [_normalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    raise TypeError(f"unsupported canonical type: {type(value)!r}")


def canonical_json_bytes(value: Any) -> bytes:
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_json_text(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
