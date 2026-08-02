from __future__ import annotations

from .models import (
    BrokerOrderCommand,
    ExecutionPolicy,
    ExecutionRequest,
    ExecutionResult,
    ReconciliationReport,
    TradeUpdate,
)


def execution_policy_schema() -> dict[str, object]:
    return ExecutionPolicy.model_json_schema()


def execution_request_schema() -> dict[str, object]:
    return ExecutionRequest.model_json_schema()


def broker_order_command_schema() -> dict[str, object]:
    return BrokerOrderCommand.model_json_schema()


def execution_result_schema() -> dict[str, object]:
    return ExecutionResult.model_json_schema()


def trade_update_schema() -> dict[str, object]:
    return TradeUpdate.model_json_schema()


def reconciliation_report_schema() -> dict[str, object]:
    return ReconciliationReport.model_json_schema()
