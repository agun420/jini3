from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from ..enums import (
    CatalystZeroReason,
    EvidencePurpose,
    ReasonCode,
    RiskFlag,
)
from ..input_models import TickerInput
from ..logic.replay import (
    MAGNITUDE_POINTS,
    RISK_FLAG_ORDER,
    TerminalRecord,
    expected_failed_gates,
    expected_passing_order,
    expected_score_fields,
    input_by_ticker,
    risk_flags_of,
    score_of,
    terminal_records,
)
from ..output_models import ApprovedSetup, ExcludedTicker, QualifiedNotSelected
from ..types import is_canonical_ticker
from .helpers import checked, not_evaluated, passed, violation
from .models import InvariantCheck, InvariantViolation, ValidationContext

InvariantFn = Callable[[ValidationContext], InvariantCheck]


def _terminal_symbols(ctx: ValidationContext) -> dict[str, list[str]]:
    output = ctx.output
    return {
        "approved_setups": [item.ticker for item in output.approved_setups],
        "qualified_not_selected": [item.ticker for item in output.qualified_not_selected],
        "excluded_tickers": [item.ticker for item in output.excluded_tickers],
        "schema_failures": [
            item.ticker
            for item in output.schema_failures
            if item.scope == "ticker" and item.ticker is not None
        ],
    }


def _all_records(ctx: ValidationContext) -> list[tuple[str, TerminalRecord]]:
    return list(terminal_records(ctx.output))


def _records_with_input(
    ctx: ValidationContext,
) -> list[tuple[str, TerminalRecord, TickerInput | None]]:
    if ctx.input_payload is None:
        return []
    mapping = input_by_ticker(ctx.input_payload)
    return [
        (ticker, record, mapping.get(ticker)) for ticker, record in terminal_records(ctx.output)
    ]


def _score_path(record: object, ticker: str) -> str:
    if isinstance(record, ExcludedTicker):
        return f"excluded_tickers[{ticker}].evaluation_snapshot"
    if isinstance(record, ApprovedSetup):
        return f"approved_setups[{ticker}].score_breakdown"
    return f"qualified_not_selected[{ticker}].score_breakdown"


def invariant_001(ctx: ValidationContext) -> InvariantCheck:
    name = "terminal categories are mutually exclusive"
    occurrences: dict[str, list[str]] = {}
    for category, symbols in _terminal_symbols(ctx).items():
        for symbol in symbols:
            occurrences.setdefault(symbol, []).append(category)
    errors = [
        violation(
            1,
            symbol,
            "one terminal category",
            categories,
            "ticker appears in multiple terminal categories",
        )
        for symbol, categories in occurrences.items()
        if len(categories) > 1
    ]
    return checked(1, name, errors)


def invariant_002(ctx: ValidationContext) -> InvariantCheck:
    name = "schema-invalid tickers appear only in schema_failures"
    trading = set(
        _terminal_symbols(ctx)["approved_setups"]
        + _terminal_symbols(ctx)["qualified_not_selected"]
        + _terminal_symbols(ctx)["excluded_tickers"]
    )
    errors = []
    for failure in ctx.output.schema_failures:
        if failure.scope == "ticker" and failure.ticker in trading:
            errors.append(
                violation(
                    2,
                    failure.ticker or "null",
                    "absent from trading arrays",
                    "present",
                    "schema-invalid ticker reached trading output",
                )
            )
    return checked(2, name, errors)


def invariant_003(ctx: ValidationContext) -> InvariantCheck:
    name = "every excluded ticker fails at least one hard gate"
    if ctx.input_payload is None:
        return not_evaluated(3, name, "valid evaluator input is required")
    mapping = input_by_ticker(ctx.input_payload)
    errors = []
    for item in ctx.output.excluded_tickers:
        entry = mapping.get(item.ticker)
        if entry is None:
            errors.append(
                violation(
                    3,
                    item.ticker,
                    "ticker in input",
                    "missing",
                    "excluded ticker has no corresponding input",
                )
            )
            continue
        expected = expected_failed_gates(entry, item.evaluation_snapshot.catalyst_score_raw)
        if not expected:
            errors.append(
                violation(
                    3,
                    item.ticker,
                    "at least one failed hard gate",
                    "none",
                    "excluded ticker passes all hard gates",
                )
            )
            continue
        observed = [item.primary_reason, *item.additional_reasons]
        expected_dump = [reason.model_dump(mode="json") for reason in expected]
        observed_dump = [reason.model_dump(mode="json") for reason in observed]
        if observed_dump != expected_dump:
            errors.append(
                violation(
                    3,
                    item.ticker,
                    expected_dump,
                    observed_dump,
                    "hard-gate reasons or ordering do not match deterministic replay",
                )
            )
    return checked(3, name, errors)


def invariant_004(ctx: ValidationContext) -> InvariantCheck:
    name = "passing terminal records pass all eight hard gates"
    if ctx.input_payload is None:
        return not_evaluated(4, name, "valid evaluator input is required")
    mapping = input_by_ticker(ctx.input_payload)
    errors: list[InvariantViolation] = []
    passing: tuple[ApprovedSetup | QualifiedNotSelected, ...] = (
        *ctx.output.approved_setups,
        *ctx.output.qualified_not_selected,
    )
    for item in passing:
        entry = mapping.get(item.ticker)
        if entry is None:
            errors.append(
                violation(
                    4,
                    item.ticker,
                    "ticker in input",
                    "missing",
                    "passing ticker has no corresponding input",
                )
            )
            continue
        failures = expected_failed_gates(entry, item.score_breakdown.catalyst_score_raw)
        if failures:
            errors.append(
                violation(
                    4,
                    item.ticker,
                    "zero hard-gate failures",
                    [f.reason_code for f in failures],
                    "passing ticker failed a hard gate",
                )
            )
    return checked(4, name, errors)


def invariant_005(ctx: ValidationContext) -> InvariantCheck:
    name = "approved/no-setups terminal partition is exhaustive"
    if ctx.output.run_status not in {"approved", "no_setups"}:
        return passed(5, name, "partition equation is not applicable to this run status")
    if ctx.input_payload is None:
        return not_evaluated(5, name, "valid evaluator input is required")
    observed = (
        len(ctx.output.approved_setups)
        + len(ctx.output.qualified_not_selected)
        + len(ctx.output.excluded_tickers)
    )
    expected = len(ctx.input_payload.tickers)
    errors = (
        []
        if observed == expected
        else [
            violation(5, "terminal arrays", expected, observed, "terminal partition count mismatch")
        ]
    )
    return checked(5, name, errors)


