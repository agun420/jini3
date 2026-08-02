from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from daybreak.core.hashing import canonical_sha256
from daybreak_contracts.input_models import DaybreakInput
from daybreak_evaluator.errors import EvaluatorTransportError
from daybreak_evaluator.models import (
    AttemptStatus,
    EvaluationEvidence,
    EvaluationRequest,
    EvaluatorPolicy,
    ProviderResult,
    RunStatus,
    TokenUsage,
)
from daybreak_evaluator.persistence import MemoryEvaluatorRepository
from daybreak_evaluator.service import EvaluatorService

ROOT = Path(__file__).resolve().parents[2]
UTC = UTC


class QueueTransport:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def fixture_text(name: str) -> str:
    return (ROOT / f"tests/fixtures/{name}").read_text(encoding="utf-8")


def make_request(now: datetime | None = None) -> EvaluationRequest:
    now = now or datetime.now(UTC)
    payload = DaybreakInput.model_validate_json(fixture_text("approved_input.json"))
    payload_hash = canonical_sha256(payload.model_dump(mode="json"))
    return EvaluationRequest(
        run_id="run-001",
        input_payload=payload,
        evidence=EvaluationEvidence(
            payload_hash=payload_hash,
            configuration_hash="a" * 64,
            capacity_omitted_tickers=frozenset({"ZZZZ"}),
            capacity_omissions_logged=frozenset({"ZZZZ"}),
            preselection_policy_version="prequal_rank_v1",
        ),
        requested_at=now,
        response_cutoff_timestamp=now + timedelta(seconds=30),
    )


def test_request_rejects_payload_hash_substitution() -> None:
    request = make_request()
    with pytest.raises(ValueError, match="payload_hash"):
        EvaluationRequest(
            run_id=request.run_id,
            input_payload=request.input_payload,
            evidence=request.evidence.model_copy(update={"payload_hash": "f" * 64}),
            requested_at=request.requested_at,
            response_cutoff_timestamp=request.response_cutoff_timestamp,
        )


def test_provider_rejects_naive_completion_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ProviderResult(model="gpt-5.6-terra", completed_at=datetime(2026, 8, 1))


def provider(output_name: str, completed_at: datetime, *, model: str) -> ProviderResult:
    return ProviderResult(
        response_id=f"resp-{model}",
        model=model,
        completed_at=completed_at,
        output_text=fixture_text(output_name),
        usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
        raw_response={"id": f"resp-{model}", "model": model},
    )


@pytest.mark.asyncio
async def test_primary_and_shadow_valid() -> None:
    request = make_request()
    transport = QueueTransport(
        [
            provider(
                "approved_output.json",
                request.requested_at + timedelta(seconds=2),
                model="gpt-5.6-sol",
            ),
            provider(
                "approved_output.json",
                request.requested_at + timedelta(seconds=1),
                model="gpt-5.6-terra",
            ),
        ]
    )
    repo = MemoryEvaluatorRepository()
    counter = iter([f"id-{n}" for n in range(10)])
    service = EvaluatorService(
        transport=transport,
        spec_path=str(ROOT / "docs/spec/Project_Daybreak_v6.3_Final.md"),
        repository=repo,
        id_factory=lambda: next(counter),
    )
    result = await service.evaluate_with_shadow(request)
    assert result.status == RunStatus.PRIMARY_VALID
    assert result.output is not None
    assert result.comparison is not None
    assert result.comparison.exact_output_match is True
    assert result.executable_candidate_output is not None
    assert len(repo.attempts) == 2


@pytest.mark.asyncio
async def test_transient_transport_failure_retries_once() -> None:
    request = make_request()
    transport = QueueTransport(
        [
            EvaluatorTransportError("temporary"),
            provider(
                "approved_output.json",
                request.requested_at + timedelta(seconds=2),
                model="gpt-5.6-terra",
            ),
        ]
    )
    service = EvaluatorService(
        transport=transport,
        spec_path=str(ROOT / "docs/spec/Project_Daybreak_v6.3_Final.md"),
        policy=EvaluatorPolicy(shadow_model=None),
    )
    result = await service.evaluate(request, run_shadow=False)
    assert result.status == RunStatus.PRIMARY_VALID
    assert [x.status for x in result.primary_attempts] == [
        AttemptStatus.TRANSPORT_ERROR,
        AttemptStatus.SUCCEEDED,
    ]


