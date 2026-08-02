from __future__ import annotations

from decimal import Decimal

import pytest

from daybreak_risk.engine import size_approved_batch, size_position
from daybreak_risk.enums import RiskDecisionStatus
from daybreak_risk.models import BatchSizingRequest
from daybreak_risk.persistence import MemoryRiskRepository
from daybreak_risk.replay import verify_risk_replay

from .helpers import sizing_request


def test_batch_reserves_capacity_in_rank_order() -> None:
    first = sizing_request()
    second_base = sizing_request()
    second_setup = second_base.setup.model_copy(update={"ticker": "BBBB"})
    second = second_base.model_copy(
        update={
            "request_id": "request-2",
            "final_rank": 2,
            "setup": second_setup,
            "planned_entry_limit": Decimal("20.05"),
        }
    )
    result = size_approved_batch(BatchSizingRequest(requests=(first, second)))
    assert len(result.decisions) == 2
    assert result.decisions[0].decision == RiskDecisionStatus.APPROVED
    assert result.ending_session_state.reserved_entry_position_count >= 1
    assert result.ending_session_state.current_total_open_risk == sum(
        decision.reserved_modeled_risk or Decimal("0") for decision in result.decisions
    )


def test_batch_requires_unique_ascending_ranks() -> None:
    first = sizing_request()
    second = sizing_request().model_copy(update={"request_id": "request-2"})
    with pytest.raises(ValueError):
        BatchSizingRequest(requests=(first, second))


def test_replay_is_byte_identical() -> None:
    request = sizing_request()
    decision = size_position(request)
    verify_risk_replay(request, decision)


def test_memory_repository_is_idempotent_and_detects_client_id_collision() -> None:
    repository = MemoryRiskRepository()
    first_request = sizing_request()
    first = size_position(first_request)
    repository.save_request(first_request)
    repository.save_decision(first)
    repository.reserve(first)
    repository.reserve(first)
    assert len(repository.reservations) == 1

    second_request = first_request.model_copy(update={"request_id": "request-2"})
    second = size_position(second_request)
    assert second.reservation is not None
    collision = second.reservation.model_copy(
        update={"client_order_id": first.reservation.client_order_id}
    )
    second = second.model_copy(update={"reservation": collision})
    with pytest.raises(RuntimeError):
        repository.reserve(second)


def test_risk_service_persists_request_decision_and_reservation() -> None:
    from daybreak_risk.persistence import MemoryRiskRepository
    from daybreak_risk.service import RiskService

    repository = MemoryRiskRepository()
    service = RiskService(repository)
    request = sizing_request()
    decision = service.evaluate(request)
    assert request.request_id in repository.requests
    assert decision.decision_id in repository.decisions
    assert decision.reservation is not None
    assert decision.reservation.reservation_id in repository.reservations


def test_batch_rejects_mixed_runs() -> None:
    first = sizing_request()
    second_base = sizing_request()
    second = second_base.model_copy(
        update={
            "request_id": "request-2",
            "run_id": "other-run",
            "final_rank": 2,
            "setup": second_base.setup.model_copy(update={"ticker": "BBBB"}),
        }
    )
    with pytest.raises(ValueError):
        BatchSizingRequest(requests=(first, second))