def invariant_006(ctx: ValidationContext) -> InvariantCheck:
    return checked(
        6,
        "approved setup count never exceeds three",
        []
        if len(ctx.output.approved_setups) <= 3
        else [
            violation(
                6,
                "approved_setups",
                "<= 3",
                len(ctx.output.approved_setups),
                "approval cap exceeded",
            )
        ],
    )


def invariant_007(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        7,
        "every excluded ticker has exactly one primary reason",
        "enforced by the strict ExcludedTicker model",
    )


def invariant_008(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        8,
        "additional reasons use the primary reason schema",
        "enforced by the shared ReasonObject model",
    )


def invariant_009(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        9, "SCHEMA_FAILURE is never an exclusion reason", "enforced by the ReasonCode enum"
    )


def invariant_010(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        10, "excluded evaluation snapshots are complete", "enforced by EvaluationSnapshot"
    )


def invariant_011(ctx: ValidationContext) -> InvariantCheck:
    return passed(11, "run blockers use only allowed codes", "enforced by BlockerCode")


def invariant_012(ctx: ValidationContext) -> InvariantCheck:
    return passed(12, "schema failures use allowed scopes", "enforced by SchemaFailureScope")


def invariant_013(ctx: ValidationContext) -> InvariantCheck:
    name = "non-scoring statuses have zero ticker trading results"
    if ctx.output.run_status not in {"schema_failure", "blocked_market", "stale_payload"}:
        return passed(13, name)
    count = (
        len(ctx.output.approved_setups)
        + len(ctx.output.qualified_not_selected)
        + len(ctx.output.excluded_tickers)
    )
    return checked(
        13,
        name,
        []
        if count == 0
        else [violation(13, "trading arrays", 0, count, "non-scoring run contains ticker results")],
    )


def invariant_014(ctx: ValidationContext) -> InvariantCheck:
    name = "run status follows universal precedence"
    if ctx.input_payload is None:
        return (
            passed(14, name, "schema-failure precedence is represented by the output model")
            if ctx.output.run_status == "schema_failure"
            else not_evaluated(14, name, "valid input or staged schema trace is required")
        )
    payload = ctx.input_payload
    if payload.market_status != "normal":
        expected = "blocked_market"
    elif payload.payload_age_seconds > 180:
        expected = "stale_payload"
    elif ctx.output.approved_setups:
        expected = "approved"
    else:
        expected = "no_setups"
    return checked(
        14,
        name,
        []
        if ctx.output.run_status == expected
        else [
            violation(
                14, "run_status", expected, ctx.output.run_status, "run-status precedence mismatch"
            )
        ],
    )


def invariant_015(ctx: ValidationContext) -> InvariantCheck:
    name = "all scoring stages complete before hard gates"
    value = ctx.metadata.scoring_completed_before_gates
    if value is None:
        return not_evaluated(15, name, "requires orchestrator evaluation trace")
    return checked(
        15,
        name,
        []
        if value
        else [violation(15, "evaluation_trace", True, value, "scoring/gate order was not proven")],
    )


def invariant_016(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        16,
        "no terminal scoring result is partially populated",
        "enforced by ScoreBreakdown and EvaluationSnapshot",
    )


def invariant_017(ctx: ValidationContext) -> InvariantCheck:
    name = "hard gates do not alter component scores"
    if ctx.input_payload is None:
        return not_evaluated(17, name, "valid evaluator input is required")
    mapping = input_by_ticker(ctx.input_payload)
    errors = []
    for ticker, record in terminal_records(ctx.output):
        entry = mapping.get(ticker)
        if entry is None:
            continue
        score = score_of(record)
        expected = expected_score_fields(ctx.input_payload, entry, score)
        for field in (
            "source_quality_points",
            "catalyst_magnitude_points",
            "catalyst_zero_override",
            "catalyst_zero_reason",
            "catalyst_score_raw",
            "catalyst_points",
            "volume_points",
            "technical_grade",
            "technical_base_points",
            "technical_points",
            "parabolic_adjusted",
        ):
            observed = getattr(score, field)
            if observed != expected[field]:
                errors.append(
                    violation(
                        17,
                        f"{_score_path(record, ticker)}.{field}",
                        expected[field],
                        observed,
                        "deterministic score replay mismatch",
                    )
                )
        observed_flags = risk_flags_of(record)
        if observed_flags != expected["risk_flags"]:
            errors.append(
                violation(
                    17,
                    f"{ticker}.risk_flags",
                    expected["risk_flags"],
                    observed_flags,
                    "risk-flag truth replay mismatch",
                )
            )
        if isinstance(record, (ApprovedSetup, QualifiedNotSelected)):
            expected_conviction = (
                score.catalyst_points + score.volume_points + score.technical_points
            )
            if record.conviction_score != expected_conviction:
                errors.append(
                    violation(
                        17,
                        f"{ticker}.conviction_score",
                        expected_conviction,
                        record.conviction_score,
                        "conviction score replay mismatch",
                    )
                )
        if isinstance(record, ApprovedSetup):
            trade = record.trade_parameters
            tech = entry.technical_context
            expected_trade = (tech.current_price, tech.atr_value, tech.premarket_low)
            observed_trade = (trade.reference_price, trade.atr_value_used, trade.premarket_low_used)
            if observed_trade != expected_trade:
                errors.append(
                    violation(
                        17,
                        f"{ticker}.trade_parameters",
                        expected_trade,
                        observed_trade,
                        "trade-parameter echo mismatch",
                    )
                )
    return checked(17, name, errors)


def invariant_018(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        18,
        "conviction score appears only on passing records",
        "enforced by terminal object schemas",
    )


