from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from daybreak.core.hashing import canonical_sha256
from daybreak_contracts.input_models import DaybreakInput
from daybreak_contracts.output_models import DaybreakOutput
from daybreak_contracts.validation.models import ValidationReport

HASH_PATTERN = r"^[0-9a-f]{64}$"
Sha256 = Annotated[str, StringConstraints(pattern=HASH_PATTERN)]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class AttemptRole(StrEnum):
    PRIMARY = "primary"
    SHADOW = "shadow"


class AttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    TRANSPORT_ERROR = "transport_error"
    REFUSED = "refused"
    INCOMPLETE = "incomplete"
    EMPTY_OUTPUT = "empty_output"
    INVALID_JSON = "invalid_json"
    SCHEMA_INVALID = "schema_invalid"
    INVARIANT_INVALID = "invariant_invalid"
    CANCELED = "canceled"


class RunStatus(StrEnum):
    PRIMARY_VALID = "primary_valid"
    PRIMARY_INVALID = "primary_invalid"
    CUTOFF_MISSED = "cutoff_missed"
    INPUT_REJECTED = "input_rejected"


class TokenUsage(StrictFrozenModel):
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class EvaluatorPolicy(StrictFrozenModel):
    policy_version: Literal["evaluator_policy_v1"] = "evaluator_policy_v1"
    primary_model: str = "gpt-5.6-terra"
    shadow_model: str | None = "gpt-5.6-sol"
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"
    max_output_tokens: int = Field(default=64_000, ge=1_000, le=128_000)
    max_attempts: int = Field(default=2, ge=1, le=2)
    max_evaluator_candidates_hard: int = Field(default=25, ge=1, le=25)
    request_timeout_seconds: float = Field(default=90.0, gt=0, le=300)
    shadow_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    schema_name: Literal["project_daybreak_v6_3_output"] = "project_daybreak_v6_3_output"
    store_raw_provider_response: bool = True

    @model_validator(mode="after")
    def validate_models(self) -> EvaluatorPolicy:
        if not self.primary_model.strip():
            raise ValueError("primary_model must be nonempty")
        if self.shadow_model is not None:
            if not self.shadow_model.strip():
                raise ValueError("shadow_model must be nonempty when supplied")
            if self.shadow_model == self.primary_model:
                raise ValueError("shadow_model must differ from primary_model")
        return self


class EvaluationEvidence(StrictFrozenModel):
    snapshot_id: Sha256 | None = None
    context_hash: Sha256 | None = None
    payload_hash: Sha256
    feature_hash: Sha256 | None = None
    audit_hash: Sha256 | None = None
    configuration_hash: Sha256
    prequalified_out_tickers: frozenset[str] = frozenset()
    capacity_omitted_tickers: frozenset[str] = frozenset()
    capacity_omissions_logged: frozenset[str] = frozenset()
    preselection_policy_version: str | None = None


class EvaluationRequest(StrictFrozenModel):
    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    input_payload: DaybreakInput
    evidence: EvaluationEvidence
    response_cutoff_timestamp: datetime
    requested_at: datetime

    @model_validator(mode="after")
    def validate_request(self) -> EvaluationRequest:
        if self.requested_at.tzinfo is None or self.response_cutoff_timestamp.tzinfo is None:
            raise ValueError("requested_at and response_cutoff_timestamp must be timezone-aware")
        if self.response_cutoff_timestamp <= self.requested_at:
            raise ValueError("response cutoff must be after requested_at")
        payload_hash = canonical_sha256(self.input_payload.model_dump(mode="json"))
        if self.evidence.payload_hash != payload_hash:
            raise ValueError("payload_hash must match the canonical evaluator input")
        return self

    @field_validator("requested_at", "response_cutoff_timestamp")
    @classmethod
    def timestamps_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluation timestamps must be timezone-aware")
        return value.astimezone(UTC)


class ProviderResult(StrictFrozenModel):
    response_id: str | None = None
    model: str
    created_at: datetime | None = None
    completed_at: datetime
    output_text: str | None = None
    refusal: str | None = None
    incomplete_reason: str | None = None
    usage: TokenUsage = TokenUsage()
    raw_response: dict[str, Any] | None = None

    @field_validator("created_at", "completed_at")
    @classmethod
    def timestamps_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider timestamps must be timezone-aware")
        return value.astimezone(UTC)


