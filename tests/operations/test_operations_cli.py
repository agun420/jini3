import json
from datetime import UTC, date, datetime
from pathlib import Path

from daybreak.cli import main
from daybreak_operations.models import RestartState


def test_operations_schema_command(capsys):
    assert main(["operations-schema", "recovery-plan"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "RecoveryPlan"


def test_recovery_plan_command(tmp_path: Path, capsys):
    state = RestartState(
        trading_date=date(2026, 8, 3),
        session_id="s",
        previous_outcome="failed",
        kill_switch_active=False,
        managed_position_count=0,
        open_daybreak_order_count=0,
        recorder_checkpoint_available=True,
        database_consistent=True,
        leadership_lease_active=False,
        configuration_hash_matches=True,
        now=datetime(2026, 8, 3, 13, tzinfo=UTC),
    )
    path = tmp_path / "state.json"
    path.write_text(state.model_dump_json(), encoding="utf-8")
    assert main(["operations-recovery-plan", str(path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["may_resume_new_entries"] is False


def test_backup_and_restore_commands(tmp_path: Path):
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")
    manifest = tmp_path / "manifest.json"
    assert (
        main(
            [
                "operations-backup-manifest",
                str(artifact),
                "--source-database",
                "db",
                "--schema-revision",
                "0007",
                "--table-counts",
                '{"raw_events":1}',
                "--encrypted",
                "--complete",
                "--output",
                str(manifest),
            ]
        )
        == 0
    )
    result = tmp_path / "restore.json"
    assert (
        main(
            [
                "operations-restore-validate",
                str(manifest),
                "--target-database",
                "restore",
                "--schema-revision",
                "0007",
                "--table-counts",
                '{"raw_events":1}',
                "--replay-verified",
                "--output",
                str(result),
            ]
        )
        == 0
    )
    assert json.loads(result.read_text())["passed"] is True


def test_drill_simulation_requires_confirmation(capsys):
    assert main(["operations-drill-simulate", "database_disconnect"]) == 2
    assert "confirm-simulation" in capsys.readouterr().err


def test_drill_simulation_passes_with_confirmation(capsys):
    assert main(["operations-drill-simulate", "database_disconnect", "--confirm-simulation"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
