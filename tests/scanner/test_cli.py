import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from daybreak_scanner.cli import main
from daybreak_scanner.errors import ScannerTransportError
from daybreak_scanner.models import MarketMover, MinuteBar


def _daily_bars(count: int = 20):
    from daybreak_features.models import DailyBar

    return tuple(
        DailyBar(
            session_date=date(2026, 7, 1) + timedelta(days=i),
            open=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10"),
            volume=100,
        )
        for i in range(count)
    )


class _FakeClient:
    closed = False
    fail_bars = False
    minute_bars: tuple[MinuteBar, ...] = ()

    def __init__(self, *, api_key: str, secret_key: str) -> None:
        assert api_key == "key"
        assert secret_key == "secret"

    def get_gainers(self, *, top: int):
        return (
            MarketMover(
                ticker="AAAA",
                percent_change=Decimal("9.0"),
                change=Decimal("1"),
                price=Decimal("10"),
            ),
            MarketMover(
                ticker="BBBB",
                percent_change=Decimal("1.0"),
                change=Decimal("0.1"),
                price=Decimal("5"),
            ),
        )

    def get_current_volumes(self, symbols):
        return {"AAAA": 800_000, "BBBB": 800_000}

    def get_daily_bars(self, symbols, *, start: date, end: date):
        if self.fail_bars:
            raise ScannerTransportError("bars unavailable", transient=True)
        return {symbol: _daily_bars() for symbol in symbols}

    def get_minute_bars(self, symbol, *, start, end):
        return self.minute_bars

    def close(self) -> None:
        self.closed = True


def test_scan_requires_credentials(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert main(["scan", "--output-dir", str(tmp_path)]) == 2
    assert "APCA_API_KEY_ID" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


def test_scan_writes_dated_candidates_and_signals_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _FakeClient)

    assert main(["scan", "--output-dir", str(tmp_path)]) == 0

    files = {item.name: item for item in tmp_path.iterdir()}
    assert len(files) == 2
    candidates_file = next(f for name, f in files.items() if name.startswith("candidates-"))
    signals_file = next(f for name, f in files.items() if name.startswith("signals-"))

    candidates_payload = json.loads(candidates_file.read_text(encoding="utf-8"))
    assert candidates_payload["qualifying_tickers"] == ["AAAA"]
    assert len(candidates_payload["candidates"]) == 2

    signals_payload = json.loads(signals_file.read_text(encoding="utf-8"))
    assert len(signals_payload["signals"]) == 1
    signal = signals_payload["signals"][0]
    assert signal["ticker"] == "AAAA"
    assert Decimal(signal["entry_price"]) == Decimal("10")
    assert Decimal(signal["stop_price"]) == Decimal("8")
    assert Decimal(signal["target_price_1"]) == Decimal("14")
    assert Decimal(signal["target_price_2"]) == Decimal("16")


def test_scan_refuses_to_overwrite_an_existing_signals_file(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _FakeClient)

    assert main(["scan", "--output-dir", str(tmp_path)]) == 0
    signals_file = next(tmp_path.glob("signals-*.json"))
    original = signals_file.read_text(encoding="utf-8")

    class _ShouldNotBeCalledClient(_FakeClient):
        def get_gainers(self, *, top: int):
            raise AssertionError("a refused re-scan must not fetch anything")

    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _ShouldNotBeCalledClient)

    assert main(["scan", "--output-dir", str(tmp_path)]) == 5
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "--replace" in err
    assert signals_file.read_text(encoding="utf-8") == original


def test_scan_replace_flag_overwrites_an_existing_signals_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _FakeClient)

    assert main(["scan", "--output-dir", str(tmp_path)]) == 0
    assert main(["scan", "--output-dir", str(tmp_path), "--replace"]) == 0

    signals_file = next(tmp_path.glob("signals-*.json"))
    payload = json.loads(signals_file.read_text(encoding="utf-8"))
    assert len(payload["signals"]) == 1
    assert payload["signals"][0]["ticker"] == "AAAA"


def test_scan_degrades_gracefully_when_historical_bars_are_unavailable(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")

    class _FailingBarsClient(_FakeClient):
        fail_bars = True

    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _FailingBarsClient)

    assert main(["scan", "--output-dir", str(tmp_path)]) == 0
    assert "historical bars unavailable" in capsys.readouterr().err
    files = {item.name for item in tmp_path.iterdir()}
    assert len(files) == 2
    signals_file = next(tmp_path.glob("signals-*.json"))
    assert json.loads(signals_file.read_text(encoding="utf-8"))["signals"] == []


