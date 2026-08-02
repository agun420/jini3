from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..input_models import DaybreakInput
from ..output_models import DaybreakOutput
from .invariants import INVARIANT_REGISTRY
from .models import (
    CheckStatus,
    ValidationContext,
    ValidationMetadata,
    ValidationReport,
)

# These need live orchestration evidence before an evaluator response can authorize an order.
EXECUTION_EVIDENCE_INVARIANTS = frozenset({15, 41, 44, 62, 66})


ModelT = TypeVar("ModelT", bound=BaseModel)


def _parse_model(model_type: type[ModelT], value: Any) -> ModelT:  # noqa: UP047
    if isinstance(value, model_type):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        return model_type.model_validate_json(value)
    return model_type.model_validate_json(json.dumps(value, ensure_ascii=False, allow_nan=False))


def validate_daybreak_run(
    input_payload: DaybreakInput | dict[str, Any] | str | bytes | None,
    output: DaybreakOutput | dict[str, Any] | str | bytes,
    *,
    metadata: ValidationMetadata | dict[str, Any] | None = None,
    require_execution_evidence: bool = False,
) -> ValidationReport:
    """
    Validate the strict output contract and run all 77 registered checks.

    Invalid evaluator inputs may be supplied as raw dictionaries when validating a
    schema_failure response. In that case input-dependent checks are explicitly
    reported as not_evaluated rather than silently passing.
    """

    model_errors: list[str] = []
    raw_input = input_payload if isinstance(input_payload, dict) else None
    raw_output = output if isinstance(output, dict) else None

    parsed_input: DaybreakInput | None = None
    input_error: str | None = None
    if input_payload is not None:
        try:
            parsed_input = _parse_model(DaybreakInput, input_payload)
        except (ValidationError, ValueError, TypeError) as exc:
            input_error = f"input: {exc}"

    try:
        parsed_output = _parse_model(DaybreakOutput, output)
    except (ValidationError, ValueError, TypeError) as exc:
        model_errors.append(f"output: {exc}")
        return ValidationReport(
            valid=False,
            execution_ready=False,
            model_errors=tuple(model_errors),
            checks=(),
        )

    if input_error is not None and parsed_output.run_status != "schema_failure":
        model_errors.append(input_error)

    if metadata is None:
        parsed_metadata = ValidationMetadata()
    elif isinstance(metadata, ValidationMetadata):
        parsed_metadata = metadata
    else:
        parsed_metadata = ValidationMetadata.model_validate(metadata)

    ctx = ValidationContext(
        input_payload=parsed_input,
        output=parsed_output,
        raw_input=raw_input,
        raw_output=raw_output,
        metadata=parsed_metadata,
    )
    checks = tuple(INVARIANT_REGISTRY[number](ctx) for number in INVARIANT_REGISTRY)
    failures = [check for check in checks if check.status == CheckStatus.FAIL]
    missing_execution_evidence = [
        check
        for check in checks
        if check.invariant_number in EXECUTION_EVIDENCE_INVARIANTS
        and check.status == CheckStatus.NOT_EVALUATED
    ]
    valid = not model_errors and not failures
    execution_ready = valid and not missing_execution_evidence
    if require_execution_evidence:
        valid = execution_ready

    return ValidationReport(
        valid=valid,
        execution_ready=execution_ready,
        model_errors=tuple(model_errors),
        checks=checks,
    )
