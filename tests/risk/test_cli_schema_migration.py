from __future__ import annotations

import json
from pathlib import Path

from daybreak.cli import main
from daybreak_risk.canonical import canonical_json_text

from .helpers import sizing_request


def test_risk_cli_and_schema(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "decision.json"
    request_path.write_text(canonical_json_text(sizing_request()), encoding="utf-8")
    assert main(["risk-size", str(request_path), "--output", str(output_path)]) == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["decision"] == "approved"

    schema_path = tmp_path / "schema.json"
    assert main(["risk-schema", "decision", "--output", str(schema_path)]) == 0
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["title"] == "RiskDecision"


def test_risk_migration_is_chained_and_append_only() -> None:
    migration = Path("migrations/versions/0004_phase4_risk.py").read_text(encoding="utf-8")
    assert 'down_revision = "0003_phase3_evaluator"' in migration
    assert "risk_sizing_requests" in migration
    assert "risk_reservations" in migration
    assert "append-only" in migration
