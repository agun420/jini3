from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..input_models import DaybreakInput
from ..output_models import DaybreakOutput


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"


class InvariantViolation(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    invariant_number: int = Field(ge=1, le=77)
    path: str
    expected: str
    observed: str
    message: str


class InvariantCheck(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    invariant_number: int = Field(ge=1, le=77)
    name: str
    status: CheckStatus
    violations: tuple[InvariantViolation, ...] = ()
    note: str | None = None


class ValidationMetadata(BaseModel):
    """External evidence for orchestration-level invariants."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    evaluator_candidate_count: int | None = Field(default=None, ge=0)
    max_evaluator_candidates_hard: int | None = Field(default=None, gt=0)
    prequalified_out_tickers: frozenset[str] = frozenset()
    capacity_omitted_tickers: frozenset[str] = frozenset()
    capacity_omissions_logged: frozenset[str] = frozenset()
    preselection_policy_version: str | None = None
    evaluator_response_timestamp: datetime | None = None
    execution_cutoff_timestamp: datetime | None = None
    order_authorized: bool | None = None
    completed_phases: tuple[str, ...] = ()
    scoring_completed_before_gates: bool | None = None
    duplicate_detection_after_ticker_validation: bool | None = None
    duplicate_detection_valid_only: bool | None = None
    operational_blockers_after_schema_validation: bool | None = None
    semantic_magnitude_before_override: frozenset[str] = frozenset()
    invisible_disqualifier_tickers: frozenset[str] = frozenset()


class ValidationContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    input_payload: DaybreakInput | None
    output: DaybreakOutput
    raw_input: dict[str, Any] | None = None
    raw_output: dict[str, Any] | None = None
    metadata: ValidationMetadata = ValidationMetadata()


class ValidationReport(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    valid: bool
    execution_ready: bool
    model_errors: tuple[str, ...] = ()
    checks: tuple[InvariantCheck, ...] = ()

    @property
    def failures(self) -> tuple[InvariantCheck, ...]:
        return tuple(check for check in self.checks if check.status == CheckStatus.FAIL)

    @property
    def not_evaluated(self) -> tuple[InvariantCheck, ...]:
        return tuple(check for check in self.checks if check.status == CheckStatus.NOT_EVALUATED)
