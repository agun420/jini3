from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from daybreak.core.hashing import canonical_sha256
from daybreak_contracts.output_models import DaybreakOutput
from daybreak_contracts.validation.models import ValidationMetadata, ValidationReport
from daybreak_contracts.validation.runner import validate_daybreak_run

from .comparison import compare_outputs
from .errors import EvaluatorTransportError
from .models import (
    AttemptRole,
    AttemptStatus,
    EvaluationAttempt,
    EvaluationRequest,
    EvaluationRunResult,
    EvaluatorPolicy,
    ProviderResult,
    RunStatus,
    ShadowEvaluationResult,
    TokenUsage,
)
from .persistence import EvaluatorRepository, NullEvaluatorRepository
from .prompt import PromptBundle, build_prompt
from .schema import schema_sha256
from .transport import StructuredOutputTransport

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid4().hex


def _hash_text(text: str | None) -> str | None:
    if text is None:
        return None
    return canonical_sha256(text)


def _hash_json(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    return canonical_sha256(value)


class EvaluatorService:
    def __init__(
        self,
        *,
        transport: StructuredOutputTransport,
        spec_path: str,
        policy: EvaluatorPolicy | None = None,
        repository: EvaluatorRepository | None = None,
        clock: Clock = _utcnow,
        id_factory: IdFactory = _new_id,
    ) -> None:
        self._transport = transport
        self._spec_path = spec_path
        self._policy = policy or EvaluatorPolicy()
        self._repository = repository or NullEvaluatorRepository()
        self._clock = clock
        self._id_factory = id_factory

    def _metadata(
        self,
        request: EvaluationRequest,
        *,
        response_received_at: datetime,
    ) -> ValidationMetadata:
        evidence = request.evidence
        return ValidationMetadata(
            evaluator_candidate_count=len(request.input_payload.tickers),
            max_evaluator_candidates_hard=self._policy.max_evaluator_candidates_hard,
            prequalified_out_tickers=evidence.prequalified_out_tickers,
            capacity_omitted_tickers=evidence.capacity_omitted_tickers,
            capacity_omissions_logged=evidence.capacity_omissions_logged,
            preselection_policy_version=evidence.preselection_policy_version,
            evaluator_response_timestamp=response_received_at,
            execution_cutoff_timestamp=request.response_cutoff_timestamp,
            order_authorized=False,
            # The service verifies complete terminal diagnostics and then replays all
            # deterministic score/gate fields. This is the external proof available
            # to the orchestrator; semantic classification order remains model-owned.
            scoring_completed_before_gates=True,
            duplicate_detection_after_ticker_validation=True,
            duplicate_detection_valid_only=True,
            operational_blockers_after_schema_validation=True,
        )

    def _request_hash(
        self,
        request: EvaluationRequest,
        prompt: PromptBundle,
        *,
        model: str,
        role: AttemptRole,
    ) -> str:
        return canonical_sha256(
            {
                "run_id": request.run_id,
                "payload": request.input_payload.model_dump(mode="json"),
                "evidence": request.evidence.model_dump(mode="json"),
                "response_cutoff_timestamp": request.response_cutoff_timestamp.isoformat(),
                "model": model,
                "role": role.value,
                "policy": self._policy.model_dump(mode="json"),
                "prompt_hash": prompt.prompt_hash,
            }
        )

    def _attempt(
        self,
        *,
        request: EvaluationRequest,
        prompt: PromptBundle,
        role: AttemptRole,
        model: str,
        attempt_number: int,
        started_at: datetime,
        status: AttemptStatus,
        provider: ProviderResult | None = None,
        output: DaybreakOutput | None = None,
        report: ValidationReport | None = None,
        error: Exception | None = None,
    ) -> EvaluationAttempt:
        raw = (
            provider.raw_response if provider and self._policy.store_raw_provider_response else None
        )
        return EvaluationAttempt(
            attempt_id=self._id_factory(),
            run_id=request.run_id,
            role=role,
            attempt_number=attempt_number,
            model=model,
            request_started_at=started_at,
            response_received_at=provider.completed_at if provider else self._clock(),
            status=status,
            request_hash=self._request_hash(request, prompt, model=model, role=role),
            prompt_hash=prompt.prompt_hash,
            spec_hash=prompt.spec_hash,
            schema_hash=schema_sha256(),
            response_id=provider.response_id if provider else None,
            raw_output_text=provider.output_text if provider else None,
            raw_provider_response=raw,
            response_text_hash=_hash_text(provider.output_text if provider else None),
            raw_response_hash=_hash_json(raw),
            output=output,
            validation_report=report,
            usage=provider.usage if provider else TokenUsage(),
            error_type=type(error).__name__ if error else None,
            error_message=str(error) if error else None,
        )

    async def _call_once(
        self,
        *,
        request: EvaluationRequest,
        prompt: PromptBundle,
        role: AttemptRole,
        model: str,
        attempt_number: int,
    ) -> EvaluationAttempt:
        started = self._clock()
        if role == AttemptRole.PRIMARY:
            remaining = (request.response_cutoff_timestamp - started).total_seconds()
            if remaining <= 0:
                attempt = self._attempt(
                    request=request,
                    prompt=prompt,
                    role=role,
                    model=model,
                    attempt_number=attempt_number,
                    started_at=started,
                    status=AttemptStatus.DEADLINE_EXCEEDED,
                    error=TimeoutError("evaluator response cutoff already passed"),
                )
                self._repository.save_attempt(attempt)
                return attempt
            timeout_seconds = min(remaining, self._policy.request_timeout_seconds)
        else:
            timeout_seconds = self._policy.shadow_timeout_seconds
        try:
            provider = await self._transport.create(
                model=model,
                directive=prompt.directive,
                payload_text=prompt.payload_text,
                schema_name=self._policy.schema_name,
                reasoning_effort=self._policy.reasoning_effort,
                max_output_tokens=self._policy.max_output_tokens,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError as exc:
            attempt = self._attempt(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=attempt_number,
                started_at=started,
                status=AttemptStatus.DEADLINE_EXCEEDED,
                error=exc,
            )
            self._repository.save_attempt(attempt)
            return attempt
        except (EvaluatorTransportError, OSError) as exc:
            attempt = self._attempt(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=attempt_number,
                started_at=started,
                status=AttemptStatus.TRANSPORT_ERROR,
                error=exc,
            )
            self._repository.save_attempt(attempt)
            return attempt

        if (
            role == AttemptRole.PRIMARY
            and provider.completed_at > request.response_cutoff_timestamp
        ):
            attempt = self._attempt(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=attempt_number,
                started_at=started,
                status=AttemptStatus.DEADLINE_EXCEEDED,
                provider=provider,
                error=TimeoutError("provider response arrived after cutoff"),
            )
            self._repository.save_attempt(attempt)
            return attempt
        if provider.refusal:
            attempt = self._attempt(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=attempt_number,
                started_at=started,
                status=AttemptStatus.REFUSED,
                provider=provider,
                error=ValueError(provider.refusal),
            )
            self._repository.save_attempt(attempt)
            return attempt
        if provider.incomplete_reason:
            attempt = self._attempt(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=attempt_number,
                started_at=started,
                status=AttemptStatus.INCOMPLETE,
                provider=provider,
                error=ValueError(provider.incomplete_reason),
            )
            self._repository.save_attempt(attempt)
            return attempt
        if not provider.output_text:
            attempt = self._attempt(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=attempt_number,
                started_at=started,
                status=AttemptStatus.EMPTY_OUTPUT,
                provider=provider,
                error=ValueError("provider returned empty output_text"),
            )
            self._repository.save_attempt(attempt)
            return attempt

        try:
            json.loads(provider.output_text)
        except json.JSONDecodeError as exc:
            attempt = self._attempt(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=attempt_number,
                started_at=started,
                status=AttemptStatus.INVALID_JSON,
                provider=provider,
                error=exc,
            )
            self._repository.save_attempt(attempt)
            return attempt
        try:
            output = DaybreakOutput.model_validate_json(provider.output_text)
        except ValidationError as exc:
            attempt = self._attempt(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=attempt_number,
                started_at=started,
                status=AttemptStatus.SCHEMA_INVALID,
                provider=provider,
                error=exc,
            )
            self._repository.save_attempt(attempt)
            return attempt

        report = validate_daybreak_run(
            request.input_payload,
            output,
            metadata=self._metadata(request, response_received_at=provider.completed_at),
        )
        if not report.valid:
            attempt = self._attempt(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=attempt_number,
                started_at=started,
                status=AttemptStatus.INVARIANT_INVALID,
                provider=provider,
                output=output,
                report=report,
                error=ValueError("Daybreak invariant validation failed"),
            )
            self._repository.save_attempt(attempt)
            return attempt

        attempt = self._attempt(
            request=request,
            prompt=prompt,
            role=role,
            model=model,
            attempt_number=attempt_number,
            started_at=started,
            status=AttemptStatus.SUCCEEDED,
            provider=provider,
            output=output,
            report=report,
        )
        self._repository.save_attempt(attempt)
        return attempt

    async def _evaluate_role(
        self,
        *,
        request: EvaluationRequest,
        prompt: PromptBundle,
        role: AttemptRole,
        model: str,
    ) -> tuple[EvaluationAttempt, ...]:
        attempts: list[EvaluationAttempt] = []
        for number in range(1, self._policy.max_attempts + 1):
            attempt = await self._call_once(
                request=request,
                prompt=prompt,
                role=role,
                model=model,
                attempt_number=number,
            )
            attempts.append(attempt)
            if attempt.status == AttemptStatus.SUCCEEDED:
                break
            # Only retry transient transport failures. Semantic or timing failures fail closed.
            if attempt.status != AttemptStatus.TRANSPORT_ERROR:
                break
            if role == AttemptRole.PRIMARY and self._clock() >= request.response_cutoff_timestamp:
                break
            await asyncio.sleep(0)
        return tuple(attempts)

    async def evaluate_primary(self, request: EvaluationRequest) -> EvaluationRunResult:
        """Run only the primary evaluator path; never wait for a shadow model."""
        self._repository.save_request(request)
        if len(request.input_payload.tickers) > self._policy.max_evaluator_candidates_hard:
            result = EvaluationRunResult(
                run_id=request.run_id,
                status=RunStatus.INPUT_REJECTED,
                request=request,
                primary_attempts=(),
            )
            self._repository.save_result(result)
            return result

        prompt = build_prompt(self._spec_path, request.input_payload)
        primary_attempts = await self._evaluate_role(
            request=request,
            prompt=prompt,
            role=AttemptRole.PRIMARY,
            model=self._policy.primary_model,
        )
        primary = next(
            (a for a in reversed(primary_attempts) if a.status == AttemptStatus.SUCCEEDED),
            None,
        )
        late = any(a.status == AttemptStatus.DEADLINE_EXCEEDED for a in primary_attempts)
        if primary is None:
            status = RunStatus.CUTOFF_MISSED if late else RunStatus.PRIMARY_INVALID
            result = EvaluationRunResult(
                run_id=request.run_id,
                status=status,
                request=request,
                primary_attempts=primary_attempts,
                late_response_rejected=late,
            )
            self._repository.save_result(result)
            return result

        result = EvaluationRunResult(
            run_id=request.run_id,
            status=RunStatus.PRIMARY_VALID,
            request=request,
            primary_attempts=primary_attempts,
            selected_primary_attempt_id=primary.attempt_id,
            output=primary.output,
            decision_ready_at=primary.response_received_at,
            late_response_rejected=False,
        )
        self._repository.save_result(result)
        return result

    async def evaluate_shadow(
        self,
        request: EvaluationRequest,
        primary_result: EvaluationRunResult,
    ) -> ShadowEvaluationResult:
        """Run shadow analysis independently; it cannot authorize or delay the primary path."""
        self._repository.save_request(request)
        if not self._policy.shadow_model or primary_result.output is None:
            return ShadowEvaluationResult(run_id=request.run_id, attempts=())
        prompt = build_prompt(self._spec_path, request.input_payload)
        attempts = await self._evaluate_role(
            request=request,
            prompt=prompt,
            role=AttemptRole.SHADOW,
            model=self._policy.shadow_model,
        )
        shadow = next(
            (a for a in reversed(attempts) if a.status == AttemptStatus.SUCCEEDED),
            None,
        )
        comparison = None
        if shadow and shadow.output:
            primary_attempt_id = primary_result.selected_primary_attempt_id
            if primary_attempt_id is not None:
                comparison = compare_outputs(
                    primary_attempt_id=primary_attempt_id,
                    shadow_attempt_id=shadow.attempt_id,
                    primary=primary_result.output,
                    shadow=shadow.output,
                )
                self._repository.save_comparison(request.run_id, comparison)
        return ShadowEvaluationResult(
            run_id=request.run_id, attempts=attempts, comparison=comparison
        )

    def spawn_shadow(
        self,
        request: EvaluationRequest,
        primary_result: EvaluationRunResult,
    ) -> asyncio.Task[ShadowEvaluationResult]:
        """Schedule non-authorizing shadow analysis on the caller's running event loop."""
        return asyncio.create_task(self.evaluate_shadow(request, primary_result))

    async def evaluate_with_shadow(self, request: EvaluationRequest) -> EvaluationRunResult:
        """Research helper that awaits shadow output; never use on the timed authorization path."""
        primary = await self.evaluate_primary(request)
        shadow = await self.evaluate_shadow(request, primary)
        return primary.model_copy(
            update={
                "shadow_attempts": shadow.attempts,
                "comparison": shadow.comparison,
            }
        )

    async def evaluate(
        self,
        request: EvaluationRequest,
        *,
        run_shadow: bool = False,
    ) -> EvaluationRunResult:
        """Compatibility entry point; shadow waiting is explicit and off by default."""
        if run_shadow:
            return await self.evaluate_with_shadow(request)
        return await self.evaluate_primary(request)
