from decimal import Decimal

from daybreak_features.canonical import canonical_json_bytes, canonical_sha256
from daybreak_features.engine import build_feature_snapshot
from daybreak_features.models import FeatureEngineConfig

from .helpers import candidate, context


def test_builds_exact_contract_payload():
    snapshot = build_feature_snapshot(context(candidate()))
    assert snapshot.payload.tickers[0].ticker == "TEST"
    assert snapshot.payload.tickers[0].technical_context.chart_structure == "blue_sky"
    assert snapshot.payload.tickers[0].technical_context.distance_to_resistance_atr == 99.0
    assert snapshot.payload_hash == canonical_sha256(snapshot.payload)


def test_replay_is_byte_identical():
    source = context(candidate())
    first = build_feature_snapshot(source)
    second = build_feature_snapshot(source)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert first.snapshot_id == second.snapshot_id


def test_input_candidate_order_does_not_change_snapshot():
    a = candidate("AAAA")
    b = candidate("BBBB")
    first = build_feature_snapshot(context(a, b))
    second = build_feature_snapshot(context(b, a))
    assert first.payload_hash == second.payload_hash
    assert first.feature_hash == second.feature_hash


def test_halted_candidate_removed_before_payload():
    snapshot = build_feature_snapshot(context(candidate(halted=True)))
    assert snapshot.payload.tickers == ()
    assert snapshot.prequalification[0].reason_codes == ("HALTED",)


def test_low_volume_candidate_removed():
    snapshot = build_feature_snapshot(context(candidate(current_count=10, current_size=1_000)))
    assert snapshot.payload.tickers == ()
    assert "PREMARKET_VOLUME_TOO_LOW" in snapshot.prequalification[0].reason_codes


def test_stale_catalyst_removed():
    source = candidate()
    old = source.catalysts[0].model_copy(
        update={
            "source_timestamp": source.catalysts[0].source_timestamp.replace(day=1),
            "observed_at": source.catalysts[0].observed_at.replace(day=1),
        }
    )
    source = source.model_copy(update={"catalysts": (old,)})
    snapshot = build_feature_snapshot(context(source))
    assert "STALE_CATALYST" in snapshot.prequalification[0].reason_codes


def test_capacity_cap_and_omission_order():
    sources = tuple(candidate(f"T{index:02d}") for index in range(5))
    snapshot = build_feature_snapshot(context(*sources, max_candidates=3))
    assert len(snapshot.payload.tickers) == 3
    assert [item.final_capacity_rank for item in snapshot.capacity_omissions] == [4, 5]
    assert {item.ticker for item in snapshot.capacity_omissions} == {"T03", "T04"}


def test_missing_float_fails_closed_without_schema_failure_payload():
    source = candidate().model_copy(update={"float_records": ()})
    snapshot = build_feature_snapshot(context(source))
    assert snapshot.payload.tickers == ()
    assert snapshot.prequalification[0].reason_codes == ("FLOAT_DATA_UNAVAILABLE",)


def test_config_change_changes_configuration_and_snapshot_hash():
    base = context(candidate())
    first = build_feature_snapshot(base)
    changed = base.model_copy(
        update={"config": FeatureEngineConfig(spiky_max_bucket_share=Decimal("0.40"))}
    )
    second = build_feature_snapshot(changed)
    assert first.configuration_hash != second.configuration_hash
    assert first.snapshot_id != second.snapshot_id


def test_payload_age_is_exact_integer_seconds():
    base = context(candidate())
    later = base.model_copy(
        update={"evaluation_timestamp": base.evaluation_timestamp.replace(second=30)}
    )
    snapshot = build_feature_snapshot(later)
    assert snapshot.payload.payload_age_seconds == 30


def test_rejected_universe_changes_audit_and_snapshot_identity():
    accepted_only = build_feature_snapshot(context(candidate("AAAA")))
    with_rejected = build_feature_snapshot(
        context(candidate("AAAA"), candidate("BBBB", halted=True))
    )
    assert accepted_only.payload_hash == with_rejected.payload_hash
    assert accepted_only.feature_hash == with_rejected.feature_hash
    assert accepted_only.audit_hash != with_rejected.audit_hash
    assert accepted_only.context_hash != with_rejected.context_hash
    assert accepted_only.snapshot_id != with_rejected.snapshot_id
