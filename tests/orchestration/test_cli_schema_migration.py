import json
from pathlib import Path

from daybreak.cli import main


def paper_config(tmp_path: Path) -> Path:
    path = tmp_path / "daybreak.toml"
    path.write_text(
        """
[runtime]
environment = "paper"
timezone = "America/New_York"
log_level = "INFO"
json_logs = true

[database]
enabled = false
dsn_env = "DAYBREAK_DATABASE_URL"
connect_timeout_seconds = 5

[execution]
enabled = true
mode = "paper"
api_key_env = "APCA_API_KEY_ID"
secret_key_env = "APCA_API_SECRET_KEY"
base_url = "https://paper-api.alpaca.markets"
request_timeout_seconds = 5.0
cancel_unfilled_after_seconds = 10
partial_fill_protection_enabled = true

[orchestration]
enabled = true
holder_id = "test-holder"
""",
        encoding="utf-8",
    )
    return path


def test_orchestration_plan_cli(tmp_path, capsys):
    config = paper_config(tmp_path)
    assert (
        main(["orchestration-plan", "2026-08-03", "--run-id", "run-1", "--config", str(config)])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["trading_date"] == "2026-08-03"
    assert payload["policy"]["mode"] == "paper"


def test_orchestration_schema_cli(capsys):
    assert main(["orchestration-schema", "result"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "SessionResult"


def test_offline_acceptance_is_not_online_certification(tmp_path, capsys, monkeypatch):
    config = paper_config(tmp_path)
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    assert main(["acceptance-check", "--config", str(config)]) == 7
    payload = json.loads(capsys.readouterr().out)
    assert payload["online_verified"] is False
    assert payload["paper_ready"] is False


def test_phase6_migration_contains_fenced_lease_and_append_only_tables():
    migration = Path("migrations/versions/0006_phase6_orchestration.py").read_text(encoding="utf-8")
    assert 'revision = "0006_phase6_orchestration"' in migration
    assert "fencing_token" in migration
    assert "active BOOLEAN" in migration
    assert "orchestration_flatten_results" in migration
    assert "append-only" in migration
