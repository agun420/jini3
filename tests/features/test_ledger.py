from datetime import date
from decimal import Decimal

import pytest

from daybreak_features.errors import DataQualityError
from daybreak_features.ledger import materialize_trades
from daybreak_features.models import TradeAction, TradeLedgerEvent

from .helpers import dt


def test_materialize_new_trade():
    event = TradeLedgerEvent(
        ingest_seq=1,
        trade_id="A",
        action=TradeAction.NEW,
        event_timestamp=dt(date(2026, 8, 3), 4),
        price=Decimal("10"),
        size=100,
    )
    result = materialize_trades((event,))
    assert len(result) == 1
    assert result[0].price == Decimal("10")


def test_materialize_cancel_removes_trade():
    day = date(2026, 8, 3)
    events = (
        TradeLedgerEvent(
            ingest_seq=1,
            trade_id="A",
            action=TradeAction.NEW,
            event_timestamp=dt(day, 4),
            price=Decimal("10"),
            size=100,
        ),
        TradeLedgerEvent(
            ingest_seq=2,
            trade_id="C",
            action=TradeAction.CANCEL,
            original_trade_id="A",
            event_timestamp=dt(day, 4, 1),
        ),
    )
    assert materialize_trades(events) == ()


def test_materialize_correction_replaces_trade():
    day = date(2026, 8, 3)
    events = (
        TradeLedgerEvent(
            ingest_seq=1,
            trade_id="A",
            action=TradeAction.NEW,
            event_timestamp=dt(day, 4),
            price=Decimal("10"),
            size=100,
        ),
        TradeLedgerEvent(
            ingest_seq=2,
            trade_id="B",
            action=TradeAction.CORRECTION,
            original_trade_id="A",
            event_timestamp=dt(day, 4, 1),
            price=Decimal("11"),
            size=80,
        ),
    )
    result = materialize_trades(events)
    assert [(item.trade_id, item.price, item.size) for item in result] == [("B", Decimal("11"), 80)]


def test_unknown_original_fails_closed():
    event = TradeLedgerEvent(
        ingest_seq=1,
        trade_id="C",
        action=TradeAction.CANCEL,
        original_trade_id="MISSING",
        event_timestamp=dt(date(2026, 8, 3), 4),
    )
    with pytest.raises(DataQualityError, match="UNKNOWN_ORIGINAL_TRADE"):
        materialize_trades((event,))


def test_duplicate_ingest_sequence_rejected():
    day = date(2026, 8, 3)
    events = (
        TradeLedgerEvent(
            ingest_seq=1,
            trade_id="A",
            action=TradeAction.NEW,
            event_timestamp=dt(day, 4),
            price=Decimal("10"),
            size=100,
        ),
        TradeLedgerEvent(
            ingest_seq=1,
            trade_id="B",
            action=TradeAction.NEW,
            event_timestamp=dt(day, 4, 1),
            price=Decimal("11"),
            size=100,
        ),
    )
    with pytest.raises(DataQualityError, match="DUPLICATE_INGEST_SEQUENCE"):
        materialize_trades(events)
