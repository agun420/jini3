import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from daybreak_scanner.cli import main
from daybreak_scanner.models import ActiveStock, MarketMover


class _FakeClient:
    closed = False

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

    def get_most_actives(self, *, top: int):
        return (
            ActiveStock(ticker="AAAA", volume=800_000, trade_count=1000),
            ActiveStock(ticker="BBBB", volume=800_000, trade_count=1000),
        )

    def get_daily_bars(self, symbols, *, start: date, end: date):
        return {symbol: () for symbol in symbols}

    def close(self) -> None:
        self.closed = True


def test_scan_requires_credentials(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert main(["scan", "--output-dir", str(tmp_path)]) == 2
    assert "APCA_API_KEY_ID" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


def test_scan_writes_a_dated_candidates_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setattr("daybreak_scanner.cli.AlpacaMarketDataClient", _FakeClient)

    assert main(["scan", "--output-dir", str(tmp_path)]) == 0

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["qualifying_tickers"] == ["AAAA"]
    assert len(payload["candidates"]) == 2
    assert payload["trading_date"] == files[0].stem.removeprefix("candidates-")