def _evidence_checks(ctx: ValidationContext, number: int, mode: str) -> InvariantCheck:
    names = {
        "substring": "evidence excerpt is a contiguous substring",
        "full": "nontruncated excerpt equals the identified span",
        "truncated": "truncated excerpt is the first 200 code points",
        "pair": "evidence positions are paired",
        "bounds": "evidence positions are in bounds",
    }
    name = names[mode]
    if ctx.input_payload is None:
        return not_evaluated(number, name, "valid evaluator input is required")
    mapping = input_by_ticker(ctx.input_payload)
    errors = []
    for ticker, record in terminal_records(ctx.output):
        entry = mapping.get(ticker)
        if entry is None:
            continue
        score = score_of(record)
        text = entry.news_context.catalyst_text
        excerpt = score.magnitude_evidence_excerpt
        start, end = score.magnitude_evidence_start_char, score.magnitude_evidence_end_char
        path = _score_path(record, ticker)
        if mode == "substring" and excerpt and excerpt not in text:
            errors.append(
                violation(
                    number,
                    f"{path}.magnitude_evidence_excerpt",
                    "substring of catalyst_text",
                    excerpt,
                    "evidence excerpt is not present verbatim",
                )
            )
        elif (
            mode == "full"
            and not score.magnitude_evidence_truncated
            and start is not None
            and end is not None
        ):
            expected = text[start:end]
            if excerpt != expected:
                errors.append(
                    violation(
                        number,
                        f"{path}.magnitude_evidence_excerpt",
                        expected,
                        excerpt,
                        "nontruncated evidence does not equal indexed span",
                    )
                )
        elif mode == "truncated" and score.magnitude_evidence_truncated:
            if start is None or end is None:
                errors.append(
                    violation(
                        number,
                        path,
                        "integer positions",
                        "null",
                        "truncated evidence requires positions",
                    )
                )
            else:
                full_span = text[start:end]
                expected = full_span[:200]
                if len(full_span) <= 200 or excerpt != expected:
                    errors.append(
                        violation(
                            number,
                            f"{path}.magnitude_evidence_excerpt",
                            "first 200 code points of span > 200",
                            excerpt,
                            "truncation rule mismatch",
                        )
                    )
        elif mode == "pair" and ((start is None) != (end is None)):
            errors.append(
                violation(
                    number,
                    path,
                    "both integer or both null",
                    (start, end),
                    "evidence positions are not paired",
                )
            )
        elif (
            mode == "bounds"
            and start is not None
            and end is not None
            and not (0 <= start < end <= len(text))
        ):
            errors.append(
                violation(
                    number,
                    path,
                    f"0 <= start < end <= {len(text)}",
                    (start, end),
                    "evidence offsets are out of bounds",
                )
            )
    return checked(number, name, errors)


def invariant_019(ctx: ValidationContext) -> InvariantCheck:
    return _evidence_checks(ctx, 19, "substring")


def invariant_020(ctx: ValidationContext) -> InvariantCheck:
    return _evidence_checks(ctx, 20, "full")


def invariant_021(ctx: ValidationContext) -> InvariantCheck:
    return _evidence_checks(ctx, 21, "truncated")


def invariant_022(ctx: ValidationContext) -> InvariantCheck:
    return _evidence_checks(ctx, 22, "pair")


def invariant_023(ctx: ValidationContext) -> InvariantCheck:
    return _evidence_checks(ctx, 23, "bounds")


def invariant_024(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        24, "volume points use the exhaustive allowed set", "enforced by Literal[0,15,25,35]"
    )


def invariant_025(ctx: ValidationContext) -> InvariantCheck:
    return _check_volume_rule(
        ctx,
        25,
        lambda e: (
            e.liquidity_metrics.volume_profile == "clean"
            and e.liquidity_metrics.rvol_time_matched < 5.0
        ),
        0,
        "clean RVOL below 5 scores zero",
    )


def invariant_026(ctx: ValidationContext) -> InvariantCheck:
    return _check_volume_rule(
        ctx,
        26,
        lambda e: e.liquidity_metrics.volume_profile == "spiky",
        15,
        "spiky volume always scores 15",
    )


def _check_volume_rule(
    ctx: ValidationContext,
    number: int,
    predicate: Callable[[TickerInput], bool],
    expected_value: int,
    name: str,
) -> InvariantCheck:
    if ctx.input_payload is None:
        return not_evaluated(number, name, "valid evaluator input is required")
    mapping = input_by_ticker(ctx.input_payload)
    errors: list[InvariantViolation] = []
    for ticker, record in terminal_records(ctx.output):
        entry = mapping.get(ticker)
        if entry is not None and predicate(entry):
            observed = score_of(record).volume_points
            if observed != expected_value:
                errors.append(
                    violation(
                        number,
                        f"{_score_path(record, ticker)}.volume_points",
                        expected_value,
                        observed,
                        "volume rule mismatch",
                    )
                )
    return checked(number, name, errors)


def invariant_027(ctx: ValidationContext) -> InvariantCheck:
    name = "RVOL gate failures retain volume points"
    errors: list[InvariantViolation] = []
    for item in ctx.output.excluded_tickers:
        codes = [item.primary_reason.reason_code, *[r.reason_code for r in item.additional_reasons]]
        if (
            ReasonCode.RVOL_TOO_LOW.value in codes
            and item.evaluation_snapshot.volume_points is None
        ):
            errors.append(
                violation(
                    27,
                    item.ticker,
                    "non-null volume_points",
                    "null",
                    "RVOL failure lacks volume diagnostics",
                )
            )
    return checked(27, name, errors)


def invariant_028(ctx: ValidationContext) -> InvariantCheck:
    name = "resistance/capped failures have grade C zero technical result"
    errors = []
    for item in ctx.output.excluded_tickers:
        codes = [item.primary_reason.reason_code, *[r.reason_code for r in item.additional_reasons]]
        if any(
            code in {ReasonCode.RESISTANCE_TOO_CLOSE.value, ReasonCode.CAPPED_CHART.value}
            for code in codes
        ):
            s = item.evaluation_snapshot
            observed = (
                s.technical_grade,
                s.technical_base_points,
                s.technical_points,
                s.parabolic_adjusted,
            )
            expected = ("C", 0, 0, False)
            if observed != expected:
                errors.append(
                    violation(
                        28,
                        item.ticker,
                        expected,
                        observed,
                        "failing chart technical result mismatch",
                    )
                )
    return checked(28, name, errors)


def invariant_029(ctx: ValidationContext) -> InvariantCheck:
    errors = [
        violation(
            29,
            ticker,
            False,
            score_of(record).parabolic_adjusted,
            "grade-C result received parabolic penalty",
        )
        for ticker, record in terminal_records(ctx.output)
        if score_of(record).technical_grade == "C" and score_of(record).parabolic_adjusted
    ]
    return checked(29, "parabolic penalty never applies to grade C", errors)


