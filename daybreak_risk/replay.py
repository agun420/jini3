from __future__ import annotations

from .canonical import canonical_json_text
from .engine import size_position
from .models import RiskDecision, SizingRequest


def verify_risk_replay(request: SizingRequest, stored: RiskDecision) -> None:
    replayed = size_position(request)
    if canonical_json_text(replayed) != canonical_json_text(stored):
        raise RuntimeError("risk replay mismatch")
