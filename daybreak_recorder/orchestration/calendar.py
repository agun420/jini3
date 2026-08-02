"""Exchange-calendar-aware capture-window calculation."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, model_validator

from ..settings import RecorderSettings


class MarketSessionSchedule(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    trading_date: date
    regular_open: time
    regular_close: time

    @model_validator(mode="after")
    def validate_market_hours(self) -> MarketSessionSchedule:
        if self.regular_close <= self.regular_open:
            raise ValueError("regular_close must be after regular_open")
        return self


class CaptureWindow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    trading_date: date
    start_at: datetime
    stop_at: datetime
    regular_open_at: datetime
    regular_close_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> CaptureWindow:
        values = (self.start_at, self.stop_at, self.regular_open_at, self.regular_close_at)
        if any(item.tzinfo is None or item.utcoffset() is None for item in values):
            raise ValueError("all capture-window datetimes must be timezone-aware")
        if self.stop_at <= self.start_at:
            raise ValueError("stop_at must be after start_at")
        return self


class CalendarProvider(Protocol):
    async def get_session(self, trading_date: date) -> MarketSessionSchedule | None: ...


class SessionController:
    def __init__(
        self,
        *,
        calendar_provider: CalendarProvider,
        settings: RecorderSettings,
    ) -> None:
        self._calendar_provider = calendar_provider
        self._settings = settings
        self._timezone = ZoneInfo(settings.timezone_name)

    def local_date(self, now: datetime | None = None) -> date:
        current = now or datetime.now(UTC)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return current.astimezone(self._timezone).date()

    async def resolve_today(self, now: datetime | None = None) -> CaptureWindow | None:
        trading_date = self.local_date(now)
        schedule = await self._calendar_provider.get_session(trading_date)
        if schedule is None:
            return None
        return self.resolve_window(schedule)

    def resolve_window(self, schedule: MarketSessionSchedule) -> CaptureWindow:
        local_start = datetime.combine(
            schedule.trading_date,
            self._settings.capture_start_et,
            tzinfo=self._timezone,
        )
        configured_stop = datetime.combine(
            schedule.trading_date,
            self._settings.capture_stop_et,
            tzinfo=self._timezone,
        )
        regular_open = datetime.combine(
            schedule.trading_date,
            schedule.regular_open,
            tzinfo=self._timezone,
        )
        regular_close = datetime.combine(
            schedule.trading_date,
            schedule.regular_close,
            tzinfo=self._timezone,
        )
        close_grace = regular_close + timedelta(minutes=5)
        local_stop = min(configured_stop, close_grace)
        return CaptureWindow(
            trading_date=schedule.trading_date,
            start_at=local_start.astimezone(UTC),
            stop_at=local_stop.astimezone(UTC),
            regular_open_at=regular_open.astimezone(UTC),
            regular_close_at=regular_close.astimezone(UTC),
        )

    def preconnect_at(self, window: CaptureWindow) -> datetime:
        return window.start_at - timedelta(seconds=self._settings.preconnect_lead_seconds)

    async def wait_until_preconnect(self, window: CaptureWindow) -> None:
        now = datetime.now(UTC)
        delay = (self.preconnect_at(window) - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

    async def wait_until_start(self, window: CaptureWindow) -> None:
        now = datetime.now(UTC)
        delay = (window.start_at - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)

    async def wait_until_stop(self, window: CaptureWindow) -> None:
        now = datetime.now(UTC)
        delay = (window.stop_at - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
