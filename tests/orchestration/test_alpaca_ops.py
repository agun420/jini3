import httpx

from daybreak_orchestration.alpaca_ops import AlpacaPaperOperations


def mock_transport(request: httpx.Request) -> httpx.Response:
    headers = {"X-Request-ID": "request-1"}
    if request.url.path == "/v2/account":
        return httpx.Response(
            200,
            headers=headers,
            json={"status": "ACTIVE", "account_blocked": False, "trading_blocked": False},
        )
    if request.url.path == "/v2/clock":
        return httpx.Response(
            200,
            headers=headers,
            json={
                "timestamp": "2026-08-03T13:30:00Z",
                "is_open": True,
                "next_open": "2026-08-04T13:30:00Z",
                "next_close": "2026-08-03T20:00:00Z",
            },
        )
    if request.url.path == "/v2/orders" and request.method == "GET":
        status = request.url.params.get("status")
        orders = [
            {
                "id": "db-order",
                "client_order_id": "DB-20260803-abc-AAPL",
                "symbol": "AAPL",
                "status": "filled",
                "side": "buy",
                "filled_qty": "5",
                "legs": [],
            },
            {
                "id": "manual-order",
                "client_order_id": "manual-order",
                "symbol": "MSFT",
                "status": "new",
            },
        ]
        return httpx.Response(
            200, headers=headers, json=orders if status in {"open", "all"} else []
        )
    if request.url.path == "/v2/orders/db-order" and request.method == "DELETE":
        return httpx.Response(204, headers=headers)
    if request.url.path == "/v2/positions/AAPL" and request.method == "GET":
        return httpx.Response(
            200, headers=headers, json={"symbol": "AAPL", "qty": "5", "avg_entry_price": "100"}
        )
    if request.url.path == "/v2/positions/AAPL" and request.method == "DELETE":
        return httpx.Response(
            200,
            headers=headers,
            json={
                "id": "close-1",
                "client_order_id": "flatten-aapl",
                "submitted_at": "2026-08-03T19:50:00Z",
            },
        )
    return httpx.Response(404)


def test_account_clock_and_flatten_operations():
    ops = AlpacaPaperOperations(
        api_key="key", secret_key="secret", transport=httpx.MockTransport(mock_transport)
    )
    assert ops.account_probe()[0] is True
    assert ops.clock_probe()[0] is True
    from datetime import date

    from daybreak_orchestration.clock import build_session_plan
    from tests.orchestration.helpers import CONFIG_HASH

    plan = build_session_plan(
        trading_date=date(2026, 8, 3), run_id="run", configuration_hash=CONFIG_HASH
    )
    targets = ops.discover_daybreak_targets(plan)
    assert targets[0].symbol == "AAPL"
    assert targets[0].quantity == 5
    assert ops.cancel_daybreak_orders(plan) == 1
    positions = ops.list_positions(targets)
    assert positions[0].symbol == "AAPL"
    close = ops.close_position(positions[0])
    assert close.broker_order_id == "close-1"
    ops.close()


def test_live_endpoint_is_rejected():
    try:
        AlpacaPaperOperations(
            api_key="key", secret_key="secret", base_url="https://api.alpaca.markets"
        )
    except ValueError as exc:
        assert "paper endpoint" in str(exc)
    else:
        raise AssertionError("live endpoint should be rejected")


def test_bracket_children_are_deduplicated_and_canceled_with_parent_ownership():
    deleted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        root = {
            "id": "root-1",
            "client_order_id": "DB-20260803-abc-AAPL",
            "symbol": "AAPL",
            "side": "buy",
            "filled_qty": "5",
            "legs": [
                {
                    "id": "stop-1",
                    "symbol": "AAPL",
                    "side": "sell",
                    "filled_qty": "1",
                }
            ],
        }
        child = {
            "id": "stop-1",
            "parent_order_id": "root-1",
            "client_order_id": "broker-generated-child",
            "symbol": "AAPL",
            "side": "sell",
            "filled_qty": "1",
        }
        if request.url.path == "/v2/orders" and request.method == "GET":
            status = request.url.params.get("status")
            return httpx.Response(200, json=[root, child] if status == "all" else [child])
        if request.method == "DELETE" and request.url.path == "/v2/orders/stop-1":
            deleted.append("stop-1")
            return httpx.Response(204)
        return httpx.Response(404)

    from datetime import date

    from daybreak_orchestration.clock import build_session_plan
    from tests.orchestration.helpers import CONFIG_HASH

    plan = build_session_plan(
        trading_date=date(2026, 8, 3),
        run_id="run",
        configuration_hash=CONFIG_HASH,
    )
    ops = AlpacaPaperOperations(
        api_key="key",
        secret_key="secret",
        transport=httpx.MockTransport(handler),
    )

    targets = ops.discover_daybreak_targets(plan)
    canceled = ops.cancel_daybreak_orders(plan)

    assert targets[0].quantity == 4
    assert canceled == 1
    assert deleted == ["stop-1"]
    ops.close()
