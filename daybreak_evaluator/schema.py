from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from daybreak.core.hashing import canonical_sha256
from daybreak_contracts.output_models import DaybreakOutput

# Metadata keywords are unnecessary for provider enforcement and can create drift.
_DROP_KEYS = {"title", "description", "default", "examples"}


def _sanitize_node(value: Any) -> Any:
    if isinstance(value, list):
        return [_sanitize_node(item) for item in value]
    if not isinstance(value, dict):
        return value

    out: dict[str, Any] = {}
    for key, item in value.items():
        if key in _DROP_KEYS:
            continue
        out[key] = _sanitize_node(item)

    if out.get("type") == "object" or "properties" in out:
        properties = out.get("properties", {})
        out["additionalProperties"] = False
        # Structured Outputs requires every property to be listed as required.
        if isinstance(properties, dict):
            out["required"] = list(properties.keys())
    return out


def daybreak_output_json_schema() -> dict[str, Any]:
    """Return the strict provider schema for the Daybreak v6.3 output contract."""
    raw = DaybreakOutput.model_json_schema(mode="serialization")
    return cast(dict[str, Any], _sanitize_node(deepcopy(raw)))


def schema_sha256() -> str:
    return canonical_sha256(daybreak_output_json_schema())


def structured_output_format(name: str) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": name,
        "strict": True,
        "schema": daybreak_output_json_schema(),
    }
