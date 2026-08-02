from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .alpaca import normalize_order
from .canonical import canonical_sha256
from .models import TradeUpdate


def normalize_trade_update(
    payload: dict[str, Any], *, received_at: datetime | None = None
) -> TradeUpdate:
    received_at = (received_at or datetime.now(UTC)).astimezone(UTC)
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError("trade update data must be an object")
    order_payload = data.get("order")
    if not isinstance(order_payload, dict):
        raise ValueError("trade update is missing order object")
    event = str(data.get("event", "unknown"))
    event_timestamp_raw = data.get("timestamp") or data.get("event_at")
    if event_timestamp_raw:
        event_timestamp = datetime.fromisoformat(str(event_timestamp_raw).replace("Z", "+00:00"))
        if event_timestamp.tzinfo is None:
            event_timestamp = event_timestamp.replace(tzinfo=UTC)
        event_timestamp = event_timestamp.astimezone(UTC)
    else:
        event_timestamp = received_at
    raw_hash = canonical_sha256(payload)
    event_id = uuid5(
        NAMESPACE_URL,
        f"alpaca-trade-update:{order_payload.get('id')}:{event}:{event_timestamp.isoformat()}:{raw_hash}",
    ).hex
    return TradeUpdate(
        event_id=event_id,
        event=event,
        event_timestamp=event_timestamp,
        order=normalize_order(order_payload, observed_at=received_at),
        raw_event_hash=raw_hash,
    )


class AlpacaPyTradeUpdateStream:
    """Optional alpaca-py stream adapter. It never submits orders."""

    def __init__(self, *, api_key: str, secret_key: str) -> None:
        try:
            from alpaca.trading.stream import TradingStream
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install project-daybreak[recorder] for Alpaca streaming") from exc
        self._stream = TradingStream(api_key, secret_key, paper=True)

    def subscribe(self, handler: Callable[[TradeUpdate], Awaitable[None]]) -> None:
        async def _wrapped(update: Any) -> None:
            if hasattr(update, "model_dump"):
                raw = update.model_dump(mode="json")
            elif hasattr(update, "dict"):
                raw = update.dict()
            elif isinstance(update, dict):
                raw = update
            else:
                raise ValueError("unsupported alpaca-py trade update type")
            await handler(normalize_trade_update(raw))

        self._stream.subscribe_trade_updates(_wrapped)

    def run(self) -> None:  # pragma: no cover - deployment acceptance only
        self._stream.run()

    def stop(self) -> None:  # pragma: no cover - deployment acceptance only
        self._stream.stop()
