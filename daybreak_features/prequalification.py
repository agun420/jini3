"""Deterministic prequalification and structured oversubscription ranking."""

from __future__ import annotations

from .models import CandidateFeatures, FeatureEngineConfig, PrequalificationDecision


def prequalify(
    features: CandidateFeatures, config: FeatureEngineConfig
) -> PrequalificationDecision:
    reasons: list[str] = []
    if features.halted:
        reasons.append("HALTED")
    if features.gap_pct < config.gap_min_pct:
        reasons.append("GAP_TOO_SMALL")
    if features.premarket_volume < config.premarket_volume_min:
        reasons.append("PREMARKET_VOLUME_TOO_LOW")
    if features.rvol_time_matched < config.rvol_min:
        reasons.append("RVOL_TOO_LOW")
    if features.resistance.distance_to_resistance_atr < config.resistance_min_atr:
        reasons.append("RESISTANCE_TOO_CLOSE")
    if features.resistance.chart_structure == "capped":
        reasons.append("CAPPED_CHART")
    if features.catalyst.source_type == "unconfirmed":
        reasons.append("UNCONFIRMED_SOURCE")
    if features.catalyst.disqualifier_flags:
        reasons.append("DISQUALIFYING_CATALYST")
    return PrequalificationDecision(
        ticker=features.ticker,
        accepted=not reasons,
        reason_codes=tuple(reasons),
        feature_source_hash=features.feature_source_hash,
    )


def capacity_sort_key(features: CandidateFeatures) -> tuple[object, ...]:
    return (
        0 if features.catalyst.source_type == "primary" else 1,
        0 if features.catalyst.corroborated else 1,
        0 if features.volume_profile == "clean" else 1,
        features.catalyst_age_hours,
        -features.rvol_time_matched,
        -features.premarket_volume,
        -features.resistance.distance_to_resistance_atr,
        features.ticker,
    )