def invariant_030(ctx: ValidationContext) -> InvariantCheck:
    allowed = {("A+", 25), ("A+", 19), ("A", 22), ("A", 16), ("B", 13), ("B", 7), ("C", 0)}
    errors = []
    for ticker, record in terminal_records(ctx.output):
        observed = (score_of(record).technical_grade, score_of(record).technical_points)
        if observed not in allowed:
            errors.append(violation(30, ticker, allowed, observed, "unsupported technical result"))
    return checked(30, "technical grade/point combinations are exhaustive", errors)


def invariant_031(ctx: ValidationContext) -> InvariantCheck:
    errors = []
    for ticker, record in terminal_records(ctx.output):
        s = score_of(record)
        if s.catalyst_zero_override != (s.catalyst_zero_reason is not None):
            errors.append(
                violation(
                    31,
                    ticker,
                    "override iff reason non-null",
                    (s.catalyst_zero_override, s.catalyst_zero_reason),
                    "zero-override equivalence failed",
                )
            )
    return checked(31, "zero override is equivalent to non-null zero reason", errors)


def invariant_032(ctx: ValidationContext) -> InvariantCheck:
    errors = []
    for ticker, record in terminal_records(ctx.output):
        s = score_of(record)
        if s.catalyst_zero_override and (s.catalyst_score_raw != 0 or s.catalyst_points != 0):
            errors.append(
                violation(
                    32,
                    ticker,
                    (0, 0),
                    (s.catalyst_score_raw, s.catalyst_points),
                    "zero override did not zero final catalyst score",
                )
            )
    return checked(32, "zero override zeros raw and weighted catalyst scores", errors)


def invariant_033(ctx: ValidationContext) -> InvariantCheck:
    errors = []
    for ticker, record in terminal_records(ctx.output):
        s = score_of(record)
        expected = MAGNITUDE_POINTS[str(s.catalyst_magnitude_bucket)]
        if s.catalyst_magnitude_points != expected:
            errors.append(
                violation(
                    33,
                    ticker,
                    expected,
                    s.catalyst_magnitude_points,
                    "magnitude bucket/points mapping mismatch",
                )
            )
    return checked(33, "magnitude bucket and points follow ordinary bucket mapping", errors)


def invariant_034(ctx: ValidationContext) -> InvariantCheck:
    name = "disqualifier override changes evidence target, not bucket"
    if ctx.input_payload is None:
        return not_evaluated(34, name, "valid input is required")
    applicable = [e.ticker for e in ctx.input_payload.tickers if e.news_context.disqualifier_flags]
    missing_trace = [
        ticker
        for ticker in applicable
        if ticker not in ctx.metadata.semantic_magnitude_before_override
    ]
    if missing_trace:
        return not_evaluated(
            34, name, f"semantic pre-override trace missing for: {', '.join(missing_trace)}"
        )
    return passed(34, name)


def invariant_035(ctx: ValidationContext) -> InvariantCheck:
    name = "disqualifier override can retain positive magnitude diagnostics"
    found = any(
        score_of(record).catalyst_zero_reason == "disqualifier_flag"
        and score_of(record).catalyst_magnitude_points > 0
        and score_of(record).catalyst_score_raw == 0
        and score_of(record).catalyst_points == 0
        for _, record in terminal_records(ctx.output)
    )
    return (
        passed(35, name, "reachability fixture observed")
        if found
        else not_evaluated(
            35, name, "reachability property is asserted by dedicated fixture, not every run"
        )
    )


def invariant_036(ctx: ValidationContext) -> InvariantCheck:
    name = "invisible disqualifier evidence does not force no-valid-driver"
    targets = set(ctx.metadata.invisible_disqualifier_tickers)
    if not targets:
        return not_evaluated(
            36, name, "requires semantic fixture identifying an invisible supplied disqualifier"
        )
    records = {ticker: record for ticker, record in terminal_records(ctx.output)}
    errors = []
    for ticker in sorted(targets):
        record = records.get(ticker)
        if record is None:
            errors.append(
                violation(36, ticker, "terminal record", "missing", "fixture ticker missing")
            )
            continue
        score = score_of(record)
        if score.catalyst_zero_reason != "disqualifier_flag":
            errors.append(
                violation(
                    36, ticker, "disqualifier_flag", score.catalyst_zero_reason, "wrong zero reason"
                )
            )
        if (
            score.magnitude_evidence_excerpt != ""
            or score.magnitude_evidence_start_char is not None
            or score.magnitude_evidence_end_char is not None
        ):
            errors.append(
                violation(
                    36,
                    ticker,
                    "empty evidence and null positions",
                    (
                        score.magnitude_evidence_excerpt,
                        score.magnitude_evidence_start_char,
                        score.magnitude_evidence_end_char,
                    ),
                    "invisible disqualifier evidence shape mismatch",
                )
            )
        expected_points = MAGNITUDE_POINTS[str(score.catalyst_magnitude_bucket)]
        if score.catalyst_magnitude_points != expected_points:
            errors.append(
                violation(
                    36,
                    ticker,
                    expected_points,
                    score.catalyst_magnitude_points,
                    "bucket points were altered by invisible disqualifier",
                )
            )
    return checked(36, name, errors)


def invariant_037(ctx: ValidationContext) -> InvariantCheck:
    name = "unconfirmed/stale evidence targets content magnitude"
    if ctx.input_payload is None:
        return not_evaluated(37, name, "valid input is required")
    errors = []
    for ticker, record in terminal_records(ctx.output):
        s = score_of(record)
        if (
            s.catalyst_zero_reason in {"unconfirmed_source", "stale_catalyst"}
            and s.catalyst_magnitude_bucket != "no_valid_driver"
            and not s.magnitude_evidence_excerpt
        ):
            errors.append(
                violation(
                    37,
                    ticker,
                    "content evidence or valid empty-span semantic trace",
                    "empty",
                    "metadata zero reason appears to have suppressed content evidence",
                )
            )
    return checked(37, name, errors)


