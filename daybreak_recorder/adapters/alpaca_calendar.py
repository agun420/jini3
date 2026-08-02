"""Alpaca market-calendar adapter."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time
from typing import Any

from ..orchestration.calendar import MarketSessionSchedule


class AlpacaCalendarAdapter:
    def __init__(self, *, api_key: str, secret_key: str, paper: bool = True) -> None:
        self._api_key = api_key
        self._secret_key = secret_key
        self._paper = paper
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from alpaca.trading.client import TradingClient
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("alpaca-py is required for calendar access") from exc
            self._client = TradingClient(
                self._api_key,
                self._secret_key,
                paper=self._paper,
            )
        return self._client

    async def get_session(self, trading_date: date) -> MarketSessionSchedule | None:
        try:
            from alpaca.trading.requests import GetCalendarRequest
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("alpaca-py is required for calendar access") from exc

        client = self._get_client()
        request = GetCalendarRequest(start=trading_date, end=trading_date)
        calendars = await asyncio.to_thread(client.get_calendar, request)
        if not calendars:
            return None
        item = calendars[0]
        item_date = item.date
        open_value = item.open
        close_value = item.close
        return MarketSessionSchedule(
            trading_date=item_date,
            regular_open=self._coerce_time(open_value),
            regular_close=self._coerce_time(close_value),
        )

    @staticmethod
    def _coerce_time(value: Any) -> time:
        if isinstance(value, time):
            return value.replace(tzinfo=None)
        if isinstance(value, datetime):
            return value.timetz().replace(tzinfo=None)
        if isinstance(value, str):
            return time.fromisoformat(value)
        raise TypeError(f"unsupported Alpaca calendar time: {value!r}")
