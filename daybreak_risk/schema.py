from __future__ import annotations

from .models import BatchSizingRequest, BatchSizingResult, RiskDecision, SizingRequest


def risk_sizing_request_schema() -> dict[str, object]:
    return SizingRequest.model_json_schema()


def risk_decision_schema() -> dict[str, object]:
    return RiskDecision.model_json_schema()


def batch_sizing_request_schema() -> dict[str, object]:
    return BatchSizingRequest.model_json_schema()


def batch_sizing_result_schema() -> dict[str, object]:
    return BatchSizingResult.model_json_schema()
