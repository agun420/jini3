from __future__ import annotations

from .engine import size_approved_batch, size_position
from .models import BatchSizingRequest, BatchSizingResult, RiskDecision, SizingRequest
from .persistence import RiskRepository


class RiskService:
    """Coordinates deterministic sizing with append-only persistence.

    This service does not submit, cancel, replace, or monitor broker orders.
    """

    def __init__(self, repository: RiskRepository) -> None:
        self._repository = repository

    def evaluate(self, request: SizingRequest) -> RiskDecision:
        self._repository.save_request(request)
        decision = size_position(request)
        if decision.reservation is not None:
            self._repository.reserve(decision)
        else:
            self._repository.save_decision(decision)
        return decision

    def evaluate_batch(self, batch: BatchSizingRequest) -> BatchSizingResult:
        result = size_approved_batch(batch)
        for request, decision in zip(batch.requests, result.decisions, strict=True):
            self._repository.save_request(request)
            if decision.reservation is not None:
                self._repository.reserve(decision)
            else:
                self._repository.save_decision(decision)
        return result
