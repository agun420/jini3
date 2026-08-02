from __future__ import annotations

import json
from typing import Any, Protocol

from .models import EvaluationAttempt, EvaluationRequest, EvaluationRunResult, ShadowComparison


class EvaluatorRepository(Protocol):
    def save_request(self, request: EvaluationRequest) -> None: ...
    def save_attempt(self, attempt: EvaluationAttempt) -> None: ...
    def save_comparison(self, run_id: str, comparison: ShadowComparison) -> None: ...
    def save_result(self, result: EvaluationRunResult) -> None: ...
    def get_result(self, run_id: str) -> EvaluationRunResult | None: ...


class NullEvaluatorRepository:
    def save_request(self, request: EvaluationRequest) -> None:
        return None

    def save_attempt(self, attempt: EvaluationAttempt) -> None:
        return None

    def save_comparison(self, run_id: str, comparison: ShadowComparison) -> None:
        return None

    def save_result(self, result: EvaluationRunResult) -> None:
        return None

    def get_result(self, run_id: str) -> EvaluationRunResult | None:
        return None


class MemoryEvaluatorRepository:
    def __init__(self) -> None:
        self.requests: dict[str, EvaluationRequest] = {}
        self.attempts: dict[str, EvaluationAttempt] = {}
        self.comparisons: dict[str, ShadowComparison] = {}
        self.results: dict[str, EvaluationRunResult] = {}

    def save_request(self, request: EvaluationRequest) -> None:
        existing = self.requests.get(request.run_id)
        if existing is not None and existing != request:
            raise RuntimeError("evaluator request identity collision")
        self.requests.setdefault(request.run_id, request)

    def save_attempt(self, attempt: EvaluationAttempt) -> None:
        existing = self.attempts.get(attempt.attempt_id)
        if existing is not None and existing != attempt:
            raise RuntimeError("evaluator attempt identity collision")
        self.attempts.setdefault(attempt.attempt_id, attempt)

    def save_comparison(self, run_id: str, comparison: ShadowComparison) -> None:
        existing = self.comparisons.get(run_id)
        if existing is not None and existing != comparison:
            raise RuntimeError("evaluator comparison identity collision")
        self.comparisons.setdefault(run_id, comparison)

    def save_result(self, result: EvaluationRunResult) -> None:
        existing = self.results.get(result.run_id)
        if existing is not None and existing != result:
            raise RuntimeError("evaluator result identity collision")
        self.results.setdefault(result.run_id, result)

    def get_result(self, run_id: str) -> EvaluationRunResult | None:
        return self.results.get(run_id)


class PostgresEvaluatorRepository:
    """Synchronous append-only repository; psycopg is imported lazily."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://")

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Install project-daybreak[recorder] for PostgreSQL support") from exc
        return psycopg.connect(self._dsn)

    def save_request(self, request: EvaluationRequest) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evaluator_runs (
                    run_id, requested_at, response_cutoff_timestamp, payload_hash,
                    configuration_hash, request_json
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (
                    request.run_id,
                    request.requested_at,
                    request.response_cutoff_timestamp,
                    request.evidence.payload_hash,
                    request.evidence.configuration_hash,
                    json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def save_attempt(self, attempt: EvaluationAttempt) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evaluator_attempts (
                    attempt_id, run_id, role, attempt_number, model, status,
                    request_started_at, response_received_at, response_id,
                    request_hash, prompt_hash, spec_hash, schema_hash, response_text_hash,
                    raw_response_hash, attempt_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (attempt_id) DO NOTHING
                """,
                (
                    attempt.attempt_id,
                    attempt.run_id,
                    attempt.role.value,
                    attempt.attempt_number,
                    attempt.model,
                    attempt.status.value,
                    attempt.request_started_at,
                    attempt.response_received_at,
                    attempt.response_id,
                    attempt.request_hash,
                    attempt.prompt_hash,
                    attempt.spec_hash,
                    attempt.schema_hash,
                    attempt.response_text_hash,
                    attempt.raw_response_hash,
                    json.dumps(attempt.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def save_comparison(self, run_id: str, comparison: ShadowComparison) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evaluator_shadow_comparisons (
                    run_id, primary_attempt_id, shadow_attempt_id,
                    exact_output_match, comparison_json
                ) VALUES (%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (
                    run_id,
                    comparison.primary_attempt_id,
                    comparison.shadow_attempt_id,
                    comparison.exact_output_match,
                    json.dumps(comparison.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def save_result(self, result: EvaluationRunResult) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evaluator_results (
                    result_id, run_id, status, selected_primary_attempt_id,
                    decision_ready_at, late_response_rejected, result_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (run_id) DO NOTHING
                """,
                (
                    f"result-{result.run_id}",
                    result.run_id,
                    result.status.value,
                    result.selected_primary_attempt_id,
                    result.decision_ready_at,
                    result.late_response_rejected,
                    json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def get_result(self, run_id: str) -> EvaluationRunResult | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT result_json FROM evaluator_results WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
        return None if row is None else EvaluationRunResult.model_validate(row[0])
