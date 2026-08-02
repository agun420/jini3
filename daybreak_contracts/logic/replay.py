from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..enums import (
    BorrowStatus,
    CatalystZeroReason,
    ChartStructure,
    EvidencePurpose,
    MagnitudeBucket,
    ReasonCode,
    RiskFlag,
    SourceType,
    TechnicalGrade,
    VolumeProfile,
)
from ..input_models import DaybreakInput, TickerInput
from ..output_models import (
    ApprovedSetup,
    DaybreakOutput,
    ExcludedTicker,
    QualifiedNotSelected,
    ReasonObject,
    ScoreBreakdown,
)

TerminalRecord = ApprovedSetup | QualifiedNotSelected | ExcludedTicker

MAGNITUDE_POINTS = {
    MagnitudeBucket.MAJOR_CONCRETE.value: 4,
    MagnitudeBucket.MATERIAL_PARTIALLY_QUANTIFIED.value: 3,
    MagnitudeBucket.CREDIBLE_UNQUANTIFIED.value: 2,
    MagnitudeBucket.WEAK_OR_PRELIMINARY.value: 1,
    MagnitudeBucket.NO_VALID_DRIVER.value: 0,
}

RISK_FLAG_ORDER = [
    RiskFlag.PARABOLIC.value,
    RiskFlag.HARD_TO_BORROW.value,
    RiskFlag.UNKNOWN_BORROW.value,
    RiskFlag.LOW_FLOAT.value,
    RiskFlag.SPIKY_VOLUME.value,
    RiskFlag.SECONDARY_SOURCE.value,
]


@dataclass(frozen=True)
class ExpectedTechnical:
    grade: str
    base_points: int
    points: int
    parabolic_adjusted: bool


@dataclass(frozen=True)
class PassingRecord:
    ticker: str
    conviction_score: int
    catalyst_age_hours: float
    catalyst_score_raw: int
    volume_points: int
    technical_points: int


def input_by_ticker(payload: DaybreakInput) -> dict[str, TickerInput]:
    return {entry.ticker: entry for entry in payload.tickers}


def terminal_records(output: DaybreakOutput) -> Iterable[tuple[str, TerminalRecord]]:
    for approved in output.approved_setups:
        yield approved.ticker, approved
    for qualified in output.qualified_not_selected:
        yield qualified.ticker, qualified
    for excluded in output.excluded_tickers:
        yield excluded.ticker, excluded


def score_of(record: object) -> ScoreBreakdown:
    if isinstance(record, ExcludedTicker):
        return record.evaluation_snapshot
    if isinstance(record, (ApprovedSetup, QualifiedNotSelected)):
        return record.score_breakdown
    raise TypeError(type(record))


def risk_flags_of(record: object) -> tuple[str, ...]:
    if isinstance(record, ExcludedTicker):
        return tuple(record.evaluation_snapshot.risk_flags)
    if isinstance(record, (ApprovedSetup, QualifiedNotSelected)):
        return tuple(record.risk_flags)
    raise TypeError(type(record))


def expected_source_quality(entry: TickerInput) -> int:
    news = entry.news_context
    if news.source_type == SourceType.PRIMARY:
        return 6
    if news.source_type == SourceType.SECONDARY:
        return 4 if news.corroborated else 2
    return 0


def expected_zero_reason(
    payload: DaybreakInput,
    entry: TickerInput,
    bucket: str,
) -> str | None:
    news = entry.news_context
    if news.disqualifier_flags:
        return CatalystZeroReason.DISQUALIFIER_FLAG.value
    if news.source_type == SourceType.UNCONFIRMED:
        return CatalystZeroReason.UNCONFIRMED_SOURCE.value
    if news.catalyst_age_hours > payload.catalyst_freshness_threshold_hours:
        return CatalystZeroReason.STALE_CATALYST.value
    if bucket == MagnitudeBucket.NO_VALID_DRIVER.value:
        return CatalystZeroReason.NO_VALID_DRIVER.value
    return None


