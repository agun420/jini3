"""Deterministic point-in-time float and catalyst joins."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from .errors import DataQualityError
from .models import CatalystRecord, FeatureEngineConfig, FloatRecord, QualityStatus

SIX = Decimal("0.000001")


def select_float_record(
    records: tuple[FloatRecord, ...],
    *,
    ticker: str,
    snapshot: datetime,
    config: FeatureEngineConfig,
) -> FloatRecord:
    candidates = [
        record
        for record in records
        if record.ticker == ticker
        and record.effective_date <= snapshot.date()
        and record.observed_at <= snapshot
        and record.validated_at <= snapshot
        and snapshot < record.expires_at
        and (
            record.quality_status == QualityStatus.VERIFIED
            or (
                config.allow_single_source_float
                and record.quality_status == QualityStatus.SINGLE_SOURCE
            )
        )
    ]
    if not candidates:
        raise DataQualityError("FLOAT_DATA_UNAVAILABLE", "no valid point-in-time float record")
    return max(
        candidates, key=lambda item: (item.effective_date, item.observed_at, item.validated_at)
    )


def select_catalyst(
    records: tuple[CatalystRecord, ...], *, ticker: str, snapshot: datetime
) -> tuple[CatalystRecord, Decimal]:
    known = [
        record for record in records if record.ticker == ticker and record.observed_at <= snapshot
    ]
    if not known:
        raise DataQualityError("CATALYST_DATA_UNAVAILABLE", "no catalyst known by snapshot")

    priority = {"primary": 0, "secondary": 1, "unconfirmed": 2}
    selected = sorted(
        known,
        key=lambda item: (
            priority[item.source_type],
            0 if item.corroborated else 1,
            -item.source_timestamp.timestamp(),
            item.catalyst_id,
        ),
    )[0]
    age_seconds = Decimal(str((snapshot - selected.source_timestamp).total_seconds()))
    if age_seconds < 0:
        raise DataQualityError("FUTURE_CATALYST_TIMESTAMP", "source timestamp is after snapshot")
    age_hours = (age_seconds / Decimal(3600)).quantize(SIX, rounding=ROUND_HALF_EVEN)
    return selected, age_hours
