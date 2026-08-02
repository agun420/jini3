from datetime import UTC, datetime

from daybreak_analytics.models import FullSessionReplayRequest
from daybreak_analytics.replay import build_full_session_replay_report

from .helpers import make_replay, make_session


def test_complete_replay_passes_all_six_components():
    report = make_replay(make_session())
    assert report.complete is True
    assert report.passed is True
    assert len(report.components) == 6


def test_missing_component_is_incomplete():
    complete = make_replay(make_session())
    request = FullSessionReplayRequest(
        session_id=complete.session_id,
        trading_date=complete.trading_date,
        replayed_at=datetime(2026, 8, 1, tzinfo=UTC),
        expected_raw_event_count=1000,
        actual_raw_event_count=1000,
        event_ordering_verified=True,
        point_in_time_integrity_verified=True,
        components=complete.components[:-1],
    )
    report = build_full_session_replay_report(request)
    assert report.complete is False
    assert report.passed is False
    assert report.errors[0].startswith("MISSING_COMPONENTS")


def test_event_count_mismatch_fails_replay():
    complete = make_replay(make_session())
    request = FullSessionReplayRequest(
        session_id=complete.session_id,
        trading_date=complete.trading_date,
        replayed_at=datetime(2026, 8, 1, tzinfo=UTC),
        expected_raw_event_count=1000,
        actual_raw_event_count=999,
        event_ordering_verified=True,
        point_in_time_integrity_verified=True,
        components=complete.components,
    )
    report = build_full_session_replay_report(request)
    assert report.passed is False
    assert "RAW_EVENT_COUNT_MISMATCH" in report.errors


def test_replay_hash_is_deterministic():
    session = make_session()
    assert make_replay(session).report_hash == make_replay(session).report_hash
