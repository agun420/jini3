from __future__ import annotations

import time as time_module
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from .alerts import AlertManager
from .canonical import canonical_sha256
from .enums import (
    AlertSeverity,
    KillSwitchReason,
    PhaseStatus,
    SessionOutcome,
    SessionPhase,
)
from .flatten import FlattenService
from .kill_switch import activate_kill_switch, health_kill_reason, inactive_kill_switch
from .leadership import LeadershipRepository
from .models import (
    EvaluationPhaseSummary,
    FlattenResult,
    LeadershipLease,
    PhaseRecord,
    SessionPlan,
    SessionResult,
)
from .persistence import OrchestrationRepository
from .protocols import HealthProbe, SessionHooks

Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


class LeadershipUnavailable(RuntimeError):
    pass


class PersistentKillSwitchActive(RuntimeError):
    pass


class SessionOrchestrator:
    """Coordinates one paper trading session with fenced leadership and fail-closed safety."""

    def __init__(
        self,
        *,
        holder_id: str,
        leadership: LeadershipRepository,
        repository: OrchestrationRepository,
        health_probe: HealthProbe,
        hooks: SessionHooks,
        flatten_service: FlattenService,
        alerts: AlertManager,
        clock: Clock = lambda: datetime.now(UTC),
        sleep: Sleeper = time_module.sleep,
    ) -> None:
        self._holder_id = holder_id
        self._leadership = leadership
        self._repository = repository
        self._health_probe = health_probe
        self._hooks = hooks
        self._flatten_service = flatten_service
        self._alerts = alerts
        self._clock = clock
        self._sleep = sleep
        self._lease: LeadershipLease | None = None
        self._last_renewed_at: datetime | None = None

    def run(self, plan: SessionPlan, *, start_at: datetime | None = None) -> SessionResult:
        started_at = (start_at or self._clock()).astimezone(UTC)
        self._repository.save_plan(plan)
        kill_switch = self._repository.get_latest_kill_switch(plan.session_id)
        if kill_switch is None:
            kill_switch = inactive_kill_switch(plan.session_id)
            self._repository.save_kill_switch(kill_switch)
        flatten_result: FlattenResult | None = None
        outcome = SessionOutcome.FAILED
        final_phase = SessionPhase.CREATED
        error_message: str | None = None
        managed_quantities: dict[str, Decimal | int | str] = {}
        lease: LeadershipLease | None = None

        try:
            lease = self._leadership.acquire(
                plan.session_id,
                self._holder_id,
                now=started_at,
                ttl_seconds=plan.policy.leadership_ttl_seconds,
            )
            if lease is None:
                raise LeadershipUnavailable("another process holds session leadership")
            self._lease = lease
            self._last_renewed_at = started_at
            self._phase(
                plan,
                SessionPhase.LEADERSHIP_ACQUIRED,
                started_at,
                details={"fencing_token": lease.fencing_token},
            )
            if kill_switch.active:
                raise PersistentKillSwitchActive(
                    f"persistent kill switch is active: {kill_switch.reason}"
                )

            self._preflight(plan)
            self._wait_and_run(
                plan,
                SessionPhase.RECORDER_WARMUP,
                plan.recorder_warmup_at,
                self._hooks.warmup_recorder,
            )
            self._wait_and_run(
                plan,
                SessionPhase.RECORDING,
                plan.feature_window_start_at,
                lambda p, now, fencing_token: {
                    "capture_started_at": now,
                    "fencing_token": fencing_token,
                },
            )
            self._wait_and_run(
                plan,
                SessionPhase.FEATURE_FREEZE,
                plan.feature_snapshot_at,
                self._hooks.freeze_features,
            )
            evaluation = self._wait_and_run(
                plan, SessionPhase.EVALUATION, plan.feature_snapshot_at, self._hooks.evaluate
            )
            if self._clock().astimezone(UTC) > plan.evaluator_cutoff_at:
                raise RuntimeError("evaluator cutoff exceeded")

            evaluation_summary = EvaluationPhaseSummary.model_validate(evaluation)
            run_status = evaluation_summary.run_status
            approved_count = evaluation_summary.approved_count
            if run_status in {"blocked_market", "stale_payload", "schema_failure"}:
                outcome = SessionOutcome.BLOCKED
                final_phase = SessionPhase.EVALUATION
            elif run_status == "no_setups" or approved_count == 0:
                outcome = SessionOutcome.NO_SETUPS
                final_phase = SessionPhase.EVALUATION
            else:
                self._wait_until(plan, plan.eligibility_lock_at)
                self._preflight(plan, phase=SessionPhase.ELIGIBILITY_LOCK)
                self._wait_until(plan, plan.regular_session_open_at)
                if self._clock().astimezone(UTC) > plan.new_entry_cutoff_at:
                    raise RuntimeError("new-entry cutoff exceeded")
                execution = self._run_phase(
                    plan, SessionPhase.EXECUTION, self._hooks.size_and_execute
                )
                raw_managed = execution.get("managed_positions", {})
                if isinstance(raw_managed, dict):
                    for symbol, quantity in raw_managed.items():
                        if isinstance(quantity, bool) or not isinstance(
                            quantity, (Decimal, int, str)
                        ):
                            raise RuntimeError(f"invalid managed position quantity for {symbol!s}")
                        managed_quantities[str(symbol)] = quantity
                if self._clock().astimezone(UTC) > plan.new_entry_cutoff_at:
                    raise RuntimeError("new-entry cutoff exceeded")
                self._run_phase(plan, SessionPhase.MONITORING, self._hooks.reconcile)
                outcome = SessionOutcome.COMPLETED
                final_phase = SessionPhase.MONITORING
                if bool(execution.get("kill_switch_required", False)):
                    raise RuntimeError("execution requested kill switch")

            self._wait_until(plan, plan.mandatory_flatten_at)
            flatten_result = self._run_flatten(plan, managed_quantities=managed_quantities)
            final_phase = SessionPhase.FLATTENING
            if not flatten_result.complete:
                kill_switch = activate_kill_switch(
                    plan.session_id,
                    KillSwitchReason.FLATTEN_DEADLINE_EXCEEDED,
                    now=flatten_result.completed_at,
                    details={
                        "errors": flatten_result.errors,
                        "remaining": [p.symbol for p in flatten_result.remaining_positions],
                    },
                )
                self._repository.save_kill_switch(kill_switch)
                self._emit_critical(
                    plan,
                    "FLATTEN_INCOMPLETE",
                    "Mandatory end-of-day flatten did not complete.",
                    flatten_result.completed_at,
                )
                outcome = SessionOutcome.FLATTEN_INCOMPLETE
                final_phase = SessionPhase.KILLED
            else:
                self._phase(
                    plan,
                    SessionPhase.RECONCILIATION,
                    flatten_result.completed_at,
                    details={"flatten_complete": True},
                )
                self._phase(
                    plan, SessionPhase.COMPLETED, self._clock(), details={"outcome": outcome.value}
                )
                final_phase = SessionPhase.COMPLETED
        except LeadershipUnavailable as exc:
            error_message = str(exc)
            outcome = SessionOutcome.BLOCKED
            final_phase = SessionPhase.FAILED
            self._emit_critical(plan, "LEADERSHIP_UNAVAILABLE", error_message, started_at)
        except PersistentKillSwitchActive as exc:
            now = self._clock().astimezone(UTC)
            error_message = str(exc)
            outcome = SessionOutcome.KILLED
            final_phase = SessionPhase.KILLED
            self._emit_critical(plan, "PERSISTENT_KILL_SWITCH_ACTIVE", error_message, now)
            try:
                flatten_result = self._run_flatten(
                    plan, now=now, managed_quantities=managed_quantities
                )
            except Exception as flatten_exc:
                error_message += (
                    f"; emergency flatten failed: {type(flatten_exc).__name__}: {flatten_exc}"
                )
        except Exception as exc:
            now = self._clock().astimezone(UTC)
            error_message = f"{type(exc).__name__}: {exc}"
            reason = self._reason_from_error(error_message)
            kill_switch = activate_kill_switch(
                plan.session_id, reason, now=now, details={"error": error_message}
            )
            self._repository.save_kill_switch(kill_switch)
            self._emit_critical(plan, reason.value, error_message, now)
            outcome = SessionOutcome.KILLED
            final_phase = SessionPhase.KILLED
            try:
                flatten_result = self._run_flatten(
                    plan, now=now, managed_quantities=managed_quantities
                )
            except Exception as flatten_exc:
                error_message += (
                    f"; emergency flatten failed: {type(flatten_exc).__name__}: {flatten_exc}"
                )
        finally:
            completed_at = self._clock().astimezone(UTC)
            if lease is not None:
                self._leadership.release(lease, now=completed_at)
            phases = self._repository.list_phases(plan.session_id)
            alerts = self._repository.list_alerts(plan.session_id)
            core = {
                "session_id": plan.session_id,
                "run_id": plan.run_id,
                "outcome": outcome,
                "started_at": started_at,
                "completed_at": completed_at,
                "final_phase": final_phase,
                "leadership_holder_id": self._holder_id,
                "kill_switch": kill_switch,
                "flatten_result": flatten_result,
                "phase_records": phases,
                "alerts": alerts,
                "error_message": error_message,
            }
            result = SessionResult.model_validate({**core, "result_hash": canonical_sha256(core)})
            self._repository.save_result(result)
        return result

    def _preflight(
        self, plan: SessionPlan, *, phase: SessionPhase = SessionPhase.PREFLIGHT
    ) -> None:
        now = self._clock().astimezone(UTC)
        self._renew_leadership(plan, now)
        health = self._health_probe.snapshot(plan, now=now)
        reason = health_kill_reason(health, plan, plan.policy)
        if reason is not None:
            raise RuntimeError(f"preflight failed: {reason.value}")
        self._phase(plan, phase, now, details=health.model_dump(mode="json"))

    def _wait_and_run(
        self,
        plan: SessionPlan,
        phase: SessionPhase,
        at: datetime,
        function: Callable[[SessionPlan], dict[str, object]] | Callable[..., dict[str, object]],
    ) -> dict[str, object]:
        self._wait_until(plan, at)
        return self._run_phase(plan, phase, function)

    def _run_phase(
        self,
        plan: SessionPlan,
        phase: SessionPhase,
        function: Callable[..., dict[str, object]],
    ) -> dict[str, object]:
        started = self._clock().astimezone(UTC)
        self._renew_leadership(plan, started)
        if self._lease is None:
            raise RuntimeError("leadership lease missing")
        details = function(
            plan,
            now=started,
            fencing_token=self._lease.fencing_token,
        )
        ended = self._clock().astimezone(UTC)
        self._renew_leadership(plan, ended)
        self._phase(plan, phase, started, ended_at=ended, details=details)
        return details

    def _run_flatten(
        self,
        plan: SessionPlan,
        *,
        now: datetime | None = None,
        managed_quantities: dict[str, Decimal | int | str] | None = None,
    ) -> FlattenResult:
        now = (now or self._clock()).astimezone(UTC)
        result = self._flatten_service.flatten(
            plan,
            now=now,
            managed_quantities=managed_quantities or {},
            sleep=self._sleep,
            clock=self._clock,
        )
        self._phase(
            plan,
            SessionPhase.FLATTENING,
            now,
            ended_at=result.completed_at,
            details={"complete": result.complete, "remaining": len(result.remaining_positions)},
        )
        self._repository.save_flatten(result)
        return result

    def _phase(
        self,
        plan: SessionPlan,
        phase: SessionPhase,
        started_at: datetime,
        *,
        ended_at: datetime | None = None,
        details: dict[str, object] | None = None,
    ) -> PhaseRecord:
        sequence = len(self._repository.list_phases(plan.session_id)) + 1
        core = {
            "session_id": plan.session_id,
            "sequence": sequence,
            "phase": phase,
            "status": PhaseStatus.COMPLETED,
            "started_at": started_at.astimezone(UTC),
            "ended_at": None if ended_at is None else ended_at.astimezone(UTC),
            "details": details or {},
        }
        record = PhaseRecord.model_validate({**core, "record_hash": canonical_sha256(core)})
        self._repository.append_phase(record)
        return record

    def _renew_leadership(self, plan: SessionPlan, now: datetime) -> None:
        if self._lease is None:
            raise RuntimeError("leadership lease missing")
        if self._last_renewed_at is not None:
            elapsed = (now - self._last_renewed_at).total_seconds()
            if elapsed < plan.policy.leadership_renew_interval_seconds:
                return
        renewed = self._leadership.renew(
            self._lease,
            now=now,
            ttl_seconds=plan.policy.leadership_ttl_seconds,
        )
        if renewed is None:
            raise RuntimeError("leadership lost")
        self._lease = renewed
        self._last_renewed_at = now

    def _wait_until(self, plan: SessionPlan, target: datetime) -> None:
        while True:
            now = self._clock().astimezone(UTC)
            remaining = (target - now).total_seconds()
            if remaining <= 0:
                return
            self._sleep(min(remaining, 1.0))
            self._renew_leadership(plan, self._clock().astimezone(UTC))

    def _emit_critical(self, plan: SessionPlan, code: str, message: str, now: datetime) -> None:
        alert = self._alerts.emit(
            session_id=plan.session_id,
            severity=AlertSeverity.CRITICAL,
            code=code,
            message=message,
            now=now,
        )
        if alert is not None:
            self._repository.save_alert(alert)

    @staticmethod
    def _reason_from_error(message: str) -> KillSwitchReason:
        upper = message.upper()
        if "LEADERSHIP" in upper:
            return KillSwitchReason.LEADERSHIP_LOST
        if "EVALUATOR CUTOFF" in upper or "ENTRY CUTOFF" in upper:
            return KillSwitchReason.EXECUTION_CUTOFF_EXCEEDED
        if "CLOCK_UNSYNCED" in upper:
            return KillSwitchReason.CLOCK_UNSYNCED
        if "DATABASE_UNHEALTHY" in upper:
            return KillSwitchReason.DATABASE_UNHEALTHY
        if "RECORDER_UNHEALTHY" in upper:
            return KillSwitchReason.RECORDER_UNHEALTHY
        if "MARKET_DATA_UNHEALTHY" in upper:
            return KillSwitchReason.MARKET_DATA_UNHEALTHY
        if "TRADE_UPDATE_STREAM_UNHEALTHY" in upper:
            return KillSwitchReason.TRADE_UPDATE_STREAM_UNHEALTHY
        if "ACCOUNT_BLOCKED" in upper:
            return KillSwitchReason.ACCOUNT_BLOCKED
        if "TRADING_BLOCKED" in upper:
            return KillSwitchReason.TRADING_BLOCKED
        if "MARKET_CIRCUIT_BREAKER" in upper:
            return KillSwitchReason.MARKET_CIRCUIT_BREAKER
        if "CONFIGURATION_MISMATCH" in upper:
            return KillSwitchReason.CONFIGURATION_MISMATCH
        return KillSwitchReason.UNKNOWN_FAILURE
