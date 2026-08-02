from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import StrictFrozenModel
from .enums import (
    BlockerCode,
    CatalystZeroReason,
    EvidencePurpose,
    MagnitudeBucket,
    MarketStatus,
    ReasonCode,
    RiskFlag,
    RunStatus,
    SchemaFailureScope,
    SourceType,
    TechnicalGrade,
)
from .types import CanonicalTicker, UTCZTimestamp

RISK_FLAG_ORDER = [
    RiskFlag.PARABOLIC.value,
    RiskFlag.HARD_TO_BORROW.value,
    RiskFlag.UNKNOWN_BORROW.value,
    RiskFlag.LOW_FLOAT.value,
    RiskFlag.SPIKY_VOLUME.value,
    RiskFlag.SECONDARY_SOURCE.value,
]


class ScoreBreakdown(StrictFrozenModel):
    source_quality_points: Annotated[int, Field(ge=0, le=6)]
    catalyst_magnitude_bucket: MagnitudeBucket
    catalyst_magnitude_points: Annotated[int, Field(ge=0, le=4)]
    evidence_purpose: EvidencePurpose
    magnitude_evidence_excerpt: Annotated[str, Field(max_length=200)]
    magnitude_evidence_truncated: bool
    magnitude_evidence_start_char: int | None
    magnitude_evidence_end_char: int | None
    catalyst_zero_override: bool
    catalyst_zero_reason: CatalystZeroReason | None
    catalyst_score_raw: Annotated[int, Field(ge=0, le=10)]
    catalyst_points: Annotated[int, Field(ge=0, le=40)]
    volume_points: Literal[0, 15, 25, 35]
    technical_grade: TechnicalGrade
    technical_base_points: Literal[0, 13, 22, 25]
    technical_points: Literal[0, 7, 13, 16, 19, 22, 25]
    parabolic_adjusted: bool

    @model_validator(mode="after")
    def validate_local_consistency(self) -> ScoreBreakdown:
        if (self.magnitude_evidence_start_char is None) != (
            self.magnitude_evidence_end_char is None
        ):
            raise ValueError("evidence positions must both be integers or both null")
        if self.catalyst_zero_override != (self.catalyst_zero_reason is not None):
            raise ValueError(
                "catalyst_zero_override must be true iff catalyst_zero_reason is non-null"
            )
        if self.evidence_purpose == EvidencePurpose.DISQUALIFIER:
            if self.catalyst_zero_reason != CatalystZeroReason.DISQUALIFIER_FLAG:
                raise ValueError(
                    "disqualifier evidence requires catalyst_zero_reason=disqualifier_flag"
                )
        elif self.evidence_purpose == EvidencePurpose.NONE:
            if self.catalyst_zero_reason != CatalystZeroReason.NO_VALID_DRIVER:
                raise ValueError(
                    "none evidence purpose requires catalyst_zero_reason=no_valid_driver"
                )
            if (
                self.magnitude_evidence_excerpt,
                self.magnitude_evidence_truncated,
                self.magnitude_evidence_start_char,
                self.magnitude_evidence_end_char,
            ) != ("", False, None, None):
                raise ValueError("none evidence purpose requires canonical empty evidence")
        elif self.catalyst_zero_reason in {
            CatalystZeroReason.DISQUALIFIER_FLAG,
            CatalystZeroReason.NO_VALID_DRIVER,
        }:
            raise ValueError("magnitude evidence purpose is incompatible with this zero reason")
        return self


class EvaluationSnapshot(ScoreBreakdown):
    risk_flags: tuple[RiskFlag, ...]

    @model_validator(mode="after")
    def validate_risk_flag_order(self) -> EvaluationSnapshot:
        _validate_risk_flags(self.risk_flags)
        return self


class TradeParameters(StrictFrozenModel):
    reference_price: Annotated[float, Field(gt=0)]
    atr_value_used: Annotated[float, Field(gt=0)]
    premarket_low_used: Annotated[float, Field(gt=0)]
    risk_stop_atr_multiple: Annotated[float, Field(ge=1.0, le=1.0)]
    profit_target_atr_multiple: Annotated[float, Field(ge=2.0, le=2.0)]
    invalidation_note: Literal[
        "Thesis is invalid if price breaks below the supplied premarket low before 9:35 AM ET."
    ]


class ApprovedSetup(StrictFrozenModel):
    ticker: CanonicalTicker
    side: Literal["long"]
    conviction_score: Annotated[int, Field(ge=0, le=100)]
    score_breakdown: ScoreBreakdown
    master_thesis: str
    catalyst_source: str
    source_type: SourceType
    source_timestamp: UTCZTimestamp
    catalyst_age_hours: Annotated[float, Field(ge=0)]
    corroborated: bool
    risk_flags: tuple[RiskFlag, ...]
    trade_parameters: TradeParameters

    @model_validator(mode="after")
    def validate_risk_flag_order(self) -> ApprovedSetup:
        _validate_risk_flags(self.risk_flags)
        return self


