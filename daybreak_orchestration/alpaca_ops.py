from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from .canonical import canonical_sha256
from .models import FlattenOrder, ManagedPositionTarget, SessionPlan, SessionPosition

PAPER_BASE_URL = "https://paper-api.alpaca.markets"


class AlpacaOperationsError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        transient: bool,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.status_code = status_code
        self.request_id = request_id


class AlpacaPaperOperations:
    """Paper-only account, clock, order-cancel, and position-flatten operations."""

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
            raise ValueError("Project Daybreak v1.0.2 permits only the Alpaca paper endpoint")
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
        self.last_request_id: str | None = None

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AlpacaOperationsError(str(exc), transient=True) from exc
        self.last_request_id = response.headers.get("X-Request-ID")
        if response.is_error:
            transient = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
            raise AlpacaOperationsError(
                f"Alpaca returned HTTP {response.status_code}",
                transient=transient,
                status_code=response.status_code,
                request_id=self.last_request_id,
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise AlpacaOperationsError(
                "Alpaca returned malformed JSON",
                transient=True,
                status_code=response.status_code,
                request_id=self.last_request_id,
            ) from exc

    def get_account(self) -> dict[str, Any]:
        data = self._request("GET", "/v2/account")
        if not isinstance(data, dict):
            raise AlpacaOperationsError("account response was not an object", transient=False)
        return data

    def get_clock(self) -> dict[str, Any]:
        data = self._request("GET", "/v2/clock")
        if not isinstance(data, dict):
            raise AlpacaOperationsError("clock response was not an object", transient=False)
        return data

    @staticmethod
    def _prefix(plan: SessionPlan) -> str:
        return f"DB-{plan.trading_date.strftime('%Y%m%d')}-"

    def _orders(self, *, status: str, after: datetime) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            "/v2/orders",
            params={
                "status": status,
                "limit": 500,
                "nested": "true",
                "direction": "asc",
                "after": after.isoformat(),
            },
        )
        if not isinstance(data, list):
            raise AlpacaOperationsError("orders response was not an array", transient=False)
        if not all(isinstance(item, dict) for item in data):
            raise AlpacaOperationsError("order entry was not an object", transient=False)
        return data

    def discover_daybreak_targets(self, plan: SessionPlan) -> tuple[ManagedPositionTarget, ...]:
        prefix = self._prefix(plan)
        orders = self._orders(status="all", after=plan.recorder_warmup_at)
        owned_ids = {
            str(order.get("id"))
            for order in orders
            if order.get("id") and str(order.get("client_order_id", "")).startswith(prefix)
        }
        for order in orders:
            if str(order.get("id", "")) not in owned_ids:
                continue
            owned_ids.update(
                str(leg.get("id"))
                for leg in order.get("legs") or []
                if isinstance(leg, dict) and leg.get("id")
            )
        owned_ids.update(
            str(order.get("id"))
            for order in orders
            if order.get("id") and str(order.get("parent_order_id", "")) in owned_ids
        )
        net: dict[str, Decimal] = {}
        seen: set[str] = set()

        def apply_fill(order: dict[str, Any], parent_symbol: str = "") -> None:
            order_id = str(order.get("id", ""))
            if not order_id or order_id in seen or order_id not in owned_ids:
                return
            seen.add(order_id)
            symbol = str(order.get("symbol") or parent_symbol)
            if not symbol:
                return
            side = str(order.get("side", ""))
            filled = Decimal(str(order.get("filled_qty", "0") or "0"))
            net[symbol] = net.get(symbol, Decimal("0")) + (filled if side == "buy" else -filled)

        for order in orders:
            symbol = str(order.get("symbol", ""))
            apply_fill(order)
            for leg in order.get("legs") or []:
                if isinstance(leg, dict):
                    apply_fill(leg, symbol)
        return tuple(
            ManagedPositionTarget(
                symbol=symbol, quantity=quantity, source="broker_order_reconstruction"
            )
            for symbol, quantity in sorted(net.items())
            if quantity > 0
        )

    def cancel_daybreak_orders(self, plan: SessionPlan) -> int:
        prefix = self._prefix(plan)
        all_orders = self._orders(status="all", after=plan.recorder_warmup_at)
        owned_ids: set[str] = set()
        for order in all_orders:
            if str(order.get("client_order_id", "")).startswith(prefix):
                if order.get("id"):
                    owned_ids.add(str(order["id"]))
                owned_ids.update(
                    str(leg["id"])
                    for leg in order.get("legs") or []
                    if isinstance(leg, dict) and leg.get("id")
                )
        for order in all_orders:
            if str(order.get("parent_order_id", "")) in owned_ids and order.get("id"):
                owned_ids.add(str(order["id"]))
        count = 0
        for order in self._orders(status="open", after=plan.recorder_warmup_at):
            order_id = str(order.get("id", ""))
            owned = (
                order_id in owned_ids
                or str(order.get("client_order_id", "")).startswith(prefix)
                or str(order.get("parent_order_id", "")) in owned_ids
            )
            if not owned:
                continue
            if not order_id:
                raise AlpacaOperationsError("Daybreak order missing broker id", transient=False)
            self._request("DELETE", f"/v2/orders/{order_id}")
            count += 1
        return count

    def list_positions(
        self, targets: Sequence[ManagedPositionTarget]
    ) -> tuple[SessionPosition, ...]:
        observed_at = datetime.now(UTC)
        positions: list[SessionPosition] = []
        for target in sorted(targets, key=lambda item: item.symbol):
            symbol = target.symbol
            try:
                raw = self._request("GET", f"/v2/positions/{symbol}")
            except AlpacaOperationsError as exc:
                if exc.status_code == 404:
                    continue
                raise
            if not isinstance(raw, dict):
                raise AlpacaOperationsError("position response was not an object", transient=False)
            account_quantity = abs(Decimal(str(raw.get("qty", "0"))))
            quantity = min(account_quantity, target.quantity)
            if quantity <= 0:
                continue
            avg = raw.get("avg_entry_price")
            positions.append(
                SessionPosition(
                    symbol=str(raw["symbol"]),
                    quantity=quantity,
                    average_entry_price=None if avg in (None, "") else Decimal(str(avg)),
                    observed_at=observed_at,
                    raw_response_hash=canonical_sha256(raw),
                )
            )
        return tuple(positions)

    def close_position(self, position: SessionPosition) -> FlattenOrder:
        data = self._request(
            "DELETE",
            f"/v2/positions/{position.symbol}",
            params={"qty": format(position.quantity, "f")},
        )
        if not isinstance(data, dict):
            raise AlpacaOperationsError(
                "close-position response was not an object", transient=False
            )
        submitted_at = _parse_timestamp(data.get("submitted_at"))
        return FlattenOrder(
            symbol=position.symbol,
            quantity=position.quantity,
            broker_order_id=str(data["id"]),
            client_order_id=None
            if data.get("client_order_id") is None
            else str(data["client_order_id"]),
            submitted_at=submitted_at,
            raw_response_hash=canonical_sha256(data),
        )

    def account_probe(self) -> tuple[bool, str, dict[str, object]]:
        account = self.get_account()
        active = str(account.get("status", "")).upper() == "ACTIVE"
        blocked = bool(account.get("account_blocked") or account.get("trading_blocked"))
        return (
            active and not blocked,
            "Paper account is active and unblocked."
            if active and not blocked
            else "Paper account is not eligible.",
            {
                "status": str(account.get("status", "")),
                "account_blocked": bool(account.get("account_blocked", False)),
                "trading_blocked": bool(account.get("trading_blocked", False)),
                "request_id": self.last_request_id,
            },
        )

    def clock_probe(self) -> tuple[bool, str, dict[str, object]]:
        clock = self.get_clock()
        return (
            "timestamp" in clock and "next_open" in clock and "next_close" in clock,
            "Alpaca market clock responded with required fields.",
            {
                "is_open": bool(clock.get("is_open", False)),
                "timestamp": str(clock.get("timestamp", "")),
                "next_open": str(clock.get("next_open", "")),
                "next_close": str(clock.get("next_close", "")),
                "request_id": self.last_request_id,
            },
        )


def _parse_timestamp(value: Any) -> datetime:
    if value in (None, ""):
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
