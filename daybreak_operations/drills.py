from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from .canonical import canonical_sha256
from .enums import DrillStatus, DrillType
from .models import DrillObservation, DrillResult


def run_failure_drill(
    drill_type: DrillType,
    *,
    inject_failure: Callable[[], None],
    detect_failure: Callable[[], bool],
    entries_blocked: Callable[[], bool],
    recovery_probe: Callable[[], bool],
    kill_switch_probe: Callable[[], bool] | None = None,
    now: Callable[[], datetime] | None = None,
) -> DrillResult:
    now = now or (lambda: datetime.now(UTC))
    started_at = now().astimezone(UTC)
    observations: list[DrillObservation] = []
    errors: list[str] = []
    try:
        inject_failure()
        observations.append(
            DrillObservation(
                name="failure_injected", passed=True, message="Failure injection completed."
            )
        )
    except Exception as exc:
        errors.append(f"INJECTION_FAILED:{type(exc).__name__}:{exc}")
        observations.append(
            DrillObservation(name="failure_injected", passed=False, message=str(exc))
        )
    failure_detected = _probe("failure_detected", detect_failure, observations, errors)
    new_entries_blocked = _probe("new_entries_blocked", entries_blocked, observations, errors)
    kill_switch_activated = (
        _probe("kill_switch_activated", kill_switch_probe, observations, errors)
        if kill_switch_probe
        else False
    )
    recovery_verified = _probe("recovery_verified", recovery_probe, observations, errors)
    completed_at = now().astimezone(UTC)
    status = (
        DrillStatus.PASSED
        if failure_detected and new_entries_blocked and recovery_verified and not errors
        else DrillStatus.FAILED
    )
    core = {
        "drill_type": drill_type,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "failure_detected": failure_detected,
        "new_entries_blocked": new_entries_blocked,
        "kill_switch_activated": kill_switch_activated,
        "recovery_verified": recovery_verified,
        "observations": tuple(observations),
        "errors": tuple(errors),
    }
    result_hash = canonical_sha256(core)
    drill_id = uuid5(NAMESPACE_URL, f"daybreak-drill:{result_hash}").hex
    return DrillResult.model_validate({**core, "drill_id": drill_id, "result_hash": result_hash})


def _probe(
    name: str,
    probe: Callable[[], bool] | None,
    observations: list[DrillObservation],
    errors: list[str],
) -> bool:
    if probe is None:
        return False
    try:
        passed = bool(probe())
        observations.append(
            DrillObservation(name=name, passed=passed, message=f"{name} returned {passed}.")
        )
        if not passed:
            errors.append(name.upper())
        return passed
    except Exception as exc:
        observations.append(DrillObservation(name=name, passed=False, message=str(exc)))
        errors.append(f"{name.upper()}_FAILED:{type(exc).__name__}:{exc}")
        return False
