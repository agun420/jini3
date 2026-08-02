from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from daybreak.core.config import DaybreakSettings, Environment

from .canonical import canonical_sha256
from .enums import AcceptanceStatus
from .models import AcceptanceCheck, AcceptanceReport


def build_acceptance_report(
    settings: DaybreakSettings,
    *,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
    probes: Mapping[str, Callable[[], tuple[bool, str, dict[str, object]]]] | None = None,
) -> AcceptanceReport:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    environ = os.environ if environ is None else environ
    probes = {} if probes is None else probes
    checks: list[AcceptanceCheck] = []

    def add(
        name: str, passed: bool, message: str, details: dict[str, object] | None = None
    ) -> None:
        checks.append(
            AcceptanceCheck(
                name=name,
                status=AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
                message=message,
                observed_at=now,
                details=details or {},
            )
        )

    add(
        "paper_environment",
        settings.runtime.environment
        in {Environment.PAPER, Environment.DEVELOPMENT, Environment.TEST},
        "Runtime is not configured as live."
        if settings.runtime.environment is not Environment.LIVE
        else "Live runtime is forbidden.",
    )
    add(
        "live_execution_disabled",
        not settings.safety.live_execution_enabled,
        "Live execution is disabled."
        if not settings.safety.live_execution_enabled
        else "Live execution must be disabled.",
    )
    add(
        "paper_endpoint",
        settings.execution.base_url == "https://paper-api.alpaca.markets",
        "Alpaca paper endpoint is configured.",
    )
    add(
        "execution_enabled",
        settings.execution.enabled,
        "Paper execution is enabled."
        if settings.execution.enabled
        else "Paper execution must be enabled for acceptance.",
    )
    add(
        "database_enabled",
        settings.database.enabled,
        "Database persistence is enabled."
        if settings.database.enabled
        else "Database persistence must be enabled.",
    )
    add(
        "alpaca_api_key_present",
        bool(environ.get(settings.execution.api_key_env)),
        f"Environment variable {settings.execution.api_key_env} is present."
        if environ.get(settings.execution.api_key_env)
        else f"Environment variable {settings.execution.api_key_env} is missing.",
    )
    add(
        "alpaca_secret_present",
        bool(environ.get(settings.execution.secret_key_env)),
        f"Environment variable {settings.execution.secret_key_env} is present."
        if environ.get(settings.execution.secret_key_env)
        else f"Environment variable {settings.execution.secret_key_env} is missing.",
    )
    if settings.database.enabled:
        add(
            "database_dsn_present",
            bool(environ.get(settings.database.dsn_env)),
            f"Environment variable {settings.database.dsn_env} is present."
            if environ.get(settings.database.dsn_env)
            else f"Environment variable {settings.database.dsn_env} is missing.",
        )

    for name, probe in sorted(probes.items()):
        try:
            passed, message, details = probe()
        except Exception as exc:
            passed, message, details = False, f"Probe failed: {type(exc).__name__}: {exc}", {}
        add(name, passed, message, details)

    required_online = {"alpaca_account", "alpaca_clock"}
    if settings.database.enabled:
        required_online.add("postgresql")
    if settings.safety.require_ntp_sync:
        required_online.add("system_ntp")
    online_verified = required_online.issubset(probes)
    paper_ready = online_verified and all(check.status is AcceptanceStatus.PASS for check in checks)
    core = {
        "generated_at": now,
        "online_verified": online_verified,
        "paper_ready": paper_ready,
        "checks": tuple(checks),
        "configuration_hash": settings.configuration_hash(),
    }
    report_hash = canonical_sha256(core)
    report_id = uuid5(NAMESPACE_URL, f"daybreak-acceptance:{report_hash}").hex
    return AcceptanceReport.model_validate(
        {**core, "report_id": report_id, "report_hash": report_hash}
    )


def system_ntp_probe() -> tuple[bool, str, dict[str, object]]:
    commands = (
        ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
        ["chronyc", "tracking"],
    )
    errors: list[str] = []
    for command in commands:
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=5, check=False
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{command[0]}: {type(exc).__name__}")
            continue
        output = completed.stdout.strip()
        if command[0] == "timedatectl" and completed.returncode == 0:
            passed = output.lower() == "yes"
            return (
                passed,
                (
                    "System clock is NTP synchronized."
                    if passed
                    else "System clock is not NTP synchronized."
                ),
                {"source": "timedatectl"},
            )
        if command[0] == "chronyc" and completed.returncode == 0:
            passed = "Leap status" in output and "Not synchronised" not in output
            return (
                passed,
                (
                    "Chrony reports a synchronized clock."
                    if passed
                    else "Chrony does not report synchronization."
                ),
                {"source": "chronyc"},
            )
        errors.append(f"{command[0]} returned {completed.returncode}")
    return False, "No supported NTP synchronization probe succeeded.", {"errors": errors}