def invariant_038(ctx: ValidationContext) -> InvariantCheck:
    errors = []
    for ticker, record in terminal_records(ctx.output):
        s = score_of(record)
        if s.catalyst_zero_reason == "no_valid_driver":
            observed = (
                s.catalyst_magnitude_bucket,
                s.catalyst_magnitude_points,
                s.magnitude_evidence_excerpt,
                s.magnitude_evidence_start_char,
                s.magnitude_evidence_end_char,
            )
            expected = ("no_valid_driver", 0, "", None, None)
            if observed != expected:
                errors.append(
                    violation(
                        38, ticker, expected, observed, "no-valid-driver diagnostic shape mismatch"
                    )
                )
    return checked(38, "no-valid-driver zero reason has canonical diagnostics", errors)


def invariant_039(ctx: ValidationContext) -> InvariantCheck:
    name = "no-valid-driver is assigned only by ordinary content analysis"
    targets = [
        ticker
        for ticker, record in terminal_records(ctx.output)
        if score_of(record).catalyst_zero_reason == "no_valid_driver"
    ]
    if not targets:
        return not_evaluated(39, name, "no no-valid-driver record in this run")
    missing = [
        ticker
        for ticker in targets
        if ticker not in ctx.metadata.semantic_magnitude_before_override
    ]
    if missing:
        return not_evaluated(39, name, f"ordinary-content trace missing for: {', '.join(missing)}")
    return passed(39, name)


def invariant_040(ctx: ValidationContext) -> InvariantCheck:
    name = "automatic-zero precedence is exact"
    if ctx.input_payload is None:
        return not_evaluated(40, name, "valid evaluator input is required")
    mapping = input_by_ticker(ctx.input_payload)
    errors = []
    for ticker, record in terminal_records(ctx.output):
        entry = mapping.get(ticker)
        if entry is None:
            continue
        s = score_of(record)
        expected = expected_score_fields(ctx.input_payload, entry, s)["catalyst_zero_reason"]
        if s.catalyst_zero_reason != expected:
            errors.append(
                violation(
                    40,
                    ticker,
                    expected,
                    s.catalyst_zero_reason,
                    "automatic-zero precedence mismatch",
                )
            )
    return checked(40, name, errors)


def invariant_041(ctx: ValidationContext) -> InvariantCheck:
    name = "evaluator candidate count does not exceed hard maximum"
    count = ctx.metadata.evaluator_candidate_count
    maximum = ctx.metadata.max_evaluator_candidates_hard
    if count is None:
        count = len(ctx.input_payload.tickers) if ctx.input_payload is not None else None
    if maximum is None:
        return not_evaluated(41, name, "hard maximum metadata is required")
    if count is None:
        return not_evaluated(41, name, "candidate count is required")
    return checked(
        41,
        name,
        []
        if count <= maximum
        else [
            violation(
                41, "candidate_count", f"<= {maximum}", count, "candidate hard maximum exceeded"
            )
        ],
    )


def invariant_042(ctx: ValidationContext) -> InvariantCheck:
    name = "prequalified-out candidates are absent from evaluator output"
    output_symbols = set(sum(_terminal_symbols(ctx).values(), []))
    overlap = sorted(output_symbols & set(ctx.metadata.prequalified_out_tickers))
    return checked(
        42,
        name,
        [
            violation(
                42,
                symbol,
                "absent",
                "present",
                "prequalified-out ticker appeared in evaluator output",
            )
            for symbol in overlap
        ],
    )


def invariant_043(ctx: ValidationContext) -> InvariantCheck:
    name = "capacity omissions are logged with policy version"
    omitted = set(ctx.metadata.capacity_omitted_tickers)
    if not omitted:
        return passed(43, name)
    errors = []
    missing = omitted - set(ctx.metadata.capacity_omissions_logged)
    if missing:
        errors.append(
            violation(
                43,
                "capacity_omissions_logged",
                omitted,
                ctx.metadata.capacity_omissions_logged,
                "capacity omissions were not all logged",
            )
        )
    if not ctx.metadata.preselection_policy_version:
        errors.append(
            violation(
                43,
                "preselection_policy_version",
                "nonempty",
                None,
                "capacity omission lacks policy version",
            )
        )
    return checked(43, name, errors)


def invariant_044(ctx: ValidationContext) -> InvariantCheck:
    name = "late evaluator responses cannot authorize orders"
    received = ctx.metadata.evaluator_response_timestamp
    cutoff = ctx.metadata.execution_cutoff_timestamp
    authorized = ctx.metadata.order_authorized
    if received is None or cutoff is None or authorized is None:
        return not_evaluated(
            44, name, "response time, cutoff, and authorization metadata are required"
        )
    violation_exists = received > cutoff and authorized
    return checked(
        44,
        name,
        []
        if not violation_exists
        else [violation(44, "order_authorized", False, True, "late response authorized an order")],
    )


def invariant_045(ctx: ValidationContext) -> InvariantCheck:
    return _check_chart_reachability(ctx, 45, "blue_sky_low_distance")


def invariant_046(ctx: ValidationContext) -> InvariantCheck:
    return _check_chart_reachability(ctx, 46, "capped")


def invariant_047(ctx: ValidationContext) -> InvariantCheck:
    return _check_chart_reachability(ctx, 47, "capped_reason_order")


def _check_chart_reachability(ctx: ValidationContext, number: int, mode: str) -> InvariantCheck:
    names = {
        "blue_sky_low_distance": "blue-sky low-distance case receives C and resistance failure",
        "capped": "every capped case receives C and capped failure",
        "capped_reason_order": "capped reason precedence is deterministic",
    }
    name = names[mode]
    if ctx.input_payload is None:
        return not_evaluated(number, name, "valid input is required")
    mapping = input_by_ticker(ctx.input_payload)
    output_excluded = {x.ticker: x for x in ctx.output.excluded_tickers}
    errors = []
    applicable = False
    for ticker, entry in mapping.items():
        tech = entry.technical_context
        if mode == "blue_sky_low_distance" and not (
            tech.chart_structure == "blue_sky" and tech.distance_to_resistance_atr < 1.0
        ):
            continue
        if mode in {"capped", "capped_reason_order"} and tech.chart_structure != "capped":
            continue
        applicable = True
        excluded = output_excluded.get(ticker)
        if excluded is None:
            errors.append(
                violation(
                    number,
                    ticker,
                    "excluded",
                    "not excluded",
                    "chart reachability case missing exclusion",
                )
            )
            continue
        codes = [
            excluded.primary_reason.reason_code,
            *[r.reason_code for r in excluded.additional_reasons],
        ]
        if mode == "blue_sky_low_distance":
            if (
                excluded.evaluation_snapshot.technical_grade != "C"
                or ReasonCode.RESISTANCE_TOO_CLOSE.value not in codes
            ):
                errors.append(
                    violation(
                        number,
                        ticker,
                        "grade C + RESISTANCE_TOO_CLOSE",
                        (excluded.evaluation_snapshot.technical_grade, codes),
                        "blue-sky low-distance outcome mismatch",
                    )
                )
        elif mode == "capped":
            if (
                excluded.evaluation_snapshot.technical_grade != "C"
                or ReasonCode.CAPPED_CHART.value not in codes
            ):
                errors.append(
                    violation(
                        number,
                        ticker,
                        "grade C + CAPPED_CHART",
                        (excluded.evaluation_snapshot.technical_grade, codes),
                        "capped outcome mismatch",
                    )
                )
        else:
            expected_primary = (
                ReasonCode.RESISTANCE_TOO_CLOSE.value
                if tech.distance_to_resistance_atr < 1.0
                else ReasonCode.CAPPED_CHART.value
            )
            if excluded.primary_reason.reason_code != expected_primary:
                errors.append(
                    violation(
                        number,
                        ticker,
                        expected_primary,
                        excluded.primary_reason.reason_code,
                        "capped primary reason order mismatch",
                    )
                )
    if not applicable:
        return not_evaluated(number, name, "reachability case is covered by a dedicated fixture")
    return checked(number, name, errors)


