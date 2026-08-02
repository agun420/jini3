from __future__ import annotations

from collections.abc import Iterable

from .models import CheckStatus, InvariantCheck, InvariantViolation


def passed(number: int, name: str, note: str | None = None) -> InvariantCheck:
    return InvariantCheck(
        invariant_number=number,
        name=name,
        status=CheckStatus.PASS,
        note=note,
    )


def not_evaluated(number: int, name: str, note: str) -> InvariantCheck:
    return InvariantCheck(
        invariant_number=number,
        name=name,
        status=CheckStatus.NOT_EVALUATED,
        note=note,
    )


def checked(
    number: int,
    name: str,
    violations: Iterable[InvariantViolation],
) -> InvariantCheck:
    items = tuple(violations)
    return InvariantCheck(
        invariant_number=number,
        name=name,
        status=CheckStatus.FAIL if items else CheckStatus.PASS,
        violations=items,
    )


def violation(
    number: int,
    path: str,
    expected: object,
    observed: object,
    message: str,
) -> InvariantViolation:
    return InvariantViolation(
        invariant_number=number,
        path=path,
        expected=str(expected),
        observed=str(observed),
        message=message,
    )