def expected_evidence_purpose(zero_reason: str | None) -> str:
    if zero_reason == CatalystZeroReason.DISQUALIFIER_FLAG.value:
        return EvidencePurpose.DISQUALIFIER.value
    if zero_reason == CatalystZeroReason.NO_VALID_DRIVER.value:
        return EvidencePurpose.NONE.value
    return EvidencePurpose.MAGNITUDE.value


def expected_volume_points(entry: TickerInput) -> int:
    liq = entry.liquidity_metrics
    if liq.volume_profile == VolumeProfile.SPIKY:
        return 15
    if liq.rvol_time_matched < 5.0:
        return 0
    if liq.rvol_time_matched <= 10.0:
        return 25
    return 35


def expected_technical(entry: TickerInput) -> ExpectedTechnical:
    tech = entry.technical_context
    if tech.distance_to_resistance_atr < 1.0 or tech.chart_structure == ChartStructure.CAPPED:
        return ExpectedTechnical(TechnicalGrade.C.value, 0, 0, False)

    if tech.chart_structure == ChartStructure.BLUE_SKY:
        grade, base = TechnicalGrade.A_PLUS.value, 25
    elif tech.chart_structure == ChartStructure.CLEAN_SHORT_TERM:
        grade, base = TechnicalGrade.A.value, 22
    elif tech.chart_structure == ChartStructure.MODERATE_ROOM:
        grade, base = TechnicalGrade.B.value, 13
    else:
        raise ValueError(f"unreachable chart structure: {tech.chart_structure}")

    adjusted = tech.distance_from_vwap_atr > 3.0
    return ExpectedTechnical(grade, base, base - 6 if adjusted else base, adjusted)


def expected_risk_flags(entry: TickerInput, technical: ExpectedTechnical) -> tuple[str, ...]:
    flags: list[str] = []
    liq = entry.liquidity_metrics
    news = entry.news_context
    if technical.parabolic_adjusted:
        flags.append(RiskFlag.PARABOLIC.value)
    if liq.borrow_status == BorrowStatus.HARD_TO_BORROW:
        flags.append(RiskFlag.HARD_TO_BORROW.value)
    if liq.borrow_status == BorrowStatus.UNKNOWN:
        flags.append(RiskFlag.UNKNOWN_BORROW.value)
    if liq.float_shares < 50_000_000:
        flags.append(RiskFlag.LOW_FLOAT.value)
    if liq.volume_profile == VolumeProfile.SPIKY:
        flags.append(RiskFlag.SPIKY_VOLUME.value)
    if news.source_type == SourceType.SECONDARY:
        flags.append(RiskFlag.SECONDARY_SOURCE.value)
    return tuple(flags)


def expected_score_fields(
    payload: DaybreakInput,
    entry: TickerInput,
    reported: ScoreBreakdown,
) -> dict[str, object]:
    source_points = expected_source_quality(entry)
    bucket = str(reported.catalyst_magnitude_bucket)
    magnitude_points = MAGNITUDE_POINTS[bucket]
    zero_reason = expected_zero_reason(payload, entry, bucket)
    if zero_reason is None:
        raw = source_points + magnitude_points
        catalyst_points = raw * 4
    else:
        raw = 0
        catalyst_points = 0
    technical = expected_technical(entry)
    return {
        "source_quality_points": source_points,
        "catalyst_magnitude_points": magnitude_points,
        "catalyst_zero_override": zero_reason is not None,
        "catalyst_zero_reason": zero_reason,
        "evidence_purpose": expected_evidence_purpose(zero_reason),
        "catalyst_score_raw": raw,
        "catalyst_points": catalyst_points,
        "volume_points": expected_volume_points(entry),
        "technical_grade": technical.grade,
        "technical_base_points": technical.base_points,
        "technical_points": technical.points,
        "parabolic_adjusted": technical.parabolic_adjusted,
        "risk_flags": expected_risk_flags(entry, technical),
    }


