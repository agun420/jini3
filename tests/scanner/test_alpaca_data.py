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
