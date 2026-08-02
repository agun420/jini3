from datetime import UTC, date, datetime

from daybreak_operations.models import RestartState
from daybreak_operations.persistence import MemoryOperationsRepository
from daybreak_operations.recovery import build_recovery_plan
from daybreak_operations.schema import recovery_plan_schema, target_acceptance_schema


def test_memory_repository_is_idempotent():
    plan = build_recovery_plan(
        RestartState(
            trading_date=date(2026, 8, 3),
            session_id="s",
            previous_outcome=None,
            kill_switch_active=False,
            managed_position_count=0,
            open_daybreak_order_count=0,
            recorder_checkpoint_available=True,
            database_consistent=True,
            leadership_lease_active=False,
            configuration_hash_matches=True,
            now=datetime(2026, 8, 3, tzinfo=UTC),
        )
    )
    repo = MemoryOperationsRepository()
    repo.save_recovery(plan)
    repo.save_recovery(plan)
    assert len(repo.recovery) == 1


def test_schemas_are_strict_objects():
    for schema in (recovery_plan_schema(), target_acceptance_schema()):
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
