import json
from pathlib import Path

from daybreak_scanner.dashboard_export import build_scanner_dashboard_snapshot


def _write_signals(scanner_dir: Path, trading_date: str) -> None:
    (scanner_dir / f"signals-{trading_date}.json").write_text(
        json.dumps(
            {
                "generated_at": f"{trading_date}T13:35:00+00:00",
                "trading_date": trading_date,
                "signals": [
                    {
                        "ticker": "AAAA",
                        "trading_date": trading_date,
                        "generated_at": f"{trading_date}T13:35:00+00:00",
                        "entry_price": "20.000000",
                        "atr_value": "2.000000",
                        "stop_price": "18.000000",
                        "target_price": "24.000000",
                        "percent_change": "9.0",
                        "relative_volume": "6.0",
                    },
                    {
                        "ticker": "BBBB",
                        "trading_date": trading_date,
                        "generated_at": f"{trading_date}T13:35:00+00:00",
                        "entry_price": "10.000000",
                        "atr_value": "1.000000",
                        "stop_price": "9.000000",
                        "target_price": "12.000000",
                        "percent_change": "15.0",
                        "relative_volume": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_outcomes(outcomes_dir: Path, trading_date: str) -> None:
    (outcomes_dir / f"outcomes-{trading_date}.json").write_text(
        json.dumps(
            {
                "trading_date": trading_date,
                "checked_at": f"{trading_date}T20:00:00+00:00",
                "outcomes": [
                    {
                        "ticker": "AAAA",
                        "trading_date": trading_date,
                        "resolved_at": f"{trading_date}T14:00:00+00:00",
                        "outcome": "win",
                        "exit_price": "24.000000",
                        "return_pct": "20",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (outcomes_dir / "scorecard.json").write_text(
        json.dumps(
            {
                "updated_at": f"{trading_date}T20:00:00+00:00",
                "total_signals": 1,
                "wins": 1,
                "losses": 0,
                "expired": 0,
                "win_rate_pct": "100",
                "average_return_pct": "20",
            }
        ),
        encoding="utf-8",
    )


def test_build_scanner_dashboard_snapshot_maps_signals_and_scorecard(tmp_path: Path) -> None:
    scanner_dir = tmp_path / "scanner"
    outcomes_dir = tmp_path / "outcomes"
    scanner_dir.mkdir()
    outcomes_dir.mkdir()
    _write_signals(scanner_dir, "2026-08-03")
    _write_outcomes(outcomes_dir, "2026-08-03")

    snapshot = build_scanner_dashboard_snapshot(scanner_dir=scanner_dir, outcomes_dir=outcomes_dir)

    assert snapshot["data_mode"] == "local"
    assert snapshot["public_safe"] is False
    assert "no evaluator" in snapshot["system"]["name"]
    assert snapshot["session"]["trading_date"] == "2026-08-03"

    # Ranked by percent_change descending: BBBB (15%) before AAAA (9%).
    tickers = [item["ticker"] for item in snapshot["signals"]]
    assert tickers == ["BBBB", "AAAA"]
    aaaa = next(item for item in snapshot["signals"] if item["ticker"] == "AAAA")
    assert aaaa["execution_status"] == "win"
    assert aaaa["status"] == "scanner_signal"
    bbbb = next(item for item in snapshot["signals"] if item["ticker"] == "BBBB")
    assert bbbb["execution_status"] == "pending"

    summary = snapshot["performance"]["summary"]
    assert summary["trade_count"] == 1
    assert summary["winning_trade_count"] == 1
    assert summary["win_rate"] == 1.0
    assert summary["profit_factor"] is None
    assert summary["net_pnl"] is None


def test_build_scanner_dashboard_snapshot_with_no_data_yet(tmp_path: Path) -> None:
    scanner_dir = tmp_path / "scanner"
    outcomes_dir = tmp_path / "outcomes"
    scanner_dir.mkdir()
    outcomes_dir.mkdir()

    snapshot = build_scanner_dashboard_snapshot(scanner_dir=scanner_dir, outcomes_dir=outcomes_dir)
    assert snapshot["signals"] == []
    assert snapshot["performance"]["summary"]["trade_count"] == 0
    assert snapshot["performance"]["summary"]["win_rate"] is None
    assert snapshot["positions"] == []
    assert snapshot["orders"] == []


def test_build_scanner_dashboard_snapshot_public_mode_sets_published_and_safe(
    tmp_path: Path,
) -> None:
    scanner_dir = tmp_path / "scanner"
    outcomes_dir = tmp_path / "outcomes"
    scanner_dir.mkdir()
    outcomes_dir.mkdir()
    _write_signals(scanner_dir, "2026-08-03")
    _write_outcomes(outcomes_dir, "2026-08-03")

    snapshot = build_scanner_dashboard_snapshot(
        scanner_dir=scanner_dir, outcomes_dir=outcomes_dir, public=True
    )

    assert snapshot["data_mode"] == "published"
    assert snapshot["public_safe"] is True
    # Public mode only changes the two visibility flags above -- the signal
    # content itself is identical to the private snapshot.
    tickers = [item["ticker"] for item in snapshot["signals"]]
    assert tickers == ["BBBB", "AAAA"]


def test_build_scanner_dashboard_snapshot_uses_the_most_recent_signals_file(tmp_path: Path) -> None:
    scanner_dir = tmp_path / "scanner"
    outcomes_dir = tmp_path / "outcomes"
    scanner_dir.mkdir()
    outcomes_dir.mkdir()
    _write_signals(scanner_dir, "2026-08-01")
    _write_signals(scanner_dir, "2026-08-03")

    snapshot = build_scanner_dashboard_snapshot(scanner_dir=scanner_dir, outcomes_dir=outcomes_dir)
    assert snapshot["session"]["trading_date"] == "2026-08-03"
