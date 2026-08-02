from daybreak_execution.order_builder import build_entry_command
from daybreak_execution.persistence import MemoryExecutionRepository
from daybreak_execution.reconciliation import reconcile_command
from daybreak_execution.schema import execution_request_schema, execution_result_schema
from tests.execution.helpers import FakeBroker, execution_request, snapshot_for


def test_reconciliation_matches_order_identity():
    request = execution_request()
    command = build_entry_command(request, now=request.requested_at)
    broker = FakeBroker()
    broker.orders[command.client_order_id] = snapshot_for(command)
    report = reconcile_command(
        request.execution_id, command, broker, checked_at=request.requested_at
    )
    assert report.matched is True
    assert report.mismatch_codes == ()


def test_memory_repository_rejects_client_order_collision():
    request = execution_request()
    command = build_entry_command(request, now=request.requested_at)
    repo = MemoryExecutionRepository()
    repo.save_command(command)
    changed = command.model_copy(update={"quantity": command.quantity + 1})
    try:
        repo.save_command(changed)
    except RuntimeError as exc:
        assert "collision" in str(exc)
    else:
        raise AssertionError("expected collision")


def test_execution_schemas_are_strict_models():
    assert execution_request_schema()["title"] == "ExecutionRequest"
    assert execution_result_schema()["title"] == "ExecutionResult"
