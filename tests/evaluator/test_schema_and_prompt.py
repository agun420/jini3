from __future__ import annotations

import json
from pathlib import Path

import pytest

from daybreak_contracts.input_models import DaybreakInput
from daybreak_evaluator.prompt import build_prompt
from daybreak_evaluator.schema import daybreak_output_json_schema, schema_sha256

ROOT = Path(__file__).resolve().parents[2]


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_structured_schema_is_strict_and_stable() -> None:
    schema = daybreak_output_json_schema()
    assert len(schema_sha256()) == 64
    for node in _walk(schema):
        assert "title" not in node
        assert "default" not in node
        if node.get("type") == "object" or "properties" in node:
            assert node["additionalProperties"] is False
            assert node["required"] == list(node.get("properties", {}).keys())


def test_prompt_uses_exact_payload_and_spec() -> None:
    payload = DaybreakInput.model_validate_json(
        (ROOT / "tests/fixtures/approved_input.json").read_text()
    )
    bundle = build_prompt(ROOT / "docs/spec/Project_Daybreak_v6.3_Final.md", payload)
    assert "PROJECT DAYBREAK" in bundle.directive.upper()
    assert json.loads(bundle.payload_text)["tickers"][0]["ticker"] == "AAAA"
    assert len(bundle.prompt_hash) == 64


def test_prompt_falls_back_to_bundled_spec(tmp_path) -> None:
    payload = DaybreakInput.model_validate_json(
        (ROOT / "tests/fixtures/approved_input.json").read_text()
    )
    bundle = build_prompt(tmp_path / "missing.md", payload)
    assert "PROJECT DAYBREAK" in bundle.directive.upper()
    assert len(bundle.spec_hash) == 64


def test_prompt_rejects_modified_specification(tmp_path) -> None:
    payload = DaybreakInput.model_validate_json(
        (ROOT / "tests/fixtures/approved_input.json").read_text(encoding="utf-8")
    )
    modified = tmp_path / "modified-v6.3.md"
    modified.write_text("# modified specification", encoding="utf-8")
    with pytest.raises(ValueError, match="pinned v6.3"):
        build_prompt(modified, payload)
