from datetime import date
from decimal import Decimal

import httpx
import pytest

from daybreak_scanner.alpaca_data import AlpacaMarketDataClient
from daybreak_scanner.errors import ScannerTransportError


def test_get_gainers_parses_the_gainers_list():
    seen = {}

    def handler(req: httpx.Request):
        seen["path"] = req.url.path
        seen["key"] = req.headers["APCA-API-KEY-ID"]
        seen["top"] = dict(req.url.params)["top"]
        return httpx.Response(
            200,
            json={
                "gainers": [
                    {"symbol": "AAAA", "percent_change": 12.5, "change": 1.1, "price": 9.9},
                ],
                "losers": [
                    {"symbol": "ZZZZ", "percent_change": -8.0, "change": -0.5, "price": 5.0}
                ],
                "market_type": "stocks",
                "last_updated": "2026-08-03T12:00:00Z",
            },
        )

    client = AlpacaMarketDataClient(
        api_key="k", secret_key="s", transport=httpx.MockTransport(handler)
    )
    gainers = client.get_gainers(top=10)
    assert seen["path"] == "/v1beta1/screener/stocks/movers"
    assert seen["key"] == "k"
    assert seen["top"] == "10"
    assert len(gainers) == 1
    assert gainers[0].ticker == "AAAA"
    assert gainers[0].percent_change == Decimal("12.5")
    client.close()


def test_get_most_actives_parses_the_most_actives_list():
    def handler(req: httpx.Request):
        return httpx.Response(
            200,
            json={
                "most_actives": [
                    {"symbol": "BBBB", "volume": 900_000, "trade_count": 4200},
                ],
                "last_updated": "2026-08-03T12:00:00Z",
            },
        )

    client = AlpacaMarketDataClient(
        api_key="k", secret_key="s", transport=httpx.MockTransport(handler)
    )
    actives = client.get_most_actives(top=10)
    assert len(actives) == 1
    assert actives[0].ticker == "BBBB"
    assert actives[0].volume == 900_000
    client.close()


def test_missing_credentials_are_rejected():
    with pytest.raises(ValueError, match="credentials are required"):
        AlpacaMarketDataClient(api_key="", secret_key="s")


def test_http_error_is_classified_as_transport_error():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(lambda req: httpx.Response(503, text="down")),
    )
    with pytest.raises(ScannerTransportError) as exc:
        client.get_gainers()
    assert exc.value.transient is True
    client.close()


def test_missing_gainers_key_is_rejected():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"losers": []})),
    )
    with pytest.raises(ScannerTransportError, match="gainers"):
        client.get_gainers()
    client.close()


def test_missing_most_actives_key_is_rejected():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})),
    )
    with pytest.raises(ScannerTransportError, match="most_actives"):
        client.get_most_actives()
    client.close()


def test_malformed_row_raises_transient_transport_error():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"gainers": [{"symbol": "AAAA"}]})
        ),
    )
    with pytest.raises(ScannerTransportError) as exc:
        client.get_gainers()
    assert exc.value.transient is True
    client.close()


def test_non_json_object_response_is_rejected():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[1, 2, 3])),
    )
    with pytest.raises(ScannerTransportError, match="JSON object"):
        client.get_gainers()
    client.close()


def test_get_daily_bars_parses_split_adjusted_bars_per_symbol():
    seen = {}

    def handler(req: httpx.Request):
        seen["path"] = req.url.path
        seen["params"] = dict(req.url.params)
        return httpx.Response(
            200,
            json={
                "bars": {
                    "AAAA": [
                        {
                            "t": "2026-07-01T04:00:00Z",
                            "o": 10.0,
                            "h": 11.0,
                            "l": 9.5,
                            "c": 10.5,
                            "v": 100_000,
                            "n": 500,
                            "vw": 10.2,
                        },
                    ]
                },
                "next_page_token": None,
            },
        )

    client = AlpacaMarketDataClient(
        api_key="k", secret_key="s", transport=httpx.MockTransport(handler)
    )
    bars = client.get_daily_bars(["AAAA"], start=date(2026, 7, 1), end=date(2026, 7, 1))
    assert seen["path"] == "/v2/stocks/bars"
    assert seen["params"]["symbols"] == "AAAA"
    assert seen["params"]["timeframe"] == "1Day"
    assert seen["params"]["adjustment"] == "split"
    assert list(bars.keys()) == ["AAAA"]
    assert len(bars["AAAA"]) == 1
    assert bars["AAAA"][0].session_date == date(2026, 7, 1)
    assert bars["AAAA"][0].volume == 100_000
    assert bars["AAAA"][0].split_adjusted is True
    assert bars["AAAA"][0].dividend_adjusted is False
    client.close()


