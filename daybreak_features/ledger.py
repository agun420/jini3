"""Deterministic correction/cancellation-aware trade materialization."""

from __future__ import annotations

from collections.abc import Iterable

from .errors import DataQualityError
from .models import MaterializedTrade, TradeAction, TradeLedgerEvent


def materialize_trades(events: Iterable[TradeLedgerEvent]) -> tuple[MaterializedTrade, ...]:
    ordered = sorted(events, key=lambda item: item.ingest_seq)
    if len({event.ingest_seq for event in ordered}) != len(ordered):
        raise DataQualityError(
            "DUPLICATE_INGEST_SEQUENCE", "trade events contain duplicate ingest_seq"
        )

    active: dict[str, MaterializedTrade] = {}
    aliases: dict[str, str] = {}

    for event in ordered:
        if event.action == TradeAction.NEW:
            if event.trade_id in active or event.trade_id in aliases:
                raise DataQualityError("DUPLICATE_TRADE_ID", f"duplicate trade id {event.trade_id}")
            if not event.eligible:
                aliases[event.trade_id] = event.trade_id
                continue
            assert event.price is not None and event.size is not None
            active[event.trade_id] = MaterializedTrade(
                trade_id=event.trade_id,
                event_timestamp=event.event_timestamp,
                price=event.price,
                size=event.size,
                ingest_seq=event.ingest_seq,
            )
            aliases[event.trade_id] = event.trade_id
            continue

        assert event.original_trade_id is not None
        root = aliases.get(event.original_trade_id, event.original_trade_id)
        previous = active.pop(root, None)
        if previous is None:
            raise DataQualityError(
                "UNKNOWN_ORIGINAL_TRADE",
                f"{event.action} references unknown active trade {event.original_trade_id}",
            )
        aliases[event.trade_id] = event.trade_id
        aliases[event.original_trade_id] = event.trade_id

        if event.action == TradeAction.CANCEL or not event.eligible:
            continue

        assert event.price is not None and event.size is not None
        active[event.trade_id] = MaterializedTrade(
            trade_id=event.trade_id,
            event_timestamp=event.event_timestamp,
            price=event.price,
            size=event.size,
            ingest_seq=event.ingest_seq,
        )

    return tuple(
        sorted(
            active.values(), key=lambda item: (item.event_timestamp, item.ingest_seq, item.trade_id)
        )
    )
