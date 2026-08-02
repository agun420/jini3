from pathlib import Path

import pytest

from daybreak.core.config import ConfigurationError, Environment, load_settings


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_and_hash_is_deterministic(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[runtime]
environment = "test"
timezone = "America/New_York"
log_level = "INFO"
json_logs = true
[paths]
state_dir = "state"
artifact_dir = "artifacts"
spec_path = "docs/spec/Project_Daybreak_v6.3_Final.md"
[database]
enabled = false
dsn_env = "DAYBREAK_DATABASE_URL"
connect_timeout_seconds = 5
[recorder]
enabled = false
start_time_et = "03:55:00"
feature_window_start_et = "04:00:00"
feature_snapshot_time_et = "09:23:00"
[safety]
live_execution_enabled = false
require_ntp_sync = true
max_clock_skew_ms = 250
""",
    )
    first = load_settings(path, environ={})
    second = load_settings(path, environ={})
    assert first.runtime.environment is Environment.TEST
    assert first.configuration_hash() == second.configuration_hash()


def test_environment_overlay(tmp_path: Path) -> None:
    path = _write(tmp_path, "")
    settings = load_settings(path, environ={"DAYBREAK_ENVIRONMENT": "paper"})
    assert settings.runtime.environment is Environment.PAPER


def test_live_execution_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[runtime]
environment = "live"
[safety]
live_execution_enabled = true
""",
    )
    with pytest.raises(ConfigurationError):
        load_settings(path, environ={})


def test_paper_profile_cannot_enable_live_execution(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[runtime]
environment = "paper"
[safety]
live_execution_enabled = true
""",
    )
    with pytest.raises(ConfigurationError):
        load_settings(path, environ={})


def test_execution_cannot_run_under_live_environment(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[runtime]
environment = "live"
[execution]
enabled = true
""",
    )
    with pytest.raises(ConfigurationError):
        load_settings(path, environ={})
