from daybreak_analytics.analytics import analyze_session
from daybreak_analytics.persistence import MemoryAnalyticsRepository
from daybreak_analytics.schema import (
    deployment_evidence_report_schema,
    paper_acceptance_ledger_schema,
    replay_report_schema,
    session_performance_schema,
)

from .helpers import make_replay, make_session


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
