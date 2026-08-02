"""Pure deterministic core market-feature calculations."""

from __future__ import annotations

from datetime import datetime, time
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from .errors import DataQualityError
from .ledger import materialize_trades
from .models import (
    DailyBar,
    FeatureEngineConfig,
    MaterializedTrade,
    PremarketSession,
    TradeLedgerEvent,
)

NY = ZoneInfo("America/New_York")
SIX = Decimal("0.000001")


def _in_premarket_window(
    trade: MaterializedTrade, snapshot: datetime, config: FeatureEngineConfig
) -> bool:
    local = trade.event_timestamp.astimezone(NY)
    snapshot_local = snapshot.astimezone(NY)
    start = time.fromisoformat(config.premarket_start_et)
    return local.date() == snapshot_local.date() and start <= local.time().replace(
        tzinfo=None
    ) <= snapshot_local.time().replace(tzinfo=None)


def current_session_trades(
    events: tuple[TradeLedgerEvent, ...], snapshot: datetime, config: FeatureEngineConfig
) -> tuple[MaterializedTrade, ...]:
    return tuple(
        trade
        for trade in materialize_trades(events)
        if _in_premarket_window(trade, snapshot, config)
    )


def current_price(trades: tuple[MaterializedTrade, ...]) -> Decimal:
    if not trades:
        raise DataQualityError(
            "NO_ELIGIBLE_PREMARKET_TRADES", "no materialized trades in snapshot window"
        )
    return trades[-1].price


def premarket_low(trades: tuple[MaterializedTrade, ...]) -> Decimal:
    if not trades:
        raise DataQualityError("NO_ELIGIBLE_PREMARKET_TRADES", "cannot calculate premarket low")
    return min(trade.price for trade in trades)


def gap_pct(price: Decimal, previous_close: Decimal) -> Decimal:
    if previous_close <= 0:
        raise DataQualityError("INVALID_PREVIOUS_CLOSE", "previous close must be positive")
    return (((price - previous_close) / previous_close) * Decimal(100)).quantize(
        SIX, rounding=ROUND_HALF_EVEN
    )


def premarket_volume(trades: tuple[MaterializedTrade, ...]) -> int:
    return sum(trade.size for trade in trades)


def premarket_vwap(trades: tuple[MaterializedTrade, ...]) -> Decimal:
    volume = premarket_volume(trades)
    if volume <= 0:
        raise DataQualityError("ZERO_PREMARKET_VOLUME", "cannot calculate VWAP with zero volume")
    notional = sum(trade.price * trade.size for trade in trades)
    return (notional / Decimal(volume)).quantize(SIX, rounding=ROUND_HALF_EVEN)


def distance_from_vwap_atr(price: Decimal, vwap: Decimal, atr: Decimal) -> Decimal:
    if atr <= 0:
        raise DataQualityError("INVALID_ATR", "ATR must be positive")
    return ((price - vwap) / atr).quantize(SIX, rounding=ROUND_HALF_EVEN)


def true_range(current: DailyBar, previous_close: Decimal) -> Decimal:
    return max(
        current.high - current.low,
        abs(current.high - previous_close),
        abs(current.low - previous_close),
    )


def wilder_atr_14(bars: tuple[DailyBar, ...]) -> Decimal:
    period = 14
    if len(bars) < period + 1:
        raise DataQualityError("INSUFFICIENT_ATR_HISTORY", "ATR-14 requires at least 15 daily bars")
    ranges = [true_range(bars[index], bars[index - 1].close) for index in range(1, len(bars))]
    initial = sum(ranges[:period], Decimal(0)) / Decimal(period)
    atr = initial
    for value in ranges[period:]:
        atr = ((atr * Decimal(period - 1)) + value) / Decimal(period)
    if atr <= 0:
        raise DataQualityError("INVALID_ATR", "computed ATR is nonpositive")
    return atr.quantize(SIX, rounding=ROUND_HALF_EVEN)


def historical_session_volume(
    session: PremarketSession, snapshot: datetime, config: FeatureEngineConfig
) -> int:
    if not session.complete:
        raise DataQualityError(
            "INCOMPLETE_RVOL_SESSION", f"historical session {session.session_date} incomplete"
        )
    cutoff_local = snapshot.astimezone(NY).time().replace(tzinfo=None)
    start = time.fromisoformat(config.premarket_start_et)
    materialized = materialize_trades(session.events)
    eligible = [
        trade
        for trade in materialized
        if trade.event_timestamp.astimezone(NY).date() == session.session_date
        and start
        <= trade.event_timestamp.astimezone(NY).time().replace(tzinfo=None)
        <= cutoff_local
    ]
    return premarket_volume(tuple(eligible))


def rvol_time_matched(
    current_volume: int,
    sessions: tuple[PremarketSession, ...],
    snapshot: datetime,
    config: FeatureEngineConfig,
) -> Decimal:
    if len(sessions) < config.rvol_lookback_sessions:
        raise DataQualityError(
            "INSUFFICIENT_RVOL_HISTORY",
            f"requires {config.rvol_lookback_sessions} complete historical sessions",
        )
    selected = sorted(sessions, key=lambda item: item.session_date)[
        -config.rvol_lookback_sessions :
    ]
    volumes = [historical_session_volume(session, snapshot, config) for session in selected]
    average = Decimal(sum(volumes)) / Decimal(len(volumes))
    if average <= 0:
        raise DataQualityError("ZERO_RVOL_BASELINE", "historical premarket average is zero")
    return (Decimal(current_volume) / average).quantize(SIX, rounding=ROUND_HALF_EVEN)


def volume_profile(
    trades: tuple[MaterializedTrade, ...], snapshot: datetime, config: FeatureEngineConfig
) -> Literal["clean", "spiky"]:
    total = premarket_volume(trades)
    if total <= 0:
        raise DataQualityError("ZERO_PREMARKET_VOLUME", "cannot classify volume profile")
    local_snapshot = snapshot.astimezone(NY)
    start_time = time.fromisoformat(config.premarket_start_et)
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = local_snapshot.hour * 60 + local_snapshot.minute
    bucket_width = config.volume_bucket_minutes
    bucket_count = ((end_minutes - start_minutes) // bucket_width) + 1
    if bucket_count <= 0:
        raise DataQualityError("INVALID_PREMARKET_WINDOW", "snapshot precedes premarket start")
    buckets = [0 for _ in range(bucket_count)]
    for trade in trades:
        local = trade.event_timestamp.astimezone(NY)
        minute = local.hour * 60 + local.minute
        index = min((minute - start_minutes) // bucket_width, bucket_count - 1)
        if index >= 0:
            buckets[index] += trade.size
    max_share = Decimal(max(buckets)) / Decimal(total)
    nonempty_coverage = Decimal(sum(1 for value in buckets if value > 0)) / Decimal(bucket_count)
    if (
        max_share > config.spiky_max_bucket_share
        or nonempty_coverage < config.spiky_min_nonempty_coverage
    ):
        return "spiky"
    return "clean"