def _number_string(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def expected_failed_gates(entry: TickerInput, catalyst_score_raw: int) -> list[ReasonObject]:
    liq = entry.liquidity_metrics
    tech = entry.technical_context
    news = entry.news_context
    failures: list[ReasonObject] = []

    def add(code: ReasonCode, field: str, observed: object, condition: str, reason: str) -> None:
        failures.append(
            ReasonObject(
                reason_code=code,
                field=field,
                observed_value=_number_string(observed),
                required_condition=condition,
                reason=reason,
            )
        )

    if entry.halted:
        add(
            ReasonCode.HALTED,
            "halted",
            entry.halted,
            "halted must equal false",
            "The ticker is halted and cannot be approved.",
        )
    if catalyst_score_raw < 7:
        add(
            ReasonCode.CATALYST_SCORE_TOO_LOW,
            "news_context.catalyst_score_raw",
            catalyst_score_raw,
            "catalyst_score_raw must be greater than or equal to 7",
            "The catalyst score is below the required minimum.",
        )
    if not news.corroborated and catalyst_score_raw < 9:
        add(
            ReasonCode.UNCORROBORATED_CATALYST,
            "news_context.corroborated",
            news.corroborated,
            "uncorroborated catalysts require catalyst_score_raw greater than or equal to 9",
            "The uncorroborated catalyst does not meet the stricter score requirement.",
        )
    if liq.gap_pct < 4.0:
        add(
            ReasonCode.GAP_TOO_SMALL,
            "liquidity_metrics.gap_pct",
            liq.gap_pct,
            "gap_pct must be greater than or equal to 4.0",
            "The premarket gap is below the required minimum.",
        )
    if liq.premarket_volume < 500_000:
        add(
            ReasonCode.PREMARKET_VOLUME_TOO_LOW,
            "liquidity_metrics.premarket_volume",
            liq.premarket_volume,
            "premarket_volume must be greater than or equal to 500000",
            "Premarket volume is below the required minimum.",
        )
    if liq.rvol_time_matched < 5.0:
        add(
            ReasonCode.RVOL_TOO_LOW,
            "liquidity_metrics.rvol_time_matched",
            liq.rvol_time_matched,
            "rvol_time_matched must be greater than or equal to 5.0",
            "Time-matched RVOL is below the required minimum.",
        )
    if tech.distance_to_resistance_atr < 1.0:
        add(
            ReasonCode.RESISTANCE_TOO_CLOSE,
            "technical_context.distance_to_resistance_atr",
            tech.distance_to_resistance_atr,
            "distance_to_resistance_atr must be greater than or equal to 1.0",
            "The ticker has insufficient room before resistance.",
        )
    if tech.chart_structure == ChartStructure.CAPPED:
        add(
            ReasonCode.CAPPED_CHART,
            "technical_context.chart_structure",
            tech.chart_structure,
            "chart_structure must not equal capped",
            "The chart is capped by nearby structural resistance.",
        )
    return failures


def passing_records(output: DaybreakOutput) -> list[PassingRecord]:
    records: list[PassingRecord] = []
    passing: tuple[ApprovedSetup | QualifiedNotSelected, ...] = (
        *output.approved_setups,
        *output.qualified_not_selected,
    )
    for record in passing:
        score = record.score_breakdown
        records.append(
            PassingRecord(
                ticker=record.ticker,
                conviction_score=record.conviction_score,
                catalyst_age_hours=record.catalyst_age_hours,
                catalyst_score_raw=score.catalyst_score_raw,
                volume_points=score.volume_points,
                technical_points=score.technical_points,
            )
        )
    return records


def expected_passing_order(output: DaybreakOutput) -> list[str]:
    remaining = sorted(
        passing_records(output),
        key=lambda item: (-item.conviction_score, item.ticker),
    )
    ranked: list[PassingRecord] = []
    while remaining:
        anchor = remaining[0].conviction_score
        group = [item for item in remaining if anchor - item.conviction_score <= 2]
        group_set = {item.ticker for item in group}
        remaining = [item for item in remaining if item.ticker not in group_set]
        group.sort(
            key=lambda item: (
                item.catalyst_age_hours,
                -item.catalyst_score_raw,
                -item.volume_points,
                -item.technical_points,
                item.ticker,
            )
        )
        ranked.extend(group)
    return [item.ticker for item in ranked]
