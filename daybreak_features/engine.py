"""End-to-end deterministic feature snapshot construction."""

from __future__ import annotations

from datetime import UTC, datetime

from daybreak_contracts.enums import BorrowStatus as ContractBorrowStatus
from daybreak_contracts.enums import ChartStructure as ContractChartStructure
from daybreak_contracts.enums import DisqualifierFlag as ContractDisqualifierFlag
from daybreak_contracts.enums import MarketStatus as ContractMarketStatus
from daybreak_contracts.enums import SourceType as ContractSourceType
from daybreak_contracts.enums import VolumeProfile as ContractVolumeProfile
from daybreak_contracts.input_models import (
    DaybreakInput,
    LiquidityMetrics,
    NewsContext,
    TechnicalContext,
    TickerInput,
)

from .canonical import canonical_sha256
from .core_features import (
    current_price,
    current_session_trades,
    distance_from_vwap_atr,
    gap_pct,
    premarket_low,
    premarket_volume,
    premarket_vwap,
    rvol_time_matched,
    volume_profile,
    wilder_atr_14,
)
from .errors import DataQualityError
from .joins import select_catalyst, select_float_record
from .models import (
    CandidateFeatures,
    CandidateSourceData,
    CapacityOmission,
    FeatureContext,
    FeatureSnapshot,
    PrequalificationDecision,
)
from .prequalification import capacity_sort_key, prequalify
from .resistance import daily_pivot_cluster_v1


