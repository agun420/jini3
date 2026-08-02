from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from daybreak_contracts.types import CanonicalTicker

from .enums import (
    AcceptanceStatus,
    AlertSeverity,
    KillSwitchReason,
    LeadershipEventType,
    PhaseStatus,
    SessionOutcome,
    SessionPhase,
)


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class OrchestrationPolicy(StrictFrozenModel):
    policy_version: Literal["session_orchestration_policy_v1"] = "session_orchestration_policy_v1"
    mode: Literal["paper"] = "paper"
    timezone: Literal["America/New_York"] = "America/New_York"
    recorder_warmup_time_et: time = time(3, 55)
    feature_window_start_time_et: time = time(4, 0)
    feature_snapshot_time_et: time = time(9, 23)
    evaluator_cutoff_time_et: time = time(9, 26, 30)
    eligibility_lock_time_et: time = time(9, 29, 30)
    regular_session_open_time_et: time = time(9, 30)
    new_entry_cutoff_time_et: time = time(9, 31, 30)
    mandatory_flatten_time_et: time = time(15, 50)
    final_flatten_deadline_et: time = time(15, 55)
    leadership_ttl_seconds: Annotated[int, Field(ge=5, le=300)] = 30
    leadership_renew_interval_seconds: Annotated[int, Field(ge=1, le=60)] = 10
    max_clock_skew_ms: Annotated[int, Field(gt=0, le=5000)] = 250
    flatten_poll_interval_seconds: Annotated[float, Field(gt=0, le=30)] = 1.0
    flatten_verification_timeout_seconds: Annotated[float, Field(gt=0, le=600)] = 300.0
    alert_dedup_window_seconds: Annotated[int, Field(ge=0, le=3600)] = 300
    allow_live_execution: Literal[False] = False

    @model_validator(mode="after")
    def times_are_monotonic(self) -> OrchestrationPolicy:
        ordered = (
            self.recorder_warmup_time_et,
            self.feature_window_start_time_et,
            self.feature_snapshot_time_et,
            self.evaluator_cutoff_time_et,
            self.eligibility_lock_time_et,
            self.regular_session_open_time_et,
            self.new_entry_cutoff_time_et,
            self.mandatory_flatten_time_et,
            self.final_flatten_deadline_et,
        )
        if any(left >= right for left, right in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("orchestration times must be strictly increasing")
        if self.leadership_renew_interval_seconds >= self.leadership_ttl_seconds:
            raise ValueError("leadership renew interval must be below lease TTL")
        return self


class SessionPlan(StrictFrozenModel):
    session_id: Annotated[str, Field(min_length=8, max_length=64)]
    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    trading_date: date
    recorder_warmup_at: datetime
    feature_window_start_at: datetime
    feature_snapshot_at: datetime
    evaluator_cutoff_at: datetime
    eligibility_lock_at: datetime
    regular_session_open_at: datetime
    new_entry_cutoff_at: datetime
    mandatory_flatten_at: datetime
    final_flatten_deadline_at: datetime
    policy: OrchestrationPolicy
    configuration_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator(
        "recorder_warmup_at",
        "feature_window_start_at",
        "feature_snapshot_at",
        "evaluator_cutoff_at",
        "eligibility_lock_at",
        "regular_session_open_at",
        "new_entry_cutoff_at",
        "mandatory_flatten_at",
        "final_flatten_deadline_at",
    )
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("session plan timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def chronological(self) -> SessionPlan:
        ordered = (
            self.recorder_warmup_at,
            self.feature_window_start_at,
            self.feature_snapshot_at,
            self.evaluator_cutoff_at,
            self.eligibility_lock_at,
            self.regular_session_open_at,
            self.new_entry_cutoff_at,
            self.mandatory_flatten_at,
            self.final_flatten_deadline_at,
        )
        if any(left >= right for left, right in zip(ordered, ordered[1:], strict=False)):
            raise ValueError("session plan timestamps must be strictly increasing")
        return self


class HealthSnapshot(StrictFrozenModel):
    observed_at: datetime
    clock_synchronized: bool
    clock_skew_ms: int
    database_healthy: bool
    recorder_healthy: bool
    market_data_stream_healthy: bool
    trade_update_stream_healthy: bool
    broker_healthy: bool
    account_active: bool
    account_blocked: bool = False
    trading_blocked: bool = False
    market_status_normal: bool = True
    configuration_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("health timestamp must be timezone-aware")
        return value.astimezone(UTC)


class EvaluationPhaseSummary(StrictFrozenModel):
    """Narrow, fail-closed contract between evaluator and orchestration."""

    run_status: Literal[
        "approved",
        "no_setups",
        "blocked_market",
        "stale_payload",
        "schema_failure",
    ]
    approved_count: Annotated[int, Field(ge=0, le=3)]

    @model_validator(mode="after")
    def coherent(self) -> EvaluationPhaseSummary:
        if self.run_status == "approved" and self.approved_count == 0:
            raise ValueError("approved evaluation must contain at least one setup")
        if self.run_status != "approved" and self.approved_count != 0:
            raise ValueError("non-approved evaluation cannot contain approved setups")
        return self


class PhaseRecord(StrictFrozenModel):
    session_id: str
    sequence: Annotated[int, Field(ge=1)]
    phase: SessionPhase
    status: PhaseStatus
    started_at: datetime
    ended_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    record_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("started_at", "ended_at")
    @classmethod
    def aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("phase timestamps must be timezone-aware")
        return value.astimezone(UTC)


class LeadershipLease(StrictFrozenModel):
    session_id: str
    holder_id: Annotated[str, Field(min_length=1, max_length=128)]
    acquired_at: datetime
    renewed_at: datetime
    expires_at: datetime
    fencing_token: Annotated[int, Field(ge=1)]

    @field_validator("acquired_at", "renewed_at", "expires_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("leadership timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_window(self) -> LeadershipLease:
        if self.renewed_at < self.acquired_at or self.expires_at <= self.renewed_at:
            raise ValueError("invalid leadership lease window")
        return self


class LeadershipEvent(StrictFrozenModel):
    session_id: str
    holder_id: str
    event_type: LeadershipEventType
    event_timestamp: datetime
    fencing_token: int
    details: dict[str, Any] = Field(default_factory=dict)
    event_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("event_timestamp")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("leadership event timestamp must be timezone-aware")
        return value.astimezone(UTC)


class KillSwitchState(StrictFrozenModel):
    session_id: str
    active: bool
    activated_at: datetime | None = None
    reason: KillSwitchReason | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    reset_required: bool = False
    state_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("activated_at")
    @classmethod
    def aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("kill-switch timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self) -> KillSwitchState:
        if self.active and (self.activated_at is None or self.reason is None):
            raise ValueError("active kill switch requires timestamp and reason")
        if not self.active and (self.activated_at is not None or self.reason is not None):
            raise ValueError("inactive kill switch cannot carry activation data")
        if self.active and not self.reset_required:
            raise ValueError("active kill switch must require explicit reset")
        return self


class AlertRecord(StrictFrozenModel):
    alert_id: Annotated[str, Field(min_length=8, max_length=64)]
    session_id: str
    severity: AlertSeverity
    code: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(min_length=1, max_length=2048)]
    created_at: datetime
    dedup_key: Annotated[str, Field(min_length=1, max_length=256)]
    details: dict[str, Any] = Field(default_factory=dict)
    alert_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("created_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("alert timestamp must be timezone-aware")
        return value.astimezone(UTC)


class ManagedPositionTarget(StrictFrozenModel):
    symbol: CanonicalTicker
    quantity: Annotated[Decimal, Field(gt=0)]
    source: Literal["execution_ledger", "broker_order_reconstruction", "combined"]


class SessionPosition(StrictFrozenModel):
    symbol: CanonicalTicker
    quantity: Annotated[Decimal, Field(gt=0)]
    side: Literal["long"] = "long"
    average_entry_price: Decimal | None = Field(default=None, gt=0)
    observed_at: datetime
    raw_response_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("observed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("position timestamp must be timezone-aware")
        return value.astimezone(UTC)


class FlattenOrder(StrictFrozenModel):
    symbol: CanonicalTicker
    quantity: Decimal = Field(gt=0)
    broker_order_id: str
    client_order_id: str | None = None
    submitted_at: datetime
    raw_response_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("submitted_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("flatten order timestamp must be timezone-aware")
        return value.astimezone(UTC)


class FlattenResult(StrictFrozenModel):
    flatten_id: Annotated[str, Field(min_length=8, max_length=64)]
    session_id: str
    started_at: datetime
    completed_at: datetime
    canceled_order_count: Annotated[int, Field(ge=0)]
    initial_positions: tuple[SessionPosition, ...]
    close_orders: tuple[FlattenOrder, ...]
    remaining_positions: tuple[SessionPosition, ...]
    complete: bool
    errors: tuple[str, ...] = ()
    result_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("started_at", "completed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("flatten timestamps must be timezone-aware")
        return value.astimezone(UTC)


class AcceptanceCheck(StrictFrozenModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    status: AcceptanceStatus
    message: str
    observed_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acceptance timestamp must be timezone-aware")
        return value.astimezone(UTC)


class AcceptanceReport(StrictFrozenModel):
    report_id: Annotated[str, Field(min_length=8, max_length=64)]
    generated_at: datetime
    online_verified: bool
    paper_ready: bool
    checks: tuple[AcceptanceCheck, ...]
    configuration_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    report_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("generated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acceptance timestamp must be timezone-aware")
        return value.astimezone(UTC)


class SessionResult(StrictFrozenModel):
    session_id: str
    run_id: str
    outcome: SessionOutcome
    started_at: datetime
    completed_at: datetime
    final_phase: SessionPhase
    leadership_holder_id: str
    kill_switch: KillSwitchState
    flatten_result: FlattenResult | None = None
    phase_records: tuple[PhaseRecord, ...]
    alerts: tuple[AlertRecord, ...]
    error_message: str | None = None
    result_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("started_at", "completed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("session timestamps must be timezone-aware")
        return value.astimezone(UTC)
