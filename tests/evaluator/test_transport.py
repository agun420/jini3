from __future__ import annotations

from types import SimpleNamespace

import pytest

from daybreak_evaluator.transport import OpenAIResponsesTransport


class FakeResponses:
    def __init__(self) -> None:
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="resp-1",
            model=kwargs["model"],
            status="completed",
            incomplete_details=None,
            output_text='{"run_status":"no_setups"}',
            output=[],
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                input_tokens_details=SimpleNamespace(cached_tokens=2),
                output_tokens_details=SimpleNamespace(reasoning_tokens=1),
            ),
            model_dump=lambda mode="json": {"id": "resp-1"},
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


@pytest.mark.asyncio
async def test_responses_transport_uses_strict_text_format_and_no_tools() -> None:
    client = FakeClient()
    transport = OpenAIResponsesTransport(client=client)
    result = await transport.create(
        model="gpt-5.6-terra",
        directive="directive",
        payload_text="{}",
        schema_name="daybreak",
        reasoning_effort="low",
        max_output_tokens=64000,
        timeout_seconds=2,
    )
    kwargs = client.responses.kwargs
    assert kwargs["text"]["format"]["type"] == "json_schema"
    assert kwargs["text"]["format"]["strict"] is True
    assert "tools" not in kwargs
    assert kwargs["store"] is False
    assert kwargs["reasoning"] == {"effort": "low"}
    assert result.usage.cached_input_tokens == 2
    assert result.usage.reasoning_tokens == 1
