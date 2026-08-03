from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from daybreak_features.models import DailyBar

from .errors import ScannerTransportError
from .models import ActiveStock, MarketMover

DATA_BASE_URL = "https://data.alpaca.markets"


class AlpacaMarketDataClient:
    """Read-only client for Alpaca's market-data endpoints (screener and bars).

    Uses the same API key/secret as trading, against a different host
    (`data.alpaca.markets`) that is not paper/live gated. The screener lives
    under `/v1beta1`, historical bars under `/v2` — each method passes its own
    full versioned path rather than relying on a single fixed base path.
    """

    def __init__(
        self,
        *,
        api_key: str,
        secret_key: str,
        base_url: str = DATA_BASE_URL,
        timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key or not secret_key:
            raise ValueError("Alpaca market data credentials are required")
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ScannerTransportError(str(exc), transient=True) from exc
        if response.is_error:
            transient = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
            raise ScannerTransportError(
                f"Alpaca market data returned HTTP {response.status_code}",
                transient=transient,
                status_code=response.status_code,
                response_body=response.text[:2000],
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ScannerTransportError(
                "Alpaca market data response was not valid JSON",
                transient=True,
                status_code=response.status_code,
                response_body=response.text[:2000],
            ) from exc
        if not isinstance(data, dict):
            raise ScannerTransportError(
                "Alpaca market data response was not a JSON object", transient=False
            )
        return data

    def get_gainers(self, *, top: int = 50) -> tuple[MarketMover, ...]:
        data = self._request("GET", "/v1beta1/screener/stocks/movers", params={"top": top})
        rows = data.get("gainers")
        if not isinstance(rows, list):
            raise ScannerTransportError(
                "Alpaca movers response was missing a 'gainers' list", transient=False
            )
        try:
            return tuple(
                MarketMover(
                    ticker=str(row["symbol"]),
                    percent_change=Decimal(str(row["percent_change"])),
                    change=Decimal(str(row["change"])),
                    price=Decimal(str(row["price"])),
                )
                for row in rows
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ScannerTransportError(
                "Alpaca movers response contained an invalid row", transient=True
            ) from exc

    def get_most_actives(self, *, top: int = 50, by: str = "volume") -> tuple[ActiveStock, ...]:
        data = self._request(
            "GET", "/v1beta1/screener/stocks/most-actives", params={"top": top, "by": by}
        )
        rows = data.get("most_actives")
        if not isinstance(rows, list):
            raise ScannerTransportError(
                "Alpaca most-actives response was missing a 'most_actives' list", transient=False
            )
        try:
            return tuple(
                ActiveStock(
                    ticker=str(row["symbol"]),
                    volume=int(row["volume"]),
                    trade_count=int(row["trade_count"]),
                )
                for row in rows
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ScannerTransportError(
                "Alpaca most-actives response contained an invalid row", transient=True
            ) from exc

    def get_daily_bars(
        self, symbols: Sequence[str], *, start: date, end: date
    ) -> dict[str, tuple[DailyBar, ...]]:
        """Split-adjusted daily bars per symbol, matching DailyBar's fixed
        split_adjusted=True/dividend_adjusted=False contract."""
        if not symbols:
            return {}
        raw_bars: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "symbols": ",".join(symbols),
                "timeframe": "1Day",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "adjustment": "split",
                "limit": 10_000,
            }
            if page_token is not None:
                params["page_token"] = page_token
            data = self._request("GET", "/v2/stocks/bars", params=params)
            bars_by_symbol = data.get("bars")
            if not isinstance(bars_by_symbol, dict):
                raise ScannerTransportError(
                    "Alpaca bars response was missing a 'bars' object", transient=False
                )
            for symbol, rows in bars_by_symbol.items():
                if not isinstance(rows, list):
                    raise ScannerTransportError(
                        f"Alpaca bars response for {symbol!r} was not a list", transient=False
                    )
                raw_bars.setdefault(str(symbol), []).extend(rows)
            page_token = data.get("next_page_token")
            if not page_token:
                break
        try:
            return {
                symbol: tuple(
                    DailyBar(
                        session_date=date.fromisoformat(str(row["t"])[:10]),
                        open=Decimal(str(row["o"])),
                        high=Decimal(str(row["h"])),
                        low=Decimal(str(row["l"])),
                        close=Decimal(str(row["c"])),
                        volume=int(row["v"]),
                    )
                    for row in rows
                )
                for symbol, rows in raw_bars.items()
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise ScannerTransportError(
                "Alpaca bars response contained an invalid row", transient=True
            ) from exc