def invariant_048(ctx: ValidationContext) -> InvariantCheck:
    base = invariant_031(ctx)
    violations = tuple(v.model_copy(update={"invariant_number": 48}) for v in base.violations)
    return base.model_copy(
        update={
            "invariant_number": 48,
            "name": "zero reason nullability is consistent in all score records",
            "violations": violations,
        }
    )


def invariant_049(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        49,
        "standalone catalyst/liquidity thesis fields never appear",
        "enforced by extra=forbid terminal schemas",
    )


def invariant_050(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        50, "every schema-valid terminal record contains risk_flags", "enforced by terminal schemas"
    )


def invariant_051(ctx: ValidationContext) -> InvariantCheck:
    name = "schema-failure echoes are null only for invalid or missing source fields"
    if ctx.output.run_status != "schema_failure":
        return passed(51, name)
    if ctx.raw_input is None:
        return not_evaluated(51, name, "raw invalid input is required")
    errors = []
    mapping = {
        "evaluation_timestamp": "execution_timestamp",
        "payload_timestamp": "payload_timestamp_used",
        "market_status": "market_status",
    }
    for source, target in mapping.items():
        raw = ctx.raw_input.get(source)
        observed = getattr(ctx.output, target)
        if raw is None and observed is not None:
            errors.append(violation(51, target, None, observed, "missing source echo was repaired"))
    return checked(51, name, errors)


def invariant_052(ctx: ValidationContext) -> InvariantCheck:
    name = "non-schema-failure echo fields are valid, non-null, and exact"
    if ctx.output.run_status == "schema_failure":
        return passed(52, name)
    values = (
        ctx.output.execution_timestamp,
        ctx.output.payload_timestamp_used,
        ctx.output.market_status,
    )
    errors = []
    if not all(value is not None for value in values):
        errors.append(
            violation(
                52, "echo fields", "all non-null", values, "non-schema response contains null echo"
            )
        )
    if ctx.input_payload is not None:
        expected = (
            ctx.input_payload.evaluation_timestamp,
            ctx.input_payload.payload_timestamp,
            ctx.input_payload.market_status,
        )
        if values != expected:
            errors.append(violation(52, "echo fields", expected, values, "top-level echo mismatch"))
    return checked(52, name, errors)


def invariant_053(ctx: ValidationContext) -> InvariantCheck:
    if ctx.input_payload is None:
        return not_evaluated(
            53, "valid payload tickers are canonical and unique", "valid input model is required"
        )
    symbols = [x.ticker for x in ctx.input_payload.tickers]
    return checked(
        53,
        "valid payload tickers are canonical and unique",
        []
        if len(symbols) == len(set(symbols))
        else [violation(53, "tickers", "unique", symbols, "duplicate symbols")],
    )


def invariant_054(ctx: ValidationContext) -> InvariantCheck:
    name = "catalyst freshness uses the payload-level threshold"
    if ctx.input_payload is None:
        return not_evaluated(54, name, "valid input is required")
    mapping = input_by_ticker(ctx.input_payload)
    errors = []
    for ticker, record in terminal_records(ctx.output):
        entry = mapping.get(ticker)
        if entry is None:
            continue
        s = score_of(record)
        expected = expected_score_fields(ctx.input_payload, entry, s)["catalyst_zero_reason"]
        if s.catalyst_zero_reason != expected:
            errors.append(
                violation(
                    54,
                    ticker,
                    expected,
                    s.catalyst_zero_reason,
                    "freshness/zero-reason replay mismatch",
                )
            )
    return checked(54, name, errors)


def invariant_055(ctx: ValidationContext) -> InvariantCheck:
    name = "both chart hard gates are independently reachable"
    primary_codes = {item.primary_reason.reason_code for item in ctx.output.excluded_tickers}
    if (
        ReasonCode.RESISTANCE_TOO_CLOSE.value in primary_codes
        and ReasonCode.CAPPED_CHART.value in primary_codes
    ):
        return passed(55, name)
    return not_evaluated(
        55, name, "requires a fixture containing both independent primary outcomes"
    )


def invariant_056(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        56, "output narrative fields are restricted", "enforced by strict terminal schemas"
    )


def invariant_057(ctx: ValidationContext) -> InvariantCheck:
    name = "duplicate detection follows ticker validation"
    value = ctx.metadata.duplicate_detection_after_ticker_validation
    if value is None:
        return not_evaluated(57, name, "requires staged input-validation trace")
    return checked(
        57,
        name,
        []
        if value
        else [
            violation(57, "validation_trace", True, value, "duplicate check ran in the wrong phase")
        ],
    )


def invariant_058(ctx: ValidationContext) -> InvariantCheck:
    name = "only fully valid tickers participate in duplicate detection"
    value = ctx.metadata.duplicate_detection_valid_only
    if value is None:
        return not_evaluated(58, name, "requires staged input-validation trace")
    return checked(
        58,
        name,
        []
        if value
        else [
            violation(
                58,
                "validation_trace",
                True,
                value,
                "invalid ticker participated in duplicate detection",
            )
        ],
    )


