from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from .errors import EvaluatorTransportError
from .models import ProviderResult, TokenUsage
from .schema import structured_output_format


class StructuredOutputTransport(Protocol):
    async def create(
        self,
        *,
        model: str,
        directive: str,
        payload_text: str,
        schema_name: str,
        reasoning_effort: str,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> ProviderResult: ...


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    if hasattr(value, "model_dump"):
        return cast(dict[str, Any], value.model_dump(mode="json"))
    if hasattr(value, "to_dict"):
        return cast(dict[str, Any], value.to_dict())
    return {"repr": repr(value)}


def _extract_usage(response: Any) -> TokenUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cached = int(getattr(input_details, "cached_tokens", 0) or 0)
    reasoning = int(getattr(output_details, "reasoning_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
    return TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning,
        total_tokens=total,
    )


def _extract_refusal(response: Any) -> str | None:
    for item in getattr(response, "output", ()) or ():
        for content in getattr(item, "content", ()) or ():
            if getattr(content, "type", None) == "refusal":
                return str(getattr(content, "refusal", "Model refusal"))
    return None


class OpenAIResponsesTransport:
    """Thin Responses API adapter. OpenAI is imported lazily for optional installation."""

    def __init__(self, *, api_key: str | None = None, client: Any | None = None) -> None:
        if client is not None:
            self._client = client
            return
        try:
            from openai import AsyncOpenAI
        except (ImportError, AttributeError) as exc:
            raise EvaluatorTransportError(
                "OpenAI SDK is not installed. Install project-daybreak[evaluator]."
            ) from exc
        self._client = AsyncOpenAI(api_key=api_key)

    async def create(
        self,
        *,
        model: str,
        directive: str,
        payload_text: str,
        schema_name: str,
        reasoning_effort: str,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> ProviderResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": directive,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": payload_text,
                        }
                    ],
                }
            ],
            "text": {"format": structured_output_format(schema_name)},
            "max_output_tokens": max_output_tokens,
            "store": False,
        }
        if reasoning_effort != "none":
            kwargs["reasoning"] = {"effort": reasoning_effort}

        try:
            async with asyncio.timeout(timeout_seconds):
                response = await self._client.responses.create(**kwargs)
        except TimeoutError:
            raise
        except Exception as exc:  # Provider SDK exceptions are optional at import time.
            raise EvaluatorTransportError(f"OpenAI Responses request failed: {exc}") from exc

        completed = datetime.now(UTC)
        status = str(getattr(response, "status", "completed"))
        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = None
        if status != "completed":
            incomplete_reason = str(getattr(incomplete_details, "reason", status) or status)
        return ProviderResult(
            response_id=getattr(response, "id", None),
            model=str(getattr(response, "model", model)),
            created_at=None,
            completed_at=completed,
            output_text=getattr(response, "output_text", None),
            refusal=_extract_refusal(response),
            incomplete_reason=incomplete_reason,
            usage=_extract_usage(response),
            raw_response=_as_dict(response),
        )