class QualifiedNotSelected(StrictFrozenModel):
    ticker: CanonicalTicker
    final_rank: Annotated[int, Field(ge=4)]
    conviction_score: Annotated[int, Field(ge=0, le=100)]
    score_breakdown: ScoreBreakdown
    catalyst_source: str
    source_type: SourceType
    source_timestamp: UTCZTimestamp
    catalyst_age_hours: Annotated[float, Field(ge=0)]
    corroborated: bool
    risk_flags: tuple[RiskFlag, ...]
    non_selection_reason_code: Literal["TOP_THREE_CAP"]

    @model_validator(mode="after")
    def validate_risk_flag_order(self) -> QualifiedNotSelected:
        _validate_risk_flags(self.risk_flags)
        return self


class ReasonObject(StrictFrozenModel):
    reason_code: ReasonCode
    field: str
    observed_value: str
    required_condition: str
    reason: str


class ExcludedTicker(StrictFrozenModel):
    ticker: CanonicalTicker
    primary_reason: ReasonObject
    additional_reasons: tuple[ReasonObject, ...]
    evaluation_snapshot: EvaluationSnapshot


class SchemaFailure(StrictFrozenModel):
    scope: SchemaFailureScope
    ticker: str | None
    field: str
    reason: str

    @model_validator(mode="after")
    def payload_scope_has_null_ticker(self) -> SchemaFailure:
        if self.scope == SchemaFailureScope.PAYLOAD and self.ticker is not None:
            raise ValueError("payload-scoped schema failure must use ticker=null")
        return self


class RunBlocker(StrictFrozenModel):
    blocker_code: BlockerCode
    field: str
    observed_value: str
    required_condition: str
    reason: str


class DaybreakOutput(StrictFrozenModel):
    run_status: RunStatus
    execution_timestamp: UTCZTimestamp | None
    payload_timestamp_used: UTCZTimestamp | None
    market_status: MarketStatus | None
    approved_setups: tuple[ApprovedSetup, ...]
    qualified_not_selected: tuple[QualifiedNotSelected, ...]
    excluded_tickers: tuple[ExcludedTicker, ...]
    schema_failures: tuple[SchemaFailure, ...]
    run_blockers: tuple[RunBlocker, ...]

    @model_validator(mode="after")
    def validate_status_shape(self) -> DaybreakOutput:
        if len(self.approved_setups) > 3:
            raise ValueError("approved_setups cannot exceed 3")
        if self.schema_failures and self.run_blockers:
            raise ValueError("schema_failures and run_blockers cannot both be nonempty")

        trading_arrays_nonempty = bool(
            self.approved_setups or self.qualified_not_selected or self.excluded_tickers
        )
        if (
            self.run_status
            in {
                RunStatus.SCHEMA_FAILURE,
                RunStatus.BLOCKED_MARKET,
                RunStatus.STALE_PAYLOAD,
            }
            and trading_arrays_nonempty
        ):
            raise ValueError("non-scoring status must have empty trading-result arrays")

        if self.run_status == RunStatus.SCHEMA_FAILURE:
            if not self.schema_failures:
                raise ValueError("schema_failure status requires schema_failures")
            if self.run_blockers:
                raise ValueError("schema_failure status requires empty run_blockers")
        else:
            if (
                self.execution_timestamp is None
                or self.payload_timestamp_used is None
                or self.market_status is None
            ):
                raise ValueError("non-schema-failure echoes must be non-null")
            if self.schema_failures:
                raise ValueError("non-schema-failure status requires empty schema_failures")

        if self.run_status == RunStatus.APPROVED and not self.approved_setups:
            raise ValueError("approved status requires at least one approved setup")
        if self.run_status == RunStatus.NO_SETUPS:
            if self.approved_setups or self.qualified_not_selected:
                raise ValueError("no_setups cannot contain passing tickers")
            if self.run_blockers:
                raise ValueError("no_setups requires empty run_blockers")
        if self.run_status == RunStatus.BLOCKED_MARKET:
            if not any(
                blocker.blocker_code == BlockerCode.MARKET_NOT_NORMAL
                for blocker in self.run_blockers
            ):
                raise ValueError("blocked_market requires MARKET_NOT_NORMAL blocker")
        if self.run_status == RunStatus.STALE_PAYLOAD:
            if any(
                blocker.blocker_code == BlockerCode.MARKET_NOT_NORMAL
                for blocker in self.run_blockers
            ):
                raise ValueError("MARKET_NOT_NORMAL takes precedence over stale_payload")
            if not any(
                blocker.blocker_code == BlockerCode.PAYLOAD_STALE for blocker in self.run_blockers
            ):
                raise ValueError("stale_payload requires PAYLOAD_STALE blocker")
        return self


def _validate_risk_flags(flags: tuple[RiskFlag, ...]) -> None:
    values = [flag.value if isinstance(flag, RiskFlag) else str(flag) for flag in flags]
    if len(values) != len(set(values)):
        raise ValueError("risk_flags must not contain duplicates")
    indexes = [RISK_FLAG_ORDER.index(value) for value in values]
    if indexes != sorted(indexes):
        raise ValueError("risk_flags must use canonical order")