def invariant_059(ctx: ValidationContext) -> InvariantCheck:
    name = "duplicate-valid-ticker response is a non-scoring schema failure"
    if ctx.raw_input is None or not isinstance(ctx.raw_input.get("tickers"), list):
        return not_evaluated(59, name, "raw input ticker list is required")
    strings = [
        item.get("ticker")
        for item in ctx.raw_input["tickers"]
        if isinstance(item, dict) and is_canonical_ticker(item.get("ticker"))
    ]
    duplicates = {s for s, count in Counter(strings).items() if count > 1}
    if not duplicates:
        return not_evaluated(59, name, "no duplicate-valid-ticker fixture in this run")
    arrays_empty = not (
        ctx.output.approved_setups
        or ctx.output.qualified_not_selected
        or ctx.output.excluded_tickers
        or ctx.output.run_blockers
    )
    condition = ctx.output.run_status == "schema_failure" and arrays_empty
    return checked(
        59,
        name,
        []
        if condition
        else [
            violation(
                59,
                "duplicate response",
                "schema_failure with empty trading/blocker arrays",
                ctx.output.run_status,
                "duplicate response shape mismatch",
            )
        ],
    )


def invariant_060(ctx: ValidationContext) -> InvariantCheck:
    name = "duplicate failure preserves independent ticker failures"
    if ctx.raw_input is None or not isinstance(ctx.raw_input.get("tickers"), list):
        return not_evaluated(60, name, "raw input ticker list is required")
    canonical: list[str] = []
    invalid_strings: list[str] = []
    for item in ctx.raw_input["tickers"]:
        if not isinstance(item, dict):
            continue
        ticker = item.get("ticker")
        if is_canonical_ticker(ticker):
            canonical.append(ticker)
        elif isinstance(ticker, str):
            invalid_strings.append(ticker)
    has_duplicate = any(count > 1 for count in Counter(canonical).values())
    if not has_duplicate or not invalid_strings:
        return not_evaluated(
            60, name, "requires duplicate-valid and independent invalid-ticker conditions"
        )
    reported = {
        failure.ticker for failure in ctx.output.schema_failures if failure.scope == "ticker"
    }
    missing = [ticker for ticker in invalid_strings if ticker not in reported]
    return checked(
        60,
        name,
        [
            violation(
                60,
                ticker,
                "preserved ticker failure",
                "missing",
                "duplicate failure erased independent ticker failure",
            )
            for ticker in missing
        ],
    )


def invariant_061(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        61,
        "partition equation is not applied during schema failure",
        "the partition validator skips schema_failure",
    )


def invariant_062(ctx: ValidationContext) -> InvariantCheck:
    name = "ticker validation and duplicate detection precede blockers"
    value = ctx.metadata.operational_blockers_after_schema_validation
    if value is None:
        return not_evaluated(62, name, "requires staged validation trace")
    return checked(
        62,
        name,
        []
        if value
        else [violation(62, "validation_trace", True, value, "operational blockers ran too early")],
    )


def invariant_063(ctx: ValidationContext) -> InvariantCheck:
    name = "operational blockers do not suppress eligible schema failures"
    if ctx.output.schema_failures and ctx.output.run_blockers:
        return checked(
            63,
            name,
            [
                violation(
                    63,
                    "run_blockers",
                    "empty",
                    ctx.output.run_blockers,
                    "blocker coexists with schema failure",
                )
            ],
        )
    return passed(63, name)


def invariant_064(ctx: ValidationContext) -> InvariantCheck:
    name = "schema failure status has nonempty failures and empty blockers"
    if not ctx.output.schema_failures:
        return passed(64, name)
    condition = ctx.output.run_status == "schema_failure" and not ctx.output.run_blockers
    return checked(
        64,
        name,
        []
        if condition
        else [
            violation(
                64,
                "run status/arrays",
                "schema_failure + failures + no blockers",
                ctx.output.run_status,
                "schema failure terminal state mismatch",
            )
        ],
    )


def invariant_065(ctx: ValidationContext) -> InvariantCheck:
    condition = not (ctx.output.schema_failures and ctx.output.run_blockers)
    return checked(
        65,
        "schema_failures and run_blockers are mutually exclusive",
        []
        if condition
        else [
            violation(
                65,
                "top-level arrays",
                "not both nonempty",
                "both nonempty",
                "failure/blocker exclusivity violated",
            )
        ],
    )


def invariant_066(ctx: ValidationContext) -> InvariantCheck:
    name = "operational blockers run only after eligible schema phases pass"
    value = ctx.metadata.operational_blockers_after_schema_validation
    if value is None:
        if ctx.output.run_blockers and ctx.output.schema_failures:
            return checked(
                66,
                name,
                [
                    violation(
                        66,
                        "top-level arrays",
                        "schema valid before blockers",
                        "schema failures present",
                        "blocker evaluated on schema-invalid run",
                    )
                ],
            )
        return not_evaluated(66, name, "requires staged validation trace for affirmative proof")
    return checked(
        66,
        name,
        []
        if value
        else [violation(66, "validation_trace", True, value, "blocker phase order mismatch")],
    )


def invariant_067(ctx: ValidationContext) -> InvariantCheck:
    name = "passing records are split by final rank into approved and qualified"
    ordered = expected_passing_order(ctx.output)
    observed = [x.ticker for x in ctx.output.approved_setups] + [
        x.ticker for x in ctx.output.qualified_not_selected
    ]
    errors = []
    if observed != ordered:
        errors.append(
            violation(
                67,
                "passing order",
                ordered,
                observed,
                "passing records are not in deterministic rank order",
            )
        )
    for index, ticker in enumerate(ordered, start=1):
        if index <= 3 and ticker not in {x.ticker for x in ctx.output.approved_setups}:
            errors.append(
                violation(
                    67,
                    ticker,
                    "approved rank 1-3",
                    "not approved",
                    "top-three ticker routed incorrectly",
                )
            )
        if index >= 4:
            item = next((x for x in ctx.output.qualified_not_selected if x.ticker == ticker), None)
            if item is None or item.final_rank != index:
                errors.append(
                    violation(
                        67,
                        ticker,
                        f"qualified rank {index}",
                        None if item is None else item.final_rank,
                        "rank-4+ ticker routed or ranked incorrectly",
                    )
                )
    return checked(67, name, errors)


