import json
from pathlib import Path

from daybreak.cli import main

from .helpers import make_replay, make_session


def test_analytics_schema_command(capsys):
    assert main(["analytics-schema", "deployment-report"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "DeploymentEvidenceReport"


def test_session_analytics_command(tmp_path: Path):
    evidence = make_session()
    source = tmp_path / "session.json"
    output = tmp_path / "analytics.json"
    source.write_text(evidence.model_dump_json(), encoding="utf-8")
    assert main(["analytics-session", str(source), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["trade_count"] == 2


def test_replay_command(tmp_path: Path):
    report = make_replay(make_session())
    # Reconstruct its request-shaped input from report evidence.
    request = {
        "session_id": report.session_id,
        "trading_date": report.trading_date.isoformat(),
        "replayed_at": report.replayed_at.isoformat(),
        "expected_raw_event_count": report.expected_raw_event_count,
        "actual_raw_event_count": report.actual_raw_event_count,
        "event_ordering_verified": report.event_ordering_verified,
        "point_in_time_integrity_verified": report.point_in_time_integrity_verified,
        "components": [item.model_dump(mode="json") for item in report.components],
    }
    source = tmp_path / "replay.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    assert main(["analytics-replay-report", str(source)]) == 0