@pytest.mark.asyncio
async def test_invariant_failure_is_not_retried() -> None:
    request = make_request()
    transport = QueueTransport(
        [
            provider(
                "no_setups_output.json",
                request.requested_at + timedelta(seconds=1),
                model="gpt-5.6-terra",
            ),
        ]
    )
    service = EvaluatorService(
        transport=transport,
        spec_path=str(ROOT / "docs/spec/Project_Daybreak_v6.3_Final.md"),
        policy=EvaluatorPolicy(shadow_model=None),
    )
    result = await service.evaluate(request, run_shadow=False)
    assert result.status == RunStatus.PRIMARY_INVALID
    assert len(result.primary_attempts) == 1
    assert result.primary_attempts[0].status == AttemptStatus.INVARIANT_INVALID
    assert result.output is None


@pytest.mark.asyncio
async def test_late_response_is_rejected() -> None:
    request = make_request()
    transport = QueueTransport(
        [
            provider(
                "approved_output.json",
                request.response_cutoff_timestamp + timedelta(milliseconds=1),
                model="gpt-5.6-terra",
            ),
        ]
    )
    service = EvaluatorService(
        transport=transport,
        spec_path=str(ROOT / "docs/spec/Project_Daybreak_v6.3_Final.md"),
        policy=EvaluatorPolicy(shadow_model=None),
    )
    result = await service.evaluate(request, run_shadow=False)
    assert result.status == RunStatus.CUTOFF_MISSED
    assert result.late_response_rejected is True
    assert result.executable_candidate_output is None


@pytest.mark.asyncio
async def test_refusal_fails_closed_without_retry() -> None:
    request = make_request()
    transport = QueueTransport(
        [
            ProviderResult(
                model="gpt-5.6-terra",
                completed_at=request.requested_at + timedelta(seconds=1),
                refusal="refused",
            )
        ]
    )
    service = EvaluatorService(
        transport=transport,
        spec_path=str(ROOT / "docs/spec/Project_Daybreak_v6.3_Final.md"),
        policy=EvaluatorPolicy(shadow_model=None),
    )
    result = await service.evaluate(request, run_shadow=False)
    assert result.status == RunStatus.PRIMARY_INVALID
    assert result.primary_attempts[0].status == AttemptStatus.REFUSED
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_candidate_hard_max_rejects_before_provider() -> None:
    request = make_request()
    service = EvaluatorService(
        transport=QueueTransport([]),
        spec_path=str(ROOT / "docs/spec/Project_Daybreak_v6.3_Final.md"),
        policy=EvaluatorPolicy(max_evaluator_candidates_hard=1, shadow_model=None),
    )
    result = await service.evaluate(request, run_shadow=False)
    assert result.status == RunStatus.INPUT_REJECTED
    assert result.primary_attempts == ()


@pytest.mark.asyncio
async def test_shadow_can_finish_after_primary_cutoff_without_affecting_primary() -> None:
    request = make_request()
    transport = QueueTransport(
        [
            provider(
                "approved_output.json",
                request.requested_at + timedelta(seconds=1),
                model="gpt-5.6-terra",
            ),
            provider(
                "approved_output.json",
                request.response_cutoff_timestamp + timedelta(seconds=20),
                model="gpt-5.6-sol",
            ),
        ]
    )
    service = EvaluatorService(
        transport=transport,
        spec_path=str(ROOT / "docs/spec/Project_Daybreak_v6.3_Final.md"),
    )
    primary = await service.evaluate_primary(request)
    assert primary.status == RunStatus.PRIMARY_VALID
    assert len(transport.calls) == 1
    shadow = await service.evaluate_shadow(request, primary)
    assert shadow.attempts[-1].status == AttemptStatus.SUCCEEDED
    assert shadow.comparison is not None
