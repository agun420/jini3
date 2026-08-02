from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from daybreak_recorder.settings import RecorderSettings


def test_configuration_hash_excludes_secret_values_but_tracks_presence() -> None:
    first = RecorderSettings(
        alpaca_api_key=SecretStr("key-one"),
        alpaca_secret_key=SecretStr("secret-one"),
    )
    second = RecorderSettings(
        alpaca_api_key=SecretStr("key-two"),
        alpaca_secret_key=SecretStr("secret-two"),
    )
    missing = RecorderSettings()
    assert first.configuration_hash == second.configuration_hash
    assert first.configuration_hash != missing.configuration_hash


def test_database_password_is_redacted_and_does_not_change_configuration_hash() -> None:
    first = RecorderSettings(
        database_url="postgresql+psycopg://daybreak:first-secret@db.example:5432/daybreak"
    )
    second = RecorderSettings(
        database_url="postgresql+psycopg://daybreak:second-secret@db.example:5432/daybreak"
    )
    assert "secret" not in first.redacted_database_url
    assert first.redacted_database_url == "postgresql+psycopg://daybreak@db.example:5432/daybreak"
    assert first.configuration_hash == second.configuration_hash


def test_migration_enforces_append_only_raw_tables() -> None:
    path = Path(__file__).parents[2] / "migrations" / "versions" / "0001_phase1_recorder.py"
    text = path.read_text(encoding="utf-8")
    assert "CREATE TABLE raw_events" in text
    assert "raw_events_append_only" in text
    assert "BEFORE UPDATE OR DELETE" in text
    assert "idempotency_key CHAR(64) NOT NULL UNIQUE" in text
    assert "ingest_sessions_lifecycle_guard" in text
    assert "terminal ingest sessions cannot be modified" in text


def test_shutdown_timeout_is_environment_configurable() -> None:
    settings = RecorderSettings.from_env(
        {
            "DAYBREAK_SHUTDOWN_TIMEOUT_SECONDS": "7.5",
            "DAYBREAK_STREAM_CONNECT_TIMEOUT_SECONDS": "9",
        }
    )
    assert settings.shutdown_timeout_seconds == 7.5
    assert settings.stream_connect_timeout_seconds == 9


def test_generated_raw_event_schema_contains_phase1_event_types() -> None:
    path = Path(__file__).parents[2] / "schemas" / "raw_event.schema.json"
    text = path.read_text(encoding="utf-8")
    assert '"sec_submissions_snapshot"' in text
    assert '"trade_correction"' in text
    assert '"stream_connected"' in text


def test_wildcard_tick_subscription_is_rejected() -> None:
    import pytest

    with pytest.raises(ValueError, match="wildcard trades and quotes"):
        RecorderSettings(tick_symbols=("*",))


def test_sec_ciks_require_declared_user_agent() -> None:
    import pytest

    with pytest.raises(ValueError, match="sec_user_agent"):
        RecorderSettings(sec_ciks=("0000320193",))


def test_package_version_matches_pyproject() -> None:
    import tomllib

    root = Path(__file__).parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    from daybreak_recorder import __version__

    assert __version__ == project["tool"]["daybreak"]["components"]["recorder"]
