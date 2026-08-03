from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx

from .canonical import canonical_sha256
from .enums import BrokerOrderStatus, OrderSide, OrderType
from .errors import BrokerNotFound, BrokerTransportError
from .models import (
    BrokerOrderCommand,
    BrokerOrderLeg,
    BrokerOrderSnapshot,
    BrokerPositionSnapshot,
)

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _parse_timestamp(value: Any, *, default: datetime) -> datetime:
    if not value:
        return default
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _snapshot_id(order_id: str, updated_at: datetime, raw_hash: str) -> str:
    return uuid5(NAMESPACE_URL, f"alpaca-order:{order_id}:{updated_at.isoformat()}:{raw_hash}").hex


def normalize_order(
    payload: dict[str, Any], *, observed_at: datetime | None = None
) -> BrokerOrderSnapshot:
    observed_at = (observed_at or datetime.now(UTC)).astimezone(UTC)
    raw_hash = canonical_sha256(payload)
    updated_at = _parse_timestamp(payload.get("updated_at"), default=observed_at)
    legs = tuple(
        BrokerOrderLeg(
            broker_order_id=str(leg["id"]),
            client_order_id=None
            if leg.get("client_order_id") is None
            else str(leg["client_order_id"]),
            side=str(leg.get("side", "sell")),
            order_type=str(leg.get("type", "limit")),
            status=str(leg.get("status", "new")),
            quantity=Decimal(str(leg.get("qty", "0"))),
            filled_quantity=Decimal(str(leg.get("filled_qty", "0"))),
            limit_price=_decimal(leg.get("limit_price")),
            stop_price=_decimal(leg.get("stop_price")),
        )
        for leg in payload.get("legs") or []
    )
    return BrokerOrderSnapshot(
        snapshot_id=_snapshot_id(str(payload["id"]), updated_at, raw_hash),
        broker_order_id=str(payload["id"]),
        client_order_id=str(payload["client_order_id"]),
        symbol=str(payload["symbol"]),
        side=OrderSide(str(payload["side"])),
        order_type=OrderType(str(payload["type"])),
        time_in_force=str(payload.get("time_in_force", "day")),
        order_class=str(payload.get("order_class", "simple")),
        status=BrokerOrderStatus(str(payload["status"])),
        quantity=Decimal(str(payload["qty"])),
        filled_quantity=Decimal(str(payload.get("filled_qty", "0"))),
        filled_avg_price=_decimal(payload.get("filled_avg_price")),
        limit_price=_decimal(payload.get("limit_price")),
        stop_price=_decimal(payload.get("stop_price")),
        submitted_at=(
            None
            if payload.get("submitted_at") is None
            else _parse_timestamp(payload.get("submitted_at"), default=observed_at)
        ),
        updated_at=updated_at,
        legs=legs,
        raw_response_hash=raw_hash,
        raw_response=payload,
    )


def command_payload(command: BrokerOrderCommand) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": command.symbol,
        "qty": str(command.quantity),
        "side": command.side.value,
        "type": command.order_type.value,
        "time_in_force": command.time_in_force.value,
        "client_order_id": command.client_order_id,
        "extended_hours": False,
    }
    if command.limit_price is not None:
        payload["limit_price"] = format(command.limit_price, "f")
    if command.stop_price is not None:
        payload["stop_price"] = format(command.stop_price, "f")
    if command.order_class.value == "bracket":
        payload["order_class"] = "bracket"
        payload["take_profit"] = {"limit_price": format(command.take_profit_limit_price, "f")}
        payload["stop_loss"] = {"stop_price": format(command.stop_loss_stop_price, "f")}
    return payload


