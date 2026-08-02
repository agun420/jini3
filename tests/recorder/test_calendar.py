from __future__ import annotations

from datetime import date, time, timedelta

from daybreak_recorder.orchestration.calendar import MarketSessionSchedule, SessionController
from daybreak_recorder.settings import RecorderSettings


class EmptyCalendar:
    async def get_session(self, trading_date):
        return None


def test_early_close_caps_capture_at_close_plus_five_minutes() -> None:
    settings = RecorderSettings.model_validate({})
    controller = SessionController(calendar_provider=EmptyCalendar(), settings=settings)
    window = controller.resolve_window(
        MarketSessionSchedule(
            trading_date=date(2026, 11, 27),
            regular_open=time(9, 30),
            regular_close=time(13, 0),
        )
    )
    assert window.start_at.astimezone(controller._timezone).time() == time(4, 0)
    assert window.stop_at.astimezone(controller._timezone).time() == time(13, 5)


def test_normal_close_uses_configured_1605_stop() -> None:
    settings = RecorderSettings.model_validate({})
    controller = SessionController(calendar_provider=EmptyCalendar(), settings=settings)
    window = controller.resolve_window(
        MarketSessionSchedule(
            trading_date=date(2026, 7, 31),
            regular_open=time(9, 30),
            regular_close=time(16, 0),
        )
    )
    assert window.stop_at.astimezone(controller._timezone).time() == time(16, 5)


def test_preconnect_time_precedes_capture_start_by_configured_lead() -> None:
    settings = RecorderSettings(preconnect_lead_seconds=300)
    controller = SessionController(calendar_provider=EmptyCalendar(), settings=settings)
    schedule = MarketSessionSchedule(
        trading_date=date(2026, 7, 31),
        regular_open=time(9, 30),
        regular_close=time(16, 0),
    )
    window = controller.resolve_window(schedule)
    assert controller.preconnect_at(window) == window.start_at - timedelta(minutes=5)
