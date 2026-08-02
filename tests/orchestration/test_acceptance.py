from datetime import UTC, datetime

from daybreak.core.config import (
    DatabaseSettings,
    DaybreakSettings,
    Environment,
    ExecutionSettings,
    RuntimeSettings,
)
from daybreak_orchestration.acceptance import build_acceptance_report


def ready_settings():
    return DaybreakSettings(
        runtime=RuntimeSettings(environment=Environment.PAPER),
        database=DatabaseSettings(enabled=True),
        execution=ExecutionSettings(enabled=True),
    )


def test_offline_acceptance_checks_configuration_but_is_not_certified():
    settings = ready_settings()
    report = build_acceptance_report(
        settings,
        now=datetime(2026, 8, 3, 8, tzinfo=UTC),
        environ={
            "APCA_API_KEY_ID": "paper-key",
            "APCA_API_SECRET_KEY": "paper-secret",
            "DAYBREAK_DATABASE_URL": "postgresql://example",
        },
    )
    assert report.online_verified is False
    assert report.paper_ready is False


def test_online_acceptance_requires_passing_probes():
    settings = ready_settings()
    report = build_acceptance_report(
        settings,
        environ={
            "APCA_API_KEY_ID": "paper-key",
            "APCA_API_SECRET_KEY": "paper-secret",
            "DAYBREAK_DATABASE_URL": "postgresql://example",
        },
        probes={
            "alpaca_account": lambda: (True, "ok", {}),
            "alpaca_clock": lambda: (True, "ok", {}),
            "system_ntp": lambda: (True, "ok", {}),
            "postgresql": lambda: (True, "ok", {}),
        },
    )
    assert report.online_verified is True
    assert report.paper_ready is True


def test_acceptance_fails_without_secret_but_never_echoes_it():
    report = build_acceptance_report(
        ready_settings(),
        environ={"APCA_API_KEY_ID": "visible-key", "DAYBREAK_DATABASE_URL": "db"},
    )
    assert report.paper_ready is False
    rendered = report.model_dump_json()
    assert "visible-key" not in rendered


def test_probe_failure_is_fail_closed():
    def broken():
        raise RuntimeError("network down")

    report = build_acceptance_report(
        ready_settings(),
        environ={
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "DAYBREAK_DATABASE_URL": "db",
        },
        probes={"broker_probe": broken},
    )
    assert report.paper_ready is False