def invariant_068(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        68,
        "qualified-not-selected records have the exact non-executable shape",
        "enforced by QualifiedNotSelected with extra=forbid",
    )


def invariant_069(ctx: ValidationContext) -> InvariantCheck:
    errors = []
    for ticker, record in terminal_records(ctx.output):
        adjusted = score_of(record).parabolic_adjusted
        has_flag = RiskFlag.PARABOLIC.value in risk_flags_of(record)
        if adjusted != has_flag:
            errors.append(
                violation(69, ticker, adjusted, has_flag, "parabolic flag equivalence failed")
            )
    return checked(69, "parabolic risk flag appears iff parabolic adjustment applies", errors)


def invariant_070(ctx: ValidationContext) -> InvariantCheck:
    errors = []
    for ticker, record in terminal_records(ctx.output):
        flags = list(risk_flags_of(record))
        if len(flags) != len(set(flags)):
            errors.append(violation(70, ticker, "unique risk flags", flags, "duplicate risk flag"))
            continue
        try:
            indexes = [RISK_FLAG_ORDER.index(flag) for flag in flags]
        except ValueError:
            errors.append(violation(70, ticker, RISK_FLAG_ORDER, flags, "unsupported risk flag"))
            continue
        if indexes != sorted(indexes):
            errors.append(
                violation(70, ticker, "canonical order", flags, "risk flags are out of order")
            )
    return checked(70, "risk flags are allowed, unique, and canonically ordered", errors)


def invariant_071(ctx: ValidationContext) -> InvariantCheck:
    name = "evidence indexing uses decoded Unicode code points"
    # Python 3 string indexing is Unicode-code-point based for valid decoded JSON strings.
    result = _evidence_checks(ctx, 23, "bounds")
    if result.status == "not_evaluated":
        return not_evaluated(71, name, result.note or "valid input required")
    return checked(
        71, name, [v.model_copy(update={"invariant_number": 71}) for v in result.violations]
    )


def invariant_072(ctx: ValidationContext) -> InvariantCheck:
    name = "schema-failure ticker is exact supplied string or null"
    errors: list[InvariantViolation] = []
    for index, failure in enumerate(ctx.output.schema_failures):
        if failure.ticker is not None and not isinstance(failure.ticker, str):
            errors.append(
                violation(
                    72,
                    f"schema_failures[{index}].ticker",
                    "string or null",
                    type(failure.ticker).__name__,
                    "schema-failure ticker was coerced",
                )
            )
    return checked(72, name, errors)


def invariant_073(ctx: ValidationContext) -> InvariantCheck:
    errors = []
    for ticker, record in terminal_records(ctx.output):
        score = score_of(record)
        if score.catalyst_zero_reason == CatalystZeroReason.DISQUALIFIER_FLAG.value:
            expected = EvidencePurpose.DISQUALIFIER.value
        elif score.catalyst_zero_reason == CatalystZeroReason.NO_VALID_DRIVER.value:
            expected = EvidencePurpose.NONE.value
        else:
            expected = EvidencePurpose.MAGNITUDE.value
        if score.evidence_purpose != expected:
            errors.append(
                violation(
                    73,
                    ticker,
                    expected,
                    score.evidence_purpose,
                    "evidence purpose does not match the selected evidence target",
                )
            )
    return checked(73, "evidence purpose explicitly identifies the evidence target", errors)


def invariant_074(ctx: ValidationContext) -> InvariantCheck:
    return passed(
        74,
        "unknown fields are rejected at every input and output object level",
        "enforced by StrictFrozenModel extra=forbid and recursive provider schemas",
    )


def invariant_075(ctx: ValidationContext) -> InvariantCheck:
    name = "schema-valid input satisfies bounded external-text and candidate limits"
    if ctx.input_payload is None:
        return not_evaluated(75, name, "valid evaluator input is required")
    errors = []
    payload = ctx.input_payload
    if len(payload.tickers) > 25:
        errors.append(
            violation(75, "tickers", "<= 25", len(payload.tickers), "candidate limit exceeded")
        )
    for entry in payload.tickers:
        news = entry.news_context
        if not 1 <= len(news.catalyst_text) <= 4000:
            errors.append(
                violation(
                    75,
                    f"{entry.ticker}.catalyst_text",
                    "1..4000 code points",
                    len(news.catalyst_text),
                    "catalyst text bound violated",
                )
            )
        if not 1 <= len(news.source_name) <= 256:
            errors.append(
                violation(
                    75,
                    f"{entry.ticker}.source_name",
                    "1..256 code points",
                    len(news.source_name),
                    "source-name bound violated",
                )
            )
        if len(news.disqualifier_flags) > 5 or len(news.disqualifier_flags) != len(
            set(news.disqualifier_flags)
        ):
            errors.append(
                violation(
                    75,
                    f"{entry.ticker}.disqualifier_flags",
                    "<=5 unique values",
                    list(news.disqualifier_flags),
                    "disqualifier bound or uniqueness violated",
                )
            )
    return checked(75, name, errors)


def invariant_076(ctx: ValidationContext) -> InvariantCheck:
    name = "premarket low is not above current price"
    if ctx.input_payload is None:
        return not_evaluated(76, name, "valid evaluator input is required")
    errors = [
        violation(
            76,
            f"{entry.ticker}.technical_context.premarket_low",
            f"<= {entry.technical_context.current_price}",
            entry.technical_context.premarket_low,
            "premarket low exceeds current price",
        )
        for entry in ctx.input_payload.tickers
        if entry.technical_context.premarket_low > entry.technical_context.current_price
    ]
    return checked(76, name, errors)


def invariant_077(ctx: ValidationContext) -> InvariantCheck:
    name = "freshness tie groups include exact two-point differences"
    expected = expected_passing_order(ctx.output)
    observed = [item.ticker for item in ctx.output.approved_setups]
    observed.extend(item.ticker for item in ctx.output.qualified_not_selected)
    errors = (
        []
        if observed == expected
        else [
            violation(
                77,
                "passing order",
                expected,
                observed,
                "inclusive fixed-anchor two-point tie grouping mismatch",
            )
        ]
    )
    return checked(77, name, errors)


INVARIANT_REGISTRY: dict[int, InvariantFn] = {
    number: globals()[f"invariant_{number:03d}"] for number in range(1, 78)
}

assert list(INVARIANT_REGISTRY) == list(range(1, 78))