class EvaluationAttempt(StrictFrozenModel):
    attempt_id: str
    run_id: str
    role: AttemptRole
    attempt_number: int = Field(ge=1, le=2)
    model: str
    request_started_at: datetime
    response_received_at: datetime | None = None
    status: AttemptStatus
    request_hash: Sha256
    prompt_hash: Sha256
    spec_hash: Sha256
    schema_hash: Sha256
    response_id: str | None = None
    raw_output_text: str | None = None
    raw_provider_response: dict[str, Any] | None = None
    response_text_hash: Sha256 | None = None
    raw_response_hash: Sha256 | None = None
    output: DaybreakOutput | None = None
    validation_report: ValidationReport | None = None
    usage: TokenUsage = TokenUsage()
    error_type: str | None = None
    error_message: str | None = None

    @field_validator("request_started_at", "response_received_at")
    @classmethod
    def timestamps_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("attempt timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def terminal_shape(self) -> EvaluationAttempt:
        if self.status == AttemptStatus.SUCCEEDED:
            if self.output is None or self.validation_report is None:
                raise ValueError("successful attempt requires output and validation_report")
            if not self.validation_report.valid:
                raise ValueError("successful attempt requires a valid report")
        return self


class TickerDisagreement(StrictFrozenModel):
    ticker: str
    primary_terminal: str | None
    shadow_terminal: str | None
    primary_magnitude_bucket: str | None
    shadow_magnitude_bucket: str | None
    primary_conviction_score: int | None
    shadow_conviction_score: int | None
    evidence_span_equal: bool | None


class ShadowComparison(StrictFrozenModel):
    comparison_version: Literal["shadow_compare_v1"] = "shadow_compare_v1"
    primary_attempt_id: str
    shadow_attempt_id: str
    exact_output_match: bool
    same_run_status: bool
    same_approved_order: bool
    ticker_disagreements: tuple[TickerDisagreement, ...]
    primary_output_hash: Sha256
    shadow_output_hash: Sha256


class ShadowEvaluationResult(StrictFrozenModel):
    run_id: str
    attempts: tuple[EvaluationAttempt, ...]
    comparison: ShadowComparison | None = None


class EvaluationRunResult(StrictFrozenModel):
    run_id: str
    status: RunStatus
    request: EvaluationRequest
    primary_attempts: tuple[EvaluationAttempt, ...]
    shadow_attempts: tuple[EvaluationAttempt, ...] = ()
    selected_primary_attempt_id: str | None = None
    output: DaybreakOutput | None = None
    comparison: ShadowComparison | None = None
    decision_ready_at: datetime | None = None
    late_response_rejected: bool = False

    @field_validator("decision_ready_at")
    @classmethod
    def decision_timestamp_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decision_ready_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self) -> EvaluationRunResult:
        if self.run_id != self.request.run_id:
            raise ValueError("result run_id must match the request")
        attempts = self.primary_attempts + self.shadow_attempts
        if any(item.run_id != self.run_id for item in attempts):
            raise ValueError("all attempts must belong to the result run")
        if any(item.role is not AttemptRole.PRIMARY for item in self.primary_attempts):
            raise ValueError("primary_attempts may contain only primary attempts")
        if any(item.role is not AttemptRole.SHADOW for item in self.shadow_attempts):
            raise ValueError("shadow_attempts may contain only shadow attempts")
        if len({item.attempt_id for item in attempts}) != len(attempts):
            raise ValueError("attempt ids must be unique")
        if self.status is RunStatus.PRIMARY_VALID:
            if (
                self.selected_primary_attempt_id is None
                or self.output is None
                or self.decision_ready_at is None
                or self.late_response_rejected
            ):
                raise ValueError("primary-valid result requires timely selected output")
            selected = next(
                (
                    item
                    for item in self.primary_attempts
                    if item.attempt_id == self.selected_primary_attempt_id
                ),
                None,
            )
            if (
                selected is None
                or selected.status is not AttemptStatus.SUCCEEDED
                or selected.output != self.output
            ):
                raise ValueError("selected primary attempt must be successful and match output")
        elif any(
            value is not None
            for value in (
                self.selected_primary_attempt_id,
                self.output,
                self.decision_ready_at,
            )
        ):
            raise ValueError("non-valid result cannot carry executable output")
        if self.late_response_rejected != (self.status is RunStatus.CUTOFF_MISSED):
            raise ValueError("late response flag must match cutoff-missed status")
        return self

    @property
    def executable_candidate_output(self) -> DaybreakOutput | None:
        """Return validated evaluator output; execution policy must still re-check timing/risk."""
        if self.status != RunStatus.PRIMARY_VALID or self.late_response_rejected:
            return None
        return self.output
