from __future__ import annotations

from daybreak.core.hashing import canonical_sha256
from daybreak_contracts.output_models import (
    ApprovedSetup,
    DaybreakOutput,
    ExcludedTicker,
    QualifiedNotSelected,
    ScoreBreakdown,
)

from .models import ShadowComparison, TickerDisagreement

TerminalRecord = ApprovedSetup | QualifiedNotSelected | ExcludedTicker


def _terminal_map(output: DaybreakOutput) -> dict[str, tuple[str, TerminalRecord]]:
    records: dict[str, tuple[str, TerminalRecord]] = {}
    for approved in output.approved_setups:
        records[approved.ticker] = ("approved", approved)
    for qualified in output.qualified_not_selected:
        records[qualified.ticker] = ("qualified_not_selected", qualified)
    for excluded in output.excluded_tickers:
        records[excluded.ticker] = ("excluded", excluded)
    return records


def _score(record: TerminalRecord) -> ScoreBreakdown:
    if isinstance(record, ExcludedTicker):
        return record.evaluation_snapshot
    return record.score_breakdown


def _conviction(record: TerminalRecord | None) -> int | None:
    return (
        record.conviction_score
        if isinstance(record, (ApprovedSetup, QualifiedNotSelected))
        else None
    )


def compare_outputs(
    *,
    primary_attempt_id: str,
    shadow_attempt_id: str,
    primary: DaybreakOutput,
    shadow: DaybreakOutput,
) -> ShadowComparison:
    p_dump = primary.model_dump(mode="json")
    s_dump = shadow.model_dump(mode="json")
    p_hash = canonical_sha256(p_dump)
    s_hash = canonical_sha256(s_dump)
    p_map = _terminal_map(primary)
    s_map = _terminal_map(shadow)
    disagreements: list[TickerDisagreement] = []
    for ticker in sorted(set(p_map) | set(s_map)):
        p_terminal, p_record = p_map.get(ticker, (None, None))
        s_terminal, s_record = s_map.get(ticker, (None, None))
        p_score = _score(p_record) if p_record is not None else None
        s_score = _score(s_record) if s_record is not None else None
        p_bucket = str(p_score.catalyst_magnitude_bucket) if p_score else None
        s_bucket = str(s_score.catalyst_magnitude_bucket) if s_score else None
        evidence_equal = None
        if p_score is not None and s_score is not None:
            evidence_equal = (
                p_score.magnitude_evidence_excerpt == s_score.magnitude_evidence_excerpt
                and p_score.magnitude_evidence_start_char == s_score.magnitude_evidence_start_char
                and p_score.magnitude_evidence_end_char == s_score.magnitude_evidence_end_char
            )
        if (
            p_terminal != s_terminal
            or p_bucket != s_bucket
            or _conviction(p_record) != _conviction(s_record)
            or evidence_equal is False
        ):
            disagreements.append(
                TickerDisagreement(
                    ticker=ticker,
                    primary_terminal=p_terminal,
                    shadow_terminal=s_terminal,
                    primary_magnitude_bucket=p_bucket,
                    shadow_magnitude_bucket=s_bucket,
                    primary_conviction_score=_conviction(p_record),
                    shadow_conviction_score=_conviction(s_record),
                    evidence_span_equal=evidence_equal,
                )
            )
    return ShadowComparison(
        primary_attempt_id=primary_attempt_id,
        shadow_attempt_id=shadow_attempt_id,
        exact_output_match=p_hash == s_hash,
        same_run_status=primary.run_status == shadow.run_status,
        same_approved_order=[x.ticker for x in primary.approved_setups]
        == [x.ticker for x in shadow.approved_setups],
        ticker_disagreements=tuple(disagreements),
        primary_output_hash=p_hash,
        shadow_output_hash=s_hash,
    )
