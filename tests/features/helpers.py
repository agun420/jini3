from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from daybreak_features.models import (
    BorrowStatus,
    CandidateSourceData,
    CatalystRecord,
    DailyBar,
    FeatureContext,
    FeatureEngineConfig,
    FloatRecord,
    PremarketSession,
    QualityStatus,
    SourceType,
    TradeAction,
    TradeLedgerEvent,
)

UTC = UTC
HASH = "0" * 64


def dt(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    # August fixtures use EDT = UTC-4.
    return datetime(day.year, day.month, day.day, hour + 4, minute, second, tzinfo=UTC)


def trade_events(
    day: date,
    *,
    count: int = 50,
    size: int = 12_000,
    base_price: Decimal = Decimal("12.00"),
    start_seq: int = 1,
) -> tuple[TradeLedgerEvent, ...]:
    events = []
    for index in range(count):
        total_minutes = index * 5
        hour = 4 + total_minutes // 60
        minute = total_minutes % 60
        events.append(
            TradeLedgerEvent(
                ingest_seq=start_seq + index,
                trade_id=f"{day}-T{index}",
                action=TradeAction.NEW,
                event_timestamp=dt(day, hour, minute),
                price=base_price + Decimal(index % 3) / Decimal("100"),
                size=size,
            )
        )
    return tuple(events)


def historical_sessions(
    day: date, *, volume_per_session: int = 60_000
) -> tuple[PremarketSession, ...]:
    sessions = []
    cursor = day - timedelta(days=35)
    while len(sessions) < 20:
        if cursor.weekday() < 5:
            sessions.append(
                PremarketSession(
                    session_date=cursor,
                    events=trade_events(
                        cursor,
                        count=10,
                        size=volume_per_session // 10,
                        base_price=Decimal("10.00"),
                        start_seq=1,
                    ),
                )
            )
        cursor += timedelta(days=1)
    return tuple(sessions)


def daily_bars(
    day: date, *, count: int = 60, top: Decimal = Decimal("11.00")
) -> tuple[DailyBar, ...]:
    bars = []
    cursor = day - timedelta(days=count + 30)
    while len(bars) < count:
        if cursor.weekday() < 5:
            index = len(bars)
            close = Decimal("9.00") + Decimal(index % 10) / Decimal("20")
            high = min(top, close + Decimal("0.60"))
            low = close - Decimal("0.40")
            bars.append(
                DailyBar(
                    session_date=cursor,
                    open=close - Decimal("0.10"),
                    high=high,
                    low=low,
                    close=close,
                    volume=1_000_000 + index,
                )
            )
        cursor += timedelta(days=1)
    return tuple(bars)


def float_record(ticker: str, day: date, *, shares: int = 30_000_000) -> FloatRecord:
    return FloatRecord(
        ticker=ticker,
        float_shares=shares,
        effective_date=day - timedelta(days=5),
        observed_at=dt(day, 3, 0),
        validated_at=dt(day, 3, 1),
        expires_at=dt(day + timedelta(days=1), 3, 0),
        quality_status=QualityStatus.VERIFIED,
        source="fixture",
        raw_response_hashes=(HASH,),
    )


def catalyst(
    ticker: str, day: date, *, source_type: str = "primary", age_hours: int = 2
) -> CatalystRecord:
    snapshot = dt(day, 9, 23)
    return CatalystRecord(
        catalyst_id=f"{ticker}-CAT",
        ticker=ticker,
        catalyst_text=(
            "The company raised full-year revenue guidance from $100 million to $140 million."
        ),
        source_type=SourceType(source_type),
        source_name="Issuer release",
        source_timestamp=snapshot - timedelta(hours=age_hours),
        observed_at=snapshot - timedelta(hours=age_hours) + timedelta(minutes=1),
        corroborated=True,
        disqualifier_flags=(),
        source_hash=HASH,
    )


def candidate(
    ticker: str = "TEST",
    *,
    day: date = date(2026, 8, 3),
    current_size: int = 12_000,
    current_count: int = 50,
    current_price: Decimal = Decimal("12.00"),
    previous_close: Decimal = Decimal("10.00"),
    halted: bool = False,
    history_complete: bool = True,
    source_type: str = "primary",
) -> CandidateSourceData:
    return CandidateSourceData(
        ticker=ticker,
        halted=halted,
        borrow_status=BorrowStatus.EASY,
        previous_regular_close=previous_close,
        current_session_events=trade_events(
            day,
            count=current_count,
            size=current_size,
            base_price=current_price,
        ),
        historical_premarket_sessions=historical_sessions(day),
        daily_bars=daily_bars(day),
        history_complete_since_listing=history_complete,
        float_records=(float_record(ticker, day),),
        catalysts=(catalyst(ticker, day, source_type=source_type),),
    )


def context(*candidates: CandidateSourceData, max_candidates: int = 20) -> FeatureContext:
    day = date(2026, 8, 3)
    snapshot = dt(day, 9, 23)
    return FeatureContext(
        evaluation_timestamp=snapshot,
        payload_timestamp=snapshot,
        catalyst_freshness_threshold_hours=Decimal("18"),
        market_status="normal",
        candidates=tuple(candidates or (candidate(),)),
        config=FeatureEngineConfig(max_evaluator_candidates=max_candidates),
    )
