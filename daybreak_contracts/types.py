from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, TypeGuard

from pydantic import AfterValidator, StringConstraints

TICKER_PATTERN = r"^[A-Z0-9](?:[A-Z0-9.-]{0,13}[A-Z0-9])?$"
_TICKER_RE = re.compile(TICKER_PATTERN)


def validate_utc_z_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be a UTC ISO 8601 string ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("timestamp must be valid UTC ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must use UTC")
    return value


UTCZTimestamp = Annotated[str, AfterValidator(validate_utc_z_timestamp)]
CanonicalTicker = Annotated[str, StringConstraints(pattern=TICKER_PATTERN)]


def is_canonical_ticker(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and _TICKER_RE.fullmatch(value) is not None
