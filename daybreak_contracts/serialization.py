from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_json_bytes(value: BaseModel | Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: BaseModel | Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