def _utc_z(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be aware UTC")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _calculate_candidate(context: FeatureContext, source: CandidateSourceData) -> CandidateFeatures:
    trades = current_session_trades(
        source.current_session_events, context.payload_timestamp, context.config
    )
    price = current_price(trades)
    low = premarket_low(trades)
    volume = premarket_volume(trades)
    atr = wilder_atr_14(source.daily_bars)
    vwap = premarket_vwap(trades)
    rvol = rvol_time_matched(
        volume,
        source.historical_premarket_sessions,
        context.payload_timestamp,
        context.config,
    )
    profile = volume_profile(trades, context.payload_timestamp, context.config)
    resistance = daily_pivot_cluster_v1(
        bars=source.daily_bars,
        current_price=price,
        atr=atr,
        history_complete_since_listing=source.history_complete_since_listing,
        config=context.config,
    )
    float_record = select_float_record(
        source.float_records,
        ticker=source.ticker,
        snapshot=context.payload_timestamp,
        config=context.config,
    )
    catalyst, catalyst_age = select_catalyst(
        source.catalysts, ticker=source.ticker, snapshot=context.payload_timestamp
    )
    source_material = {
        "ticker": source.ticker,
        "events": source.current_session_events,
        "historical_sessions": source.historical_premarket_sessions,
        "daily_bars": source.daily_bars,
        "float_record": float_record,
        "catalyst": catalyst,
        "config": context.config,
        "payload_timestamp": context.payload_timestamp,
    }
    return CandidateFeatures(
        ticker=source.ticker,
        halted=source.halted,
        current_price=price,
        premarket_low=low,
        gap_pct=gap_pct(price, source.previous_regular_close),
        premarket_volume=volume,
        rvol_time_matched=rvol,
        atr_value=atr,
        premarket_vwap=vwap,
        distance_from_vwap_atr=distance_from_vwap_atr(price, vwap, atr),
        volume_profile=profile,
        float_shares=float_record.float_shares,
        borrow_status=source.borrow_status,
        resistance=resistance,
        catalyst=catalyst,
        catalyst_age_hours=catalyst_age,
        feature_source_hash=canonical_sha256(source_material),
    )


def _ticker_input(features: CandidateFeatures) -> TickerInput:
    catalyst = features.catalyst
    return TickerInput(
        ticker=features.ticker,
        halted=features.halted,
        news_context=NewsContext(
            catalyst_text=catalyst.catalyst_text,
            source_type=ContractSourceType(catalyst.source_type.value),
            source_name=catalyst.source_name,
            source_timestamp=_utc_z(catalyst.source_timestamp),
            catalyst_age_hours=float(features.catalyst_age_hours),
            corroborated=catalyst.corroborated,
            disqualifier_flags=tuple(
                ContractDisqualifierFlag(flag) for flag in catalyst.disqualifier_flags
            ),
        ),
        liquidity_metrics=LiquidityMetrics(
            gap_pct=float(features.gap_pct),
            premarket_volume=features.premarket_volume,
            rvol_time_matched=float(features.rvol_time_matched),
            float_shares=features.float_shares,
            volume_profile=ContractVolumeProfile(features.volume_profile),
            borrow_status=ContractBorrowStatus(features.borrow_status.value),
        ),
        technical_context=TechnicalContext(
            distance_to_resistance_atr=float(features.resistance.distance_to_resistance_atr),
            distance_from_vwap_atr=float(features.distance_from_vwap_atr),
            chart_structure=ContractChartStructure(features.resistance.chart_structure),
            current_price=float(features.current_price),
            atr_value=float(features.atr_value),
            premarket_low=float(features.premarket_low),
        ),
    )


def build_feature_snapshot(context: FeatureContext) -> FeatureSnapshot:
    decisions: list[PrequalificationDecision] = []
    successful: list[CandidateFeatures] = []

    for source in sorted(context.candidates, key=lambda item: item.ticker):
        try:
            features = _calculate_candidate(context, source)
        except DataQualityError as exc:
            decisions.append(
                PrequalificationDecision(
                    ticker=source.ticker,
                    accepted=False,
                    reason_codes=(exc.code,),
                )
            )
            continue

        decision = prequalify(features, context.config)
        reasons = list(decision.reason_codes)
        if features.catalyst_age_hours > context.catalyst_freshness_threshold_hours:
            reasons.append("STALE_CATALYST")
        decision = PrequalificationDecision(
            ticker=features.ticker,
            accepted=not reasons,
            reason_codes=tuple(reasons),
            feature_source_hash=features.feature_source_hash,
        )
        decisions.append(decision)
        if decision.accepted:
            successful.append(features)

    ranked = sorted(successful, key=capacity_sort_key)
    selected = ranked[: context.config.max_evaluator_candidates]
    omitted = ranked[context.config.max_evaluator_candidates :]
    omissions = tuple(
        CapacityOmission(
            ticker=features.ticker,
            final_capacity_rank=index,
        )
        for index, features in enumerate(omitted, start=context.config.max_evaluator_candidates + 1)
    )

    payload_age = int((context.evaluation_timestamp - context.payload_timestamp).total_seconds())
    payload = DaybreakInput(
        evaluation_timestamp=_utc_z(context.evaluation_timestamp),
        payload_timestamp=_utc_z(context.payload_timestamp),
        payload_age_seconds=payload_age,
        catalyst_freshness_threshold_hours=float(context.catalyst_freshness_threshold_hours),
        market_status=ContractMarketStatus(context.market_status),
        tickers=tuple(_ticker_input(features) for features in selected),
    )
    context_hash = canonical_sha256(context)
    configuration_hash = canonical_sha256(context.config)
    feature_hash = canonical_sha256(selected)
    payload_hash = canonical_sha256(payload)
    audit_hash = canonical_sha256({"prequalification": decisions, "capacity_omissions": omissions})
    snapshot_id = canonical_sha256(
        {
            "context_hash": context_hash,
            "payload_hash": payload_hash,
            "feature_hash": feature_hash,
            "configuration_hash": configuration_hash,
            "audit_hash": audit_hash,
        }
    )
    return FeatureSnapshot(
        snapshot_id=snapshot_id,
        context_hash=context_hash,
        audit_hash=audit_hash,
        payload=payload,
        payload_hash=payload_hash,
        feature_hash=feature_hash,
        configuration_hash=configuration_hash,
        module_manifest=dict(sorted(context.config.module_versions.items())),
        prequalification=tuple(decisions),
        capacity_omissions=omissions,
        accepted_feature_records=tuple(selected),
    )