def test_get_daily_bars_empty_symbols_makes_no_request():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(
            lambda req: (_ for _ in ()).throw(AssertionError("should not be called"))
        ),
    )
    assert client.get_daily_bars([], start=date(2026, 7, 1), end=date(2026, 7, 1)) == {}
    client.close()


def test_get_daily_bars_symbol_with_no_history_is_an_empty_tuple():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"bars": {}, "next_page_token": None})
        ),
    )
    bars = client.get_daily_bars(["AAAA"], start=date(2026, 7, 1), end=date(2026, 7, 1))
    assert bars == {"AAAA": ()}
    client.close()


def test_get_daily_bars_follows_pagination():
    calls = []

    def handler(req: httpx.Request):
        token = dict(req.url.params).get("page_token")
        calls.append(token)
        if token is None:
            return httpx.Response(
                200,
                json={
                    "bars": {
                        "AAAA": [
                            {"t": "2026-07-01T04:00:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 10}
                        ]
                    },
                    "next_page_token": "page-2",
                },
            )
        return httpx.Response(
            200,
            json={
                "bars": {
                    "AAAA": [{"t": "2026-07-02T04:00:00Z", "o": 2, "h": 3, "l": 2, "c": 3, "v": 20}]
                },
                "next_page_token": None,
            },
        )

    client = AlpacaMarketDataClient(
        api_key="k", secret_key="s", transport=httpx.MockTransport(handler)
    )
    bars = client.get_daily_bars(["AAAA"], start=date(2026, 7, 1), end=date(2026, 7, 2))
    assert calls == [None, "page-2"]
    assert len(bars["AAAA"]) == 2
    client.close()


def test_get_daily_bars_missing_bars_key_is_rejected():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})),
    )
    with pytest.raises(ScannerTransportError, match="bars"):
        client.get_daily_bars(["AAAA"], start=date(2026, 7, 1), end=date(2026, 7, 1))
    client.close()


def test_get_daily_bars_malformed_row_raises_transient_transport_error():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, json={"bars": {"AAAA": [{"t": "2026-07-01T00:00:00Z"}]}}
            )
        ),
    )
    with pytest.raises(ScannerTransportError) as exc:
        client.get_daily_bars(["AAAA"], start=date(2026, 7, 1), end=date(2026, 7, 1))
    assert exc.value.transient is True
    client.close()


def test_get_current_volumes_reads_daily_bar_volume_per_symbol():
    seen = {}

    def handler(req: httpx.Request):
        seen["path"] = req.url.path
        seen["symbols"] = dict(req.url.params)["symbols"]
        return httpx.Response(
            200,
            json={
                "AAAA": {
                    "dailyBar": {
                        "t": "2026-08-03T04:00:00Z",
                        "o": 1,
                        "h": 2,
                        "l": 1,
                        "c": 2,
                        "v": 750_000,
                    },
                    "latestTrade": {"p": 2.0},
                },
                "BBBB": {"dailyBar": None},
            },
        )

    client = AlpacaMarketDataClient(
        api_key="k", secret_key="s", transport=httpx.MockTransport(handler)
    )
    volumes = client.get_current_volumes(["AAAA", "BBBB"])
    assert seen["path"] == "/v2/stocks/snapshots"
    assert seen["symbols"] == "AAAA,BBBB"
    assert volumes == {"AAAA": 750_000}
    client.close()


def test_get_current_volumes_empty_symbols_makes_no_request():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(
            lambda req: (_ for _ in ()).throw(AssertionError("should not be called"))
        ),
    )
    assert client.get_current_volumes([]) == {}
    client.close()


def test_get_current_volumes_invalid_volume_raises_transient_transport_error():
    client = AlpacaMarketDataClient(
        api_key="k",
        secret_key="s",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"AAAA": {"dailyBar": {"v": "not-a-number"}}})
        ),
    )
    with pytest.raises(ScannerTransportError) as exc:
        client.get_current_volumes(["AAAA"])
    assert exc.value.transient is True
    client.close()
