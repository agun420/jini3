from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from daybreak.core.hashing import canonical_sha256
from daybreak_contracts.input_models import DaybreakInput
from daybreak_evaluator.models import EvaluationEvidence, EvaluationRequest
from daybreak_evaluator.persistence import PostgresEvaluatorRepository

ROOT = Path(__file__).resolve().parents[2]


class FakeCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_obj


def test_save_request_matches_append_only_migration(monkeypatch) -> None:
    payload = DaybreakInput.model_validate_json(
        (ROOT / "tests/fixtures/approved_input.json").read_text()
    )
    now = datetime.now(UTC)
    request = EvaluationRequest(
        run_id="run-db",
        input_payload=payload,
        evidence=EvaluationEvidence(
            payload_hash=canonical_sha256(payload.model_dump(mode="json")),
            configuration_hash="a" * 64,
        ),
        requested_at=now,
        response_cutoff_timestamp=now + timedelta(seconds=30),
    )
    connection = FakeConnection()
    repository = PostgresEvaluatorRepository("unused")
    monkeypatch.setattr(repository, "_connect", lambda: connection)
    repository.save_request(request)
    sql, params = connection.cursor_obj.calls[0]
    assert "request_json" in sql
    assert "status" not in sql.split("VALUES", 1)[0]
    assert len(params) == 6


def test_sqlalchemy_style_psycopg_dsn_is_normalized() -> None:
    repository = PostgresEvaluatorRepository(
        "postgresql+psycopg://daybreak:secret@localhost/daybreak"
    )
    assert repository._dsn == "postgresql://daybreak:secret@localhost/daybreak"
