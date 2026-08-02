from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

CENT = Decimal("0.01")
MONEY_QUANTUM = Decimal("0.0000000001")


def floor_to_cent(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_FLOOR)


def floor_to_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def round_down_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        raise ValueError("increment must be positive")
    units = (value / increment).to_integral_value(rounding=ROUND_FLOOR)
    return units * increment


def round_up_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        raise ValueError("increment must be positive")
    units = (value / increment).to_integral_value(rounding=ROUND_CEILING)
    return units * increment


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
