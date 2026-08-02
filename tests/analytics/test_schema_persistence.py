from datetime import UTC, datetime
from decimal import Decimal

from daybreak_analytics.acceptance import build_paper_acceptance_ledger
from daybreak_analytics.analytics import analyze_session
from daybreak_analytics.models import AnalyticsPolicy, PaperAcceptanceRequest
from daybreak_analytics.persistence import MemoryAnalyticsRepository
from daybreak_analytics.schema import (
    deployment_evidence_report_schema,
    paper_acceptance_ledger_schema,
    replay_report_schema,
    session_performance_schema,
)
from daybreak_operations.enums import DrillType

from .helpers import H, make_replay, make_session


def test_schemas_are_strict_objects():
    for schema in (
        session_performance_schema(),
        replay_report_schema(),
        paper_acceptance_ledger_schema(),
        deployment_evidence_report_schema(),
    ):
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_memory_repository_is_idempotent():
    session = make_session()
    performance = analyze_session(session)
    replay = make_replay(session)
    repo = MemoryAnalyticsRepository()
    repo.save_session_performance(performance)
    repo.save_session_performance(performance)
    repo.save_replay_report(replay)
    repo.save_replay_report(replay)
    assert len(repo.session_performance) == 1
    assert len(repo.replay_reports) == 1


def test_get_session_performance_looks_up_by_session_id_not_analytics_id():
    session = make_session()
    performance = analyze_session(session)
    repo = MemoryAnalyticsRepository()
    repo.save_session_performance(performance)

    assert repo.get_session_performance(session.session_id) == performance
    assert repo.get_session_performance("no-such-session") is None


def test_get_latest_paper_ledger_returns_most_recently_generated():
    def ledger_request(*, count: int, generated_at: datetime) -> PaperAcceptanceRequest:
        sessions = tuple(make_session(index=i) for i in range(count))
        reports = tuple(make_replay(item) for item in sessions)
        return PaperAcceptanceRequest(
            generated_at=generated_at,
            policy=AnalyticsPolicy(
                minimum_sessions=2,
                minimum_filled_orders=4,
                minimum_clean_session_rate=Decimal("1"),
                required_drill_count=2,
            ),
            sessions=sessions,
            replay_reports=reports,
            target_acceptance_verified=True,
            restore_validation_verified=True,
            passed_drills=(DrillType.DATABASE_DISCONNECT, DrillType.PROCESS_RESTART),
            configuration_hash=H,
        )

    repo = MemoryAnalyticsRepository()
    assert repo.get_latest_paper_ledger() is None

    older = build_paper_acceptance_ledger(
        ledger_request(count=2, generated_at=datetime(2026, 8, 1, tzinfo=UTC))
    )
    newer = build_paper_acceptance_ledger(
        ledger_request(count=2, generated_at=datetime(2026, 8, 2, tzinfo=UTC))
    )
    repo.save_paper_ledger(older)
    repo.save_paper_ledger(newer)
    assert repo.get_latest_paper_ledger() == newer