class AlpacaPaperBroker:
    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        base_url: str = PAPER_BASE_URL,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if base_url.rstrip("/") != PAPER_BASE_URL:
            raise ValueError("v0.5.0 permits only the Alpaca paper endpoint")
        if not api_key or not secret_key:
            raise ValueError("Alpaca paper credentials are required")
        self._client = httpx.Client(
            base_url=PAPER_BASE_URL,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            response = self._client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise BrokerTransportError(str(exc), transient=True) from exc
        if response.status_code == 404:
            raise BrokerNotFound(path)
        if response.is_error:
            transient = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
            raise BrokerTransportError(
                f"Alpaca returned HTTP {response.status_code}",
                transient=transient,
                status_code=response.status_code,
                response_body=response.text[:2000],
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            data = response.json()
        except ValueError as exc:
            raise BrokerTransportError(
                "Alpaca response was not valid JSON",
                transient=True,
                status_code=response.status_code,
                response_body=response.text[:2000],
            ) from exc
        if not isinstance(data, dict):
            raise BrokerTransportError("Alpaca response was not a JSON object", transient=False)
        return data

    def get_order_by_client_order_id(self, client_order_id: str) -> BrokerOrderSnapshot:
        data = self._request(
            "GET",
            "/v2/orders:by_client_order_id",
            params={"client_order_id": client_order_id, "nested": "true"},
        )
        assert data is not None
        try:
            return normalize_order(data)
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerTransportError(
                "Alpaca returned an invalid order payload", transient=True
            ) from exc

    def submit_order(self, command: BrokerOrderCommand) -> BrokerOrderSnapshot:
        data = self._request("POST", "/v2/orders", json=command_payload(command))
        assert data is not None
        try:
            return normalize_order(data)
        except (KeyError, TypeError, ValueError) as exc:
            # The POST may have succeeded, so the caller must reconcile by client id.
            raise BrokerTransportError(
                "Alpaca returned an invalid submit response", transient=True
            ) from exc

    def cancel_order(self, broker_order_id: str) -> None:
        self._request("DELETE", f"/v2/orders/{broker_order_id}")

    def get_order(self, broker_order_id: str) -> BrokerOrderSnapshot:
        data = self._request("GET", f"/v2/orders/{broker_order_id}", params={"nested": "true"})
        assert data is not None
        try:
            return normalize_order(data)
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerTransportError(
                "Alpaca returned an invalid order payload", transient=True
            ) from exc

    def get_position(self, symbol: str) -> BrokerPositionSnapshot | None:
        try:
            data = self._request("GET", f"/v2/positions/{symbol}")
        except BrokerNotFound:
            return None
        assert data is not None
        observed = datetime.now(UTC)
        return BrokerPositionSnapshot(
            symbol=symbol,
            quantity=abs(Decimal(str(data.get("qty", "0")))),
            average_entry_price=_decimal(data.get("avg_entry_price")),
            observed_at=observed,
            raw_response_hash=canonical_sha256(data),
        )

    def _request_list(self, method: str, path: str, **kwargs: Any) -> list[dict[str, Any]]:
        try:
            response = self._client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise BrokerTransportError(str(exc), transient=True) from exc
        if response.status_code == 404:
            raise BrokerNotFound(path)
        if response.is_error:
            transient = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
            raise BrokerTransportError(
                f"Alpaca returned HTTP {response.status_code}",
                transient=transient,
                status_code=response.status_code,
                response_body=response.text[:2000],
            )
        if response.status_code == 204 or not response.content:
            return []
        try:
            data = response.json()
        except ValueError as exc:
            raise BrokerTransportError(
                "Alpaca response was not valid JSON",
                transient=True,
                status_code=response.status_code,
                response_body=response.text[:2000],
            ) from exc
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise BrokerTransportError(
                "Alpaca response was not a JSON array of objects", transient=False
            )
        return data

    def list_positions(self) -> tuple[BrokerPositionSnapshot, ...]:
        rows = self._request_list("GET", "/v2/positions")
        observed = datetime.now(UTC)
        try:
            return tuple(
                BrokerPositionSnapshot(
                    symbol=str(row["symbol"]),
                    quantity=abs(Decimal(str(row.get("qty", "0")))),
                    average_entry_price=_decimal(row.get("avg_entry_price")),
                    observed_at=observed,
                    raw_response_hash=canonical_sha256(row),
                )
                for row in rows
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerTransportError(
                "Alpaca returned an invalid position payload", transient=True
            ) from exc

    def list_orders(self, *, status: str = "open") -> tuple[BrokerOrderSnapshot, ...]:
        rows = self._request_list("GET", "/v2/orders", params={"status": status, "nested": "true"})
        try:
            return tuple(normalize_order(row) for row in rows)
        except (KeyError, TypeError, ValueError) as exc:
            raise BrokerTransportError(
                "Alpaca returned an invalid order payload", transient=True
            ) from exc
