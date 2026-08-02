from __future__ import annotations

import os
import platform
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from daybreak_evaluator.prompt import spec_is_available

from .config import DaybreakSettings


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    ok: bool
    required: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "required": self.required,
            "detail": self.detail,
        }


def _directory_check(name: str, path: Path) -> HealthCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".daybreak-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return HealthCheck(name, True, True, str(path.resolve()))
    except OSError as exc:
        return HealthCheck(name, False, True, str(exc))


def run_health_checks(settings: DaybreakSettings) -> tuple[HealthCheck, ...]:
    checks: list[HealthCheck] = []
    py_ok = sys.version_info >= (3, 12)
    checks.append(HealthCheck("python_version", py_ok, True, platform.python_version()))
    try:
        ZoneInfo(settings.runtime.timezone)
        checks.append(HealthCheck("timezone", True, True, settings.runtime.timezone))
    except ZoneInfoNotFoundError as exc:
        checks.append(HealthCheck("timezone", False, True, str(exc)))

    checks.append(_directory_check("state_dir", settings.paths.state_dir))
    checks.append(_directory_check("artifact_dir", settings.paths.artifact_dir))
    checks.append(
        HealthCheck(
            "spec_file",
            spec_is_available(settings.paths.spec_path),
            True,
            str(settings.paths.spec_path),
        )
    )

    if settings.database.enabled:
        present = bool(os.environ.get(settings.database.dsn_env))
        checks.append(
            HealthCheck("database_dsn_environment", present, True, settings.database.dsn_env)
        )
    else:
        checks.append(
            HealthCheck("database_disabled", True, False, "Database checks not requested")
        )

    if settings.evaluator.enabled:
        api_key_present = bool(os.environ.get(settings.evaluator.api_key_env))
        checks.append(
            HealthCheck(
                "openai_api_key_environment",
                api_key_present,
                True,
                settings.evaluator.api_key_env,
            )
        )
        try:
            from openai import AsyncOpenAI  # noqa: F401

            sdk_present = True
            detail = "OpenAI SDK import succeeded"
        except (ImportError, AttributeError) as exc:
            sdk_present = False
            detail = str(exc)
        checks.append(HealthCheck("openai_sdk", sdk_present, True, detail))
    else:
        checks.append(
            HealthCheck("evaluator_disabled", True, False, "Evaluator API checks not requested")
        )

    if settings.execution.enabled:
        api_key_present = bool(os.environ.get(settings.execution.api_key_env))
        secret_present = bool(os.environ.get(settings.execution.secret_key_env))
        checks.append(
            HealthCheck(
                "alpaca_paper_credentials",
                api_key_present and secret_present,
                True,
                f"{settings.execution.api_key_env},{settings.execution.secret_key_env}",
            )
        )
        checks.append(
            HealthCheck(
                "alpaca_paper_endpoint",
                settings.execution.base_url == "https://paper-api.alpaca.markets",
                True,
                settings.execution.base_url,
            )
        )
    else:
        checks.append(
            HealthCheck("execution_disabled", True, False, "Paper execution checks not requested")
        )

    checks.append(
        HealthCheck(
            "live_execution_disabled",
            not settings.safety.live_execution_enabled,
            True,
            "Project Daybreak v1.0.2 permits Alpaca paper trading only",
        )
    )
    return tuple(checks)


def required_checks_pass(checks: Iterable[HealthCheck]) -> bool:
    return all(check.ok for check in checks if check.required)