def test_check_outcomes_requires_credentials(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert (
        main(
            [
                "check-outcomes",
                "--signals-dir",
                str(tmp_path),
                "--outcomes-dir",
                str(tmp_path),
            ]
        )
        == 2
    )
    assert "APCA_API_KEY_ID" in capsys.readouterr().err


def test_check_outcomes_reports_missing_signals_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    assert (
        main(
            [
                "check-outcomes",
                "--signals-dir",
                str(tmp_path),
                "--outcomes-dir",
                str(tmp_path),
                "--trading-date",
                "2026-08-03",
            ]
        )
        == 4
    )
    assert "no signals file" in capsys.readouterr().err


def test_check_outcomes_resolves_a_win_from_minute_bars(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    signals_dir = tmp_path / "signals"
    outcomes_dir = tmp_path / "outcomes"
    signals_dir.mkdir()

    signals_path = signals_dir / "signals-2026-08-03.json"
    signals_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-03T13:35:00+00:00",
                "trading_date": "2026-08-03",
                "signals": [
                    {
                        "ticker": "AAAA",
                        "trading_date": "2026-08-03",
                        "generated_at": "2026-08-03T13:35:00+00:00",
                        "entry_price": "10.000000",
                        "atr_value": "2.000000",
                        "stop_price": "8.000000",
                        "target_price_1": "14.000000",
                        "target_price_2": "16.000000",
                        "percent_change": "9.0",
                        "relative_volume": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class _WinClient(_FakeClient):
        minute_bars = (
            MinuteBar(
                timestamp=datetime(2026, 8, 3, 14, 0, tzinfo=UTC),
                open=Decimal("14.5"),
                high=Decimal("14.5"),
                low=Decimal("13.9"),
                close=Decimal("14.5"),
                volume=1000,
            ),
        )

    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _WinClient)

    assert (
        main(
            [
                "check-outcomes",
                "--signals-dir",
                str(signals_dir),
                "--outcomes-dir",
                str(outcomes_dir),
                "--trading-date",
                "2026-08-03",
            ]
        )
        == 0
    )
    outcomes_path = outcomes_dir / "outcomes-2026-08-03.json"
    payload = json.loads(outcomes_path.read_text(encoding="utf-8"))
    assert len(payload["outcomes"]) == 1
    assert payload["outcomes"][0]["outcome"] == "win"

    scorecard = json.loads((outcomes_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["total_signals"] == 1
    assert scorecard["wins"] == 1
    assert scorecard["win_rate_pct"] == "100"


def test_check_outcomes_is_idempotent_and_skips_already_resolved_signals(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    signals_dir = tmp_path / "signals"
    outcomes_dir = tmp_path / "outcomes"
    signals_dir.mkdir()
    outcomes_dir.mkdir()

    (signals_dir / "signals-2026-08-03.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-08-03T13:35:00+00:00",
                "trading_date": "2026-08-03",
                "signals": [
                    {
                        "ticker": "AAAA",
                        "trading_date": "2026-08-03",
                        "generated_at": "2026-08-03T13:35:00+00:00",
                        "entry_price": "10.000000",
                        "atr_value": "2.000000",
                        "stop_price": "8.000000",
                        "target_price_1": "14.000000",
                        "target_price_2": "16.000000",
                        "percent_change": "9.0",
                        "relative_volume": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (outcomes_dir / "outcomes-2026-08-03.json").write_text(
        json.dumps(
            {
                "trading_date": "2026-08-03",
                "checked_at": "2026-08-03T15:00:00+00:00",
                "outcomes": [
                    {
                        "ticker": "AAAA",
                        "trading_date": "2026-08-03",
                        "resolved_at": "2026-08-03T14:00:00+00:00",
                        "outcome": "win",
                        "exit_price": "14.000000",
                        "return_pct": "40",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class _ShouldNotBeCalledClient(_FakeClient):
        def get_minute_bars(self, symbol, *, start, end):
            raise AssertionError("already-resolved signals must not be re-fetched")

    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _ShouldNotBeCalledClient)

    assert (
        main(
            [
                "check-outcomes",
                "--signals-dir",
                str(signals_dir),
                "--outcomes-dir",
                str(outcomes_dir),
                "--trading-date",
                "2026-08-03",
            ]
        )
        == 0
    )
    payload = json.loads((outcomes_dir / "outcomes-2026-08-03.json").read_text(encoding="utf-8"))
    assert len(payload["outcomes"]) == 1
    assert payload["outcomes"][0]["outcome"] == "win"


def test_check_outcomes_drops_orphaned_outcomes_not_in_current_signals(
    tmp_path: Path, monkeypatch
) -> None:
    # Simulates the real Aug 2026 incident: a `scan --replace` overwrote
    # signals-2026-08-03.json after BBBB's outcome had already been resolved
    # against the old signal set. BBBB no longer exists as a signal, so its
    # stale "loss" must not keep counting toward the scorecard.
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    signals_dir = tmp_path / "signals"
    outcomes_dir = tmp_path / "outcomes"
    signals_dir.mkdir()
    outcomes_dir.mkdir()

    (signals_dir / "signals-2026-08-03.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-08-03T16:00:00+00:00",
                "trading_date": "2026-08-03",
                "signals": [
                    {
                        "ticker": "AAAA",
                        "trading_date": "2026-08-03",
                        "generated_at": "2026-08-03T16:00:00+00:00",
                        "entry_price": "10.000000",
                        "atr_value": "2.000000",
                        "stop_price": "8.000000",
                        "target_price_1": "14.000000",
                        "target_price_2": "16.000000",
                        "percent_change": "9.0",
                        "relative_volume": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (outcomes_dir / "outcomes-2026-08-03.json").write_text(
        json.dumps(
            {
                "trading_date": "2026-08-03",
                "checked_at": "2026-08-03T15:00:00+00:00",
                "outcomes": [
                    {
                        "ticker": "AAAA",
                        "trading_date": "2026-08-03",
                        "resolved_at": "2026-08-03T14:00:00+00:00",
                        "outcome": "win",
                        "exit_price": "14.000000",
                        "return_pct": "40",
                    },
                    {
                        "ticker": "BBBB",
                        "trading_date": "2026-08-03",
                        "resolved_at": "2026-08-03T13:00:00+00:00",
                        "outcome": "loss",
                        "exit_price": "4.000000",
                        "return_pct": "-20",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    class _ShouldNotBeCalledClient(_FakeClient):
        def get_minute_bars(self, symbol, *, start, end):
            raise AssertionError("already-resolved signals must not be re-fetched")

    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _ShouldNotBeCalledClient)

    assert (
        main(
            [
                "check-outcomes",
                "--signals-dir",
                str(signals_dir),
                "--outcomes-dir",
                str(outcomes_dir),
                "--trading-date",
                "2026-08-03",
            ]
        )
        == 0
    )
    payload = json.loads((outcomes_dir / "outcomes-2026-08-03.json").read_text(encoding="utf-8"))
    tickers = {item["ticker"] for item in payload["outcomes"]}
    assert tickers == {"AAAA"}

    scorecard = json.loads((outcomes_dir / "scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["total_signals"] == 1
    assert scorecard["wins"] == 1
    assert scorecard["losses"] == 0
    assert scorecard["win_rate_pct"] == "100"


def test_dashboard_snapshot_needs_no_credentials_and_writes_a_private_file(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    scanner_dir = tmp_path / "scanner"
    outcomes_dir = tmp_path / "outcomes"
    scanner_dir.mkdir()
    outcomes_dir.mkdir()
    output_path = tmp_path / "private.json"

    assert (
        main(
            [
                "dashboard-snapshot",
                "--scanner-dir",
                str(scanner_dir),
                "--outcomes-dir",
                str(outcomes_dir),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    assert "never commit it" in capsys.readouterr().err
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["public_safe"] is False
    assert payload["signals"] == []


def test_dashboard_snapshot_public_flag_writes_a_publishable_file(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    scanner_dir = tmp_path / "scanner"
    outcomes_dir = tmp_path / "outcomes"
    scanner_dir.mkdir()
    outcomes_dir.mkdir()
    output_path = tmp_path / "dashboard.json"

    assert (
        main(
            [
                "dashboard-snapshot",
                "--scanner-dir",
                str(scanner_dir),
                "--outcomes-dir",
                str(outcomes_dir),
                "--output",
                str(output_path),
                "--public",
            ]
        )
        == 0
    )
    err = capsys.readouterr().err
    assert "public dashboard snapshot" in err
    assert "never commit it" not in err
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["public_safe"] is True
    assert payload["data_mode"] == "published"


def test_scan_with_forecast_degrades_gracefully_when_timesfm_is_not_installed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    # timesfm is an opt-in extra (pip install '.[forecast]') never installed
    # in this project's own dev/CI environment, so this exercises the real
    # graceful-degradation path rather than a simulated failure.
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _FakeClient)

    assert main(["scan", "--output-dir", str(tmp_path), "--with-forecast"]) == 0
    assert "forecast unavailable" in capsys.readouterr().err

    signals_file = next(tmp_path.glob("signals-*.json"))
    payload = json.loads(signals_file.read_text(encoding="utf-8"))
    assert len(payload["signals"]) == 1
    assert payload["signals"][0]["forecast_trend_pct"] is None
