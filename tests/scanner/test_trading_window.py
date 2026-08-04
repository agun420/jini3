from datetime import UTC, datetime, time

from daybreak_scanner.trading_window import in_trading_window, main


def test_in_trading_window_true_inside_the_window_on_a_weekday() -> None:
    # 2026-08-03 is a Monday; 13:35 UTC is 09:35 America/New_York (EDT, UTC-4).
    now = datetime(2026, 8, 3, 13, 35, tzinfo=UTC)
    assert in_trading_window(now, start=time(9, 30), end=time(9, 50))


def test_in_trading_window_false_outside_the_window_same_day() -> None:
    now = datetime(2026, 8, 3, 14, 35, tzinfo=UTC)  # 10:35 ET, past the window
    assert not in_trading_window(now, start=time(9, 30), end=time(9, 50))


def test_in_trading_window_handles_the_est_offset_too() -> None:
    # 2026-01-05 is a Monday in EST (UTC-5): 14:35 UTC is 09:35 ET.
    now = datetime(2026, 1, 5, 14, 35, tzinfo=UTC)
    assert in_trading_window(now, start=time(9, 30), end=time(9, 50))
    # The EDT-aligned UTC tick (13:35) is 08:35 ET in winter -- outside the window.
    winter_edt_tick = datetime(2026, 1, 5, 13, 35, tzinfo=UTC)
    assert not in_trading_window(winter_edt_tick, start=time(9, 30), end=time(9, 50))


def test_in_trading_window_false_on_a_weekend() -> None:
    # 2026-08-08 is a Saturday, 13:35 UTC is still 09:35 America/New_York.
    now = datetime(2026, 8, 8, 13, 35, tzinfo=UTC)
    assert not in_trading_window(now, start=time(9, 30), end=time(9, 50))


def test_main_requires_exactly_two_arguments(capsys) -> None:
    assert main([]) == 64
    assert "usage" in capsys.readouterr().err


def test_main_returns_nonzero_outside_the_window(monkeypatch, capsys) -> None:
    # A fixed Saturday makes this deterministic regardless of when it runs.
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime(2026, 8, 8, 13, 35, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr("daybreak_scanner.trading_window.datetime", _FixedDatetime)
    assert main(["09:30", "09:50"]) == 1
    assert "skipping" in capsys.readouterr().err
