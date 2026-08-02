"""Implementation of the frozen daily_pivot_cluster_v1 specification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from statistics import median

from .errors import DataQualityError
from .models import DailyBar, FeatureEngineConfig, ResistanceAudit


@dataclass(frozen=True, slots=True)
class Pivot:
    session_date: date
    price: Decimal
    confirmed: bool
    lookback_high: bool


@dataclass(frozen=True, slots=True)
class Cluster:
    sequence: int
    anchor: Decimal
    members: tuple[Pivot, ...]
    zone_low: Decimal
    zone_high: Decimal
    zone_center: Decimal
    touch_dates: tuple[date, ...]
    most_recent_touch_age: int
    contains_lookback_high: bool


def _quantum(places: int) -> Decimal:
    return Decimal(1).scaleb(-places)


def _pivot_candidates(
    bars: tuple[DailyBar, ...], config: FeatureEngineConfig
) -> tuple[tuple[Pivot, ...], bool]:
    left = config.pivot_left_width
    right = config.pivot_right_width
    pivots: list[Pivot] = []
    for index in range(left, len(bars) - right):
        price = bars[index].high
        if price > max(bar.high for bar in bars[index - left : index]) and price > max(
            bar.high for bar in bars[index + 1 : index + right + 1]
        ):
            pivots.append(Pivot(bars[index].session_date, price, True, False))

    max_price = max(bar.high for bar in bars)
    representative = max(
        (bar for bar in bars if bar.high == max_price), key=lambda bar: bar.session_date
    )
    synthetic = not any(pivot.session_date == representative.session_date for pivot in pivots)
    if synthetic:
        pivots.append(Pivot(representative.session_date, representative.high, False, True))
    else:
        pivots = [
            Pivot(
                p.session_date, p.price, p.confirmed, p.session_date == representative.session_date
            )
            for p in pivots
        ]
    return tuple(pivots), synthetic


def _clusters(
    pivots: tuple[Pivot, ...],
    bars: tuple[DailyBar, ...],
    atr: Decimal,
    config: FeatureEngineConfig,
) -> tuple[Cluster, ...]:
    tolerance = config.cluster_tolerance_atr * atr
    sorted_pivots = sorted(pivots, key=lambda item: (-item.price, item.session_date))
    assigned: set[int] = set()
    result: list[Cluster] = []
    latest_index = len(bars) - 1
    date_to_index = {bar.session_date: index for index, bar in enumerate(bars)}

    for index, anchor_pivot in enumerate(sorted_pivots):
        if index in assigned:
            continue
        assigned.add(index)
        members = [anchor_pivot]
        for candidate_index in range(index + 1, len(sorted_pivots)):
            if candidate_index in assigned:
                continue
            candidate = sorted_pivots[candidate_index]
            if anchor_pivot.price - candidate.price <= tolerance:
                members.append(candidate)
                assigned.add(candidate_index)
        unique_by_date = {member.session_date: member for member in members}
        unique_members = tuple(sorted(unique_by_date.values(), key=lambda item: item.session_date))
        prices = [member.price for member in unique_members]
        dates = tuple(member.session_date for member in unique_members)
        center = Decimal(str(median(prices)))
        most_recent = max(dates)
        age = latest_index - date_to_index[most_recent]
        result.append(
            Cluster(
                sequence=len(result) + 1,
                anchor=anchor_pivot.price,
                members=unique_members,
                zone_low=min(prices),
                zone_high=max(prices),
                zone_center=center,
                touch_dates=dates,
                most_recent_touch_age=age,
                contains_lookback_high=any(member.lookback_high for member in unique_members),
            )
        )
    return tuple(result)


def daily_pivot_cluster_v1(
    *,
    bars: tuple[DailyBar, ...],
    current_price: Decimal,
    atr: Decimal,
    history_complete_since_listing: bool,
    config: FeatureEngineConfig,
) -> ResistanceAudit:
    if len(bars) < config.min_daily_history:
        raise DataQualityError("INSUFFICIENT_DAILY_HISTORY", "fewer than 30 completed daily bars")
    if atr <= 0:
        raise DataQualityError("INVALID_ATR", "ATR must be positive")

    cluster_bars = bars[-min(config.cluster_lookback_sessions, len(bars)) :]
    all_time_high = max(bar.high for bar in bars)
    all_time_high_date = max(bar.session_date for bar in bars if bar.high == all_time_high)
    pivots, synthetic = _pivot_candidates(cluster_bars, config)
    clusters = _clusters(pivots, cluster_bars, atr, config)
    valid = tuple(
        cluster
        for cluster in clusters
        if (len(cluster.touch_dates) >= 2 or cluster.contains_lookback_high)
        and not (
            cluster.most_recent_touch_age > config.cluster_recency_sessions
            and len(cluster.touch_dates) < 3
        )
    )

    eligible: list[tuple[Decimal, Cluster]] = []
    for cluster in valid:
        if current_price < cluster.zone_low:
            distance = (cluster.zone_low - current_price) / atr
            eligible.append((distance, cluster))
        elif cluster.zone_low <= current_price <= cluster.zone_high:
            eligible.append((Decimal(0), cluster))

    selected: Cluster | None = None
    source: str
    raw_distance: Decimal | None
    if eligible:
        raw_distance, selected = sorted(
            eligible,
            key=lambda pair: (
                pair[0],
                -pair[1].touch_dates[-1].toordinal(),
                -len(pair[1].touch_dates),
                pair[1].zone_low,
                pair[1].sequence,
            ),
        )[0]
        source = "pivot_cluster"
    elif current_price < all_time_high:
        raw_distance = (all_time_high - current_price) / atr
        source = "all_time_high_fallback"
    else:
        if not history_complete_since_listing:
            raise DataQualityError(
                "INCOMPLETE_HISTORY_FOR_BLUE_SKY_CHECK",
                "cannot assign blue_sky without complete listing history",
            )
        return ResistanceAudit(
            available_completed_bars=len(bars),
            cluster_lookback_bars=len(cluster_bars),
            all_time_high_price=all_time_high,
            all_time_high_date=all_time_high_date,
            confirmed_pivot_count=sum(1 for pivot in pivots if pivot.confirmed),
            synthetic_lookback_high_added=synthetic,
            valid_cluster_count=len(valid),
            selected_resistance_source="none_above_all_time_high",
            distance_to_resistance_atr=config.blue_sky_sentinel,
            chart_structure="blue_sky",
            is_blue_sky_sentinel=True,
        )

    assert raw_distance is not None
    distance = raw_distance.quantize(
        _quantum(config.distance_decimal_places), rounding=ROUND_HALF_EVEN
    )
    if distance > Decimal("2.0"):
        structure = "clean_short_term"
    elif distance >= Decimal("1.0"):
        structure = "moderate_room"
    else:
        structure = "capped"

    return ResistanceAudit(
        available_completed_bars=len(bars),
        cluster_lookback_bars=len(cluster_bars),
        all_time_high_price=all_time_high,
        all_time_high_date=all_time_high_date,
        confirmed_pivot_count=sum(1 for pivot in pivots if pivot.confirmed),
        synthetic_lookback_high_added=synthetic,
        valid_cluster_count=len(valid),
        selected_resistance_source=source,  # type: ignore[arg-type]
        selected_zone_low=selected.zone_low if selected else None,
        selected_zone_high=selected.zone_high if selected else None,
        selected_zone_center=selected.zone_center if selected else None,
        selected_touch_count=len(selected.touch_dates) if selected else None,
        selected_touch_dates=selected.touch_dates if selected else (),
        raw_distance_to_resistance_atr=str(raw_distance),
        distance_to_resistance_atr=distance,
        chart_structure=structure,  # type: ignore[arg-type]
        is_blue_sky_sentinel=False,
    )
