from __future__ import annotations

import os
import platform
import resource
import shutil
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .canonical import canonical_sha256
from .enums import CheckStatus, DrillStatus, DrillType
from .models import (
    DrillResult,
    OperationsCheck,
    OperationsPolicy,
    RecoveryPlan,
    RestoreValidation,
    TargetAcceptanceReport,
)

REQUIRED_DRILLS = (
    DrillType.DATABASE_DISCONNECT,
    DrillType.MARKET_DATA_DISCONNECT,
    DrillType.TRADE_UPDATE_DISCONNECT,
    DrillType.BROKER_TIMEOUT,
    DrillType.CLOCK_SKEW,
    DrillType.PROCESS_RESTART,
)


def build_target_acceptance_report(
    *,
    configuration_hash: str,
    policy: OperationsPolicy | None = None,
    state_dir: str | Path = ".",
    probes: Mapping[str, Callable[[], tuple[bool, str, dict[str, object]]]] | None = None,
    restore_validation: RestoreValidation | None = None,
    recovery_plan: RecoveryPlan | None = None,
    drill_results: tuple[DrillResult, ...] = (),
    generated_at: datetime | None = None,
) -> TargetAcceptanceReport:
    policy = policy or OperationsPolicy()
    probes = probes or {}
    generated_at = (generated_at or datetime.now(UTC)).astimezone(UTC)
    checks: list[OperationsCheck] = []

    def add(
        name: str,
        passed: bool,
        message: str,
        *,
        required: bool = True,
        details: dict[str, object] | None = None,
    ) -> None:
        checks.append(
            OperationsCheck(
                name=name,
                status=CheckStatus.PASS if passed else CheckStatus.FAIL,
                required=required,
                message=message,
                details=details or {},
            )
        )

    add(
        "paper_only_policy",
        not policy.allow_live_execution and not policy.allow_automatic_trade_resume,
        "Operations policy is paper-only and forbids automatic trade resume.",
    )
    add(
        "python_version",
        sys.version_info >= (3, 12),
        f"Python {platform.python_version()} detected.",
    )
    add("linux_platform", sys.platform.startswith("linux"), f"Platform is {sys.platform}.")
    state = Path(state_dir).resolve()
    state.mkdir(parents=True, exist_ok=True)
    add("state_directory_writable", os.access(state, os.W_OK), f"State directory is {state}.")
    free = shutil.disk_usage(state).free
    add(
        "free_disk",
        free >= policy.minimum_free_disk_bytes,
        f"Free disk bytes: {free}.",
        details={"free_bytes": free, "minimum": policy.minimum_free_disk_bytes},
    )
    soft_fd, hard_fd = resource.getrlimit(resource.RLIMIT_NOFILE)
    add(
        "file_descriptor_limit",
        soft_fd >= policy.minimum_file_descriptor_limit,
        f"Soft file descriptor limit: {soft_fd}.",
        details={"soft": soft_fd, "hard": hard_fd},
    )
    add(
        "systemd_available",
        shutil.which("systemctl") is not None,
        "systemctl availability checked.",
    )

    for name, probe in sorted(probes.items()):
        try:
            passed, message, details = probe()
        except Exception as exc:
            passed, message, details = False, f"Probe failed: {type(exc).__name__}: {exc}", {}
        add(name, passed, message, details=details)

    add(
        "backup_restore_validation",
        bool(restore_validation and restore_validation.passed),
        "A passing backup/restore validation is required.",
    )
    recovery_safe = bool(
        recovery_plan
        and not recovery_plan.may_resume_new_entries
        and recovery_plan.manual_acknowledgement_required
    )
    add(
        "restart_recovery_plan",
        recovery_safe,
        "Recovery plan must prohibit automatic new-entry resume.",
    )
    passed_drills = tuple(
        sorted(
            (result.drill_type for result in drill_results if result.status is DrillStatus.PASSED),
            key=str,
        )
    )
    add(
        "failure_drills",
        set(REQUIRED_DRILLS).issubset(passed_drills),
        "All required operational failure drills must pass.",
        details={
            "required": [item.value for item in REQUIRED_DRILLS],
            "passed": [item.value for item in passed_drills],
        },
    )

    required_probe_names = {
        "alpaca_account",
        "alpaca_clock",
        "postgresql",
        "system_ntp",
        "migration_head",
    }
    target_verified = required_probe_names.issubset(probes)
    paper_ready = target_verified and all(
        check.status is CheckStatus.PASS for check in checks if check.required
    )
    core = {
        "generated_at": generated_at,
        "target_verified": target_verified,
        "paper_ready": paper_ready,
        "checks": tuple(checks),
        "required_drills": REQUIRED_DRILLS,
        "passed_drills": passed_drills,
        "restore_validation_id": restore_validation.validation_id if restore_validation else None,
        "recovery_plan_id": recovery_plan.plan_id if recovery_plan else None,
        "configuration_hash": configuration_hash,
    }
    report_hash = canonical_sha256(core)
    report_id = uuid5(NAMESPACE_URL, f"daybreak-target-acceptance:{report_hash}").hex
    return TargetAcceptanceReport.model_validate(
        {**core, "report_id": report_id, "report_hash": report_hash}
    )
