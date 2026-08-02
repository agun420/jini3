# Phase 3 — Structured Outputs Evaluator

## Objective

Convert one immutable Phase 2 `FeatureSnapshot.payload` into a strictly validated Project Daybreak v6.3 evaluator result.

The evaluator is permitted to make only the semantic judgments assigned by the specification, principally catalyst magnitude, exact evidence span, and approved master thesis. Python independently checks every deterministic score, gate, risk flag, ranking result, terminal category, and payload echo.

## Primary path

`EvaluatorService.evaluate_primary()` is the only timed path.

It:

1. Rejects candidate counts above the configured hard maximum.
2. Loads the exact v6.3 specification from disk.
3. Canonically serializes the evaluator payload.
4. Calls the Responses API with strict `text.format` JSON Schema and no tools.
5. Enforces the response cutoff before and after the request.
6. Allows at most one retry and only after a transient transport failure.
7. Detects refusal and incomplete output explicitly.
8. Validates JSON and the strict `DaybreakOutput` Pydantic model.
9. Runs all 77 invariant functions and Python truth replay.
10. Persists the immutable attempt and result records.

The primary result never waits for a shadow model.

## Shadow path

`EvaluatorService.evaluate_shadow()` is a separate non-authorizing operation.

It may finish after the primary response cutoff because:

- it cannot authorize an order;
- it does not replace the primary result;
- it is used only for model disagreement analysis.

The comparison records:

- exact-output equality;
- run-status equality;
- approved-order equality;
- terminal routing by ticker;
- magnitude-bucket disagreement;
- conviction-score disagreement;
- evidence-span disagreement.

## Structured Outputs schema

`daybreak_evaluator.schema.daybreak_output_json_schema()` derives the provider schema from the strict Pydantic output contract and:

- removes non-enforcement metadata such as titles and defaults;
- sets `additionalProperties: false` on every object;
- requires every object property;
- retains nullable fields as explicit null unions;
- preserves exact enums, patterns, and numeric bounds.

The schema hash is stored with every attempt.

## Persistence

Migration `0003_phase3_evaluator` adds append-only tables:

- `evaluator_runs`
- `evaluator_attempts`
- `evaluator_results`
- `evaluator_shadow_comparisons`

No row is updated or deleted. Each attempt stores the full normalized attempt object plus separate searchable hashes and status fields.

## Retry rules

Retry once only for:

- provider transport failure;
- transient SDK/network error wrapped as `EvaluatorTransportError`.

Do not retry in the timed path for:

- response cutoff expiration;
- refusal;
- incomplete result;
- empty output;
- invalid JSON;
- Pydantic schema failure;
- Daybreak invariant failure.

Semantic failures are recorded and fail closed.

## Model defaults

- Primary: `gpt-5.6-terra`
- Shadow: `gpt-5.6-sol`
- Reasoning effort: `low`
- Maximum output tokens: 64,000

All are versioned configuration values. The provider-returned model ID and response ID are persisted for each attempt.

## Runtime boundary

The evaluator result does not imply that an order is eligible. Position sizing, account checks, market re-verification, execution cutoffs, duplicate-order prevention, and broker interaction remain absent from v0.3.0.
