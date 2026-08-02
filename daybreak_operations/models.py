from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import CheckStatus, DrillStatus, DrillType, RecoveryAction


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class OperationsPolicy(StrictFrozenModel):
    policy_version: Literal["operations_policy_v1"] = "operations_policy_v1"
    mode: Literal["paper"] = "paper"
    timezone: Literal["America/New_York"] = "America/New_York"
    heartbeat_interval_seconds: Annotated[int, Field(ge=1, le=60)] = 5
    max_heartbeat_gap_seconds: Annotated[int, Field(ge=2, le=300)] = 20
    minimum_free_disk_bytes: Annotated[int, Field(ge=100_000_000)] = 5_000_000_000
    minimum_file_descriptor_limit: Annotated[int, Field(ge=256)] = 4096
    required_backup_retention_count: Annotated[int, Field(ge=1, le=365)] = 7
    recovery_requires_manual_trade_enable: Literal[True] = True
    allow_automatic_trade_resume: Literal[False] = False
    allow_live_execution: Literal[False] = False

    @model_validator(mode="after")
    def coherent(self) -> OperationsPolicy:
        if self.max_heartbeat_gap_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("max heartbeat gap must exceed heartbeat interval")
        return self


class MetricSample(StrictFrozenModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    value: Decimal
    unit: Annotated[str, Field(min_length=1, max_length=32)]
    labels: tuple[tuple[str, str], ...] = ()

    @field_validator("labels")
    @classmethod
    def labels_sorted_unique(
        cls, value: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        if tuple(sorted(value)) != value:
            raise ValueError("metric labels must be sorted")
        if len({key for key, _ in value}) != len(value):
            raise ValueError("metric label keys must be unique")
        return value


class ObservabilitySnapshot(StrictFrozenModel):
    snapshot_id: Annotated[str, Field(min_length=8, max_length=64)]
    session_id: str | None = None
    observed_at: datetime
    healthy: bool
    metrics: tuple[MetricSample, ...]
    failures: tuple[str, ...] = ()
    configuration_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    snapshot_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("observed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observability timestamp must be timezone-aware")
        return value.astimezone(UTC)


class RestartState(StrictFrozenModel):
    trading_date: date
    session_id: str | None = None
    previous_outcome: str | None = None
    kill_switch_active: bool
    managed_position_count: Annotated[int, Field(ge=0)]
    open_daybreak_order_count: Annotated[int, Field(ge=0)]
    recorder_checkpoint_available: bool
    database_consistent: bool
    leadership_lease_active: bool
    configuration_hash_matches: bool
    now: datetime

    @field_validator("now")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("restart timestamp must be timezone-aware")
        return value.astimezone(UTC)


class RecoveryPlan(StrictFrozenModel):
    plan_id: Annotated[str, Field(min_length=8, max_length=64)]
    generated_at: datetime
    action: RecoveryAction
    reasons: tuple[str, ...]
    may_resume_capture: bool
    may_resume_evaluation: bool
    may_resume_new_entries: Literal[False] = False
    manual_acknowledgement_required: Literal[True] = True
    state_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    plan_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("generated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recovery timestamp must be timezone-aware")
        return value.astimezone(UTC)


class BackupManifest(StrictFrozenModel):
    backup_id: Annotated[str, Field(min_length=8, max_length=64)]
    created_at: datetime
    source_database: Annotated[str, Field(min_length=1, max_length=256)]
    artifact_path: Path
    artifact_size_bytes: Annotated[int, Field(gt=0)]
    artifact_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    schema_revision: Annotated[str, Field(min_length=1, max_length=128)]
    table_counts: tuple[tuple[str, int], ...]
    encrypted: bool
    complete: bool
    manifest_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("created_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("backup timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("table_counts")
    @classmethod
    def counts_sorted(cls, value: tuple[tuple[str, int], ...]) -> tuple[tuple[str, int], ...]:
        if tuple(sorted(value)) != value:
            raise ValueError("table counts must be sorted")
        if any(count < 0 for _, count in value):
            raise ValueError("table counts cannot be negative")
        return value


class RestoreValidation(StrictFrozenModel):
    validation_id: Annotated[str, Field(min_length=8, max_length=64)]
    backup_id: str
    restored_at: datetime
    target_database: Annotated[str, Field(min_length=1, max_length=256)]
    artifact_hash_verified: bool
    schema_revision_match: bool
    table_counts_match: bool
    replay_verified: bool
    passed: bool
    errors: tuple[str, ...] = ()
    validation_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("restored_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("restore timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self) -> RestoreValidation:
        expected = (
            self.artifact_hash_verified
            and self.schema_revision_match
            and self.table_counts_match
            and self.replay_verified
            and not self.errors
        )
        if self.passed != expected:
            raise ValueError("restore passed flag does not match validation evidence")
        return self


class DrillObservation(StrictFrozenModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    passed: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DrillResult(StrictFrozenModel):
    drill_id: Annotated[str, Field(min_length=8, max_length=64)]
    drill_type: DrillType
    started_at: datetime
    completed_at: datetime
    status: DrillStatus
    failure_detected: bool
    new_entries_blocked: bool
    kill_switch_activated: bool
    recovery_verified: bool
    observations: tuple[DrillObservation, ...]
    errors: tuple[str, ...] = ()
    result_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("started_at", "completed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("drill timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self) -> DrillResult:
        passed = (
            self.failure_detected
            and self.new_entries_blocked
            and self.recovery_verified
            and not self.errors
        )
        if (self.status is DrillStatus.PASSED) != passed:
            raise ValueError("drill status does not match evidence")
        return self


class OperationsCheck(StrictFrozenModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    status: CheckStatus
    required: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class TargetAcceptanceReport(StrictFrozenModel):
    report_id: Annotated[str, Field(min_length=8, max_length=64)]
    generated_at: datetime
    target_verified: bool
    paper_ready: bool
    checks: tuple[OperationsCheck, ...]
    required_drills: tuple[DrillType, ...]
    passed_drills: tuple[DrillType, ...]
    restore_validation_id: str | None = None
    recovery_plan_id: str | None = None
    configuration_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    report_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("generated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acceptance timestamp must be timezone-aware")
        return value.astimezone(UTC)
