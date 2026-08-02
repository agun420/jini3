from datetime import date, timedelta
from decimal import Decimal

import pytest

from daybreak_features.errors import DataQualityError
from daybreak_features.joins import select_catalyst, select_float_record
from daybreak_features.models import FeatureEngineConfig, QualityStatus

from .helpers import catalyst, dt, float_record


def test_float_join_selects_latest_known_record():
    day = date(2026, 8, 3)
    older = float_record("TEST", day, shares=20_000_000)
    newer = older.model_copy(
        update={
            "float_shares": 25_000_000,
            "effective_date": day - timedelta(days=1),
            "observed_at": dt(day, 3, 10),
            "validated_at": dt(day, 3, 11),
        }
    )
    result = select_float_record(
        (older, newer), ticker="TEST", snapshot=dt(day, 9, 23), config=FeatureEngineConfig()
    )
    assert result.float_shares == 25_000_000


def test_float_join_blocks_future_observation():
    day = date(2026, 8, 3)
    record = float_record("TEST", day).model_copy(update={"observed_at": dt(day, 10)})
    with pytest.raises(DataQualityError, match="FLOAT_DATA_UNAVAILABLE"):
        select_float_record(
            (record,), ticker="TEST", snapshot=dt(day, 9, 23), config=FeatureEngineConfig()
        )


def test_float_join_can_require_verified():
    day = date(2026, 8, 3)
    record = float_record("TEST", day).model_copy(
        update={"quality_status": QualityStatus.SINGLE_SOURCE}
    )
    with pytest.raises(DataQualityError, match="FLOAT_DATA_UNAVAILABLE"):
        select_float_record(
            (record,),
            ticker="TEST",
            snapshot=dt(day, 9, 23),
            config=FeatureEngineConfig(allow_single_source_float=False),
        )


def test_catalyst_primary_priority():
    day = date(2026, 8, 3)
    primary = catalyst("TEST", day, source_type="primary", age_hours=5)
    secondary = catalyst("TEST", day, source_type="secondary", age_hours=1).model_copy(
        update={"catalyst_id": "SEC"}
    )
    selected, age = select_catalyst((secondary, primary), ticker="TEST", snapshot=dt(day, 9, 23))
    assert selected.source_type == "primary"
    assert age == Decimal("5.000000")


def test_catalyst_future_timestamp_rejected():
    day = date(2026, 8, 3)
    record = catalyst("TEST", day).model_copy(update={"source_timestamp": dt(day, 10)})
    with pytest.raises(DataQualityError, match="FUTURE_CATALYST_TIMESTAMP"):
        select_catalyst((record,), ticker="TEST", snapshot=dt(day, 9, 23))
