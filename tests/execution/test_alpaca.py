import json

import httpx
import pytest

from daybreak_execution.alpaca import AlpacaPaperBroker, command_payload
from daybreak_execution.errors import BrokerNotFound, BrokerTransportError
from daybreak_execution.order_builder import build_entry_command
from tests.execution.helpers import execution_request


def _order_json(command):
    return {
        "id": "alpaca-1",
        "client_order_id": command.client_order_id,
        "symbol": command.symbol,
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "order_class": "bracket",
        "status": "new",
        "qty": str(command.quantity),
        "filled_qty": "0",
        "limit_price": str(command.limit_price),
        "stop_price": None,
        "submitted_at": "2026-08-03T13:30:01Z",
        "updated_at": "2026-08-03T13:30:01Z",
        "legs": [
            {
                "id": "alpaca-1-tp",
                "side": "sell",
                "type": "limit",
                "status": "held",
                "qty": str(command.quantity),
                "filled_qty": "0",
                "limit_price": str(command.take_profit_limit_price),
            },
            {
                "id": "alpaca-1-sl",
                "side": "sell",
                "type": "stop",
                "status": "held",
                "qty": str(command.quantity),
                "filled_qty": "0",
                "stop_price": str(command.stop_loss_stop_price),
            },
        ],
    }


def test_command_payload_is_day_limit_bracket():
    command = build_entry_command(execution_request(), now=execution_request().requested_at)
    payload = command_payload(command)
    assert payload["type"] == "limit"
    assert payload["time_in_force"] == "day"
    assert payload["order_class"] == "bracket"
    assert payload["extended_hours"] is False
    assert payload["take_profit"]["limit_price"] == str(command.take_profit_limit_price)
    assert payload["stop_loss"]["stop_price"] == str(command.stop_loss_stop_price)


def test_paper_broker_submits_and_sends_credentials():
    request = execution_request()
    command = build_entry_command(request, now=request.requested_at)
    seen = {}

    def handler(req: httpx.Request):
        seen["path"] = req.url.path
        seen["key"] = req.headers["APCA-API-KEY-ID"]
        seen["payload"] = json.loads(req.content)
        return httpx.Response(200, json=_order_json(command))

    broker = AlpacaPaperBroker(
        api_key="paper-key",
        secret_key="paper-secret",
        transport=httpx.MockTransport(handler),
    )
    order = broker.submit_order(command)
    assert seen["path"] == "/v2/orders"
    assert seen["key"] == "paper-key"
    assert seen["payload"]["client_order_id"] == command.client_order_id
    assert order.client_order_id == command.client_order_id
    broker.close()


def test_live_endpoint_is_forbidden():
    with pytest.raises(ValueError, match="paper endpoint"):
        AlpacaPaperBroker(api_key="x", secret_key="y", base_url="https://api.alpaca.markets")


def test_http_errors_are_classified():
    broker = AlpacaPaperBroker(
        api_key="x",
        secret_key="y",
        transport=httpx.MockTransport(lambda req: httpx.Response(404, json={})),
    )
    with pytest.raises(BrokerNotFound):
        broker.get_order_by_client_order_id("missing")
    broker.close()
    broker = AlpacaPaperBroker(
        api_key="x",
        secret_key="y",
        transport=httpx.MockTransport(lambda req: httpx.Response(503, text="down")),
    )
    with pytest.raises(BrokerTransportError) as exc:
        broker.get_order_by_client_order_id("x")
    assert exc.value.transient is True
    broker.close()


def test_success_with_malformed_json_is_an_ambiguous_transport_failure():
    broker = AlpacaPaperBroker(
        api_key="x",
        secret_key="y",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text="not-json")),
    )
    with pytest.raises(BrokerTransportError) as exc:
        broker.get_order_by_client_order_id("ambiguous")
    assert exc.value.transient is True
    broker.close()


def test_list_positions_returns_every_open_position():
    rows = [
        {"symbol": "AAAA", "qty": "100", "avg_entry_price": "10.50"},
        {"symbol": "BBBB", "qty": "-50", "avg_entry_price": "20.00"},
    ]

    def handler(req: httpx.Request):
        assert req.url.path == "/v2/positions"
        return httpx.Response(200, json=rows)

    broker = AlpacaPaperBroker(api_key="x", secret_key="y", transport=httpx.MockTransport(handler))
    positions = broker.list_positions()
    assert [item.symbol for item in positions] == ["AAAA", "BBBB"]
    assert positions[1].quantity == 50  # magnitude only, matching get_position's abs()
    broker.close()


def test_list_positions_empty_body_is_empty_list():
    broker = AlpacaPaperBroker(
        api_key="x",
        secret_key="y",
        transport=httpx.MockTransport(lambda req: httpx.Response(204)),
    )
    assert broker.list_positions() == ()
    broker.close()


def test_list_positions_rejects_a_non_array_response():
    broker = AlpacaPaperBroker(
        api_key="x",
        secret_key="y",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"not": "a list"})),
    )
    with pytest.raises(BrokerTransportError):
        broker.list_positions()
    broker.close()


def test_list_orders_normalizes_every_row_and_passes_status_filter():
    command = build_entry_command(execution_request(), now=execution_request().requested_at)
    seen = {}

    def handler(req: httpx.Request):
        seen["query"] = dict(req.url.params)
        return httpx.Response(200, json=[_order_json(command)])

    broker = AlpacaPaperBroker(api_key="x", secret_key="y", transport=httpx.MockTransport(handler))
    orders = broker.list_orders(status="all")
    assert seen["query"]["status"] == "all"
    assert seen["query"]["nested"] == "true"
    assert len(orders) == 1
    assert orders[0].client_order_id == command.client_order_id
    broker.close()


def test_list_orders_invalid_row_raises_transient_transport_error():
    broker = AlpacaPaperBroker(
        api_key="x",
        secret_key="y",
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[{"id": "only-id"}])),
    )
    with pytest.raises(BrokerTransportError) as exc:
        broker.list_orders()
    assert exc.value.transient is True
    broker.close()
