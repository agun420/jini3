from datetime import UTC, date, datetime

from daybreak_operations.acceptance import REQUIRED_DRILLS, build_target_acceptance_report
from daybreak_operations.backup import build_backup_manifest, validate_restore
from daybreak_operations.drills import run_failure_drill
from daybreak_operations.models import RestartState
from daybreak_operations.recovery import build_recovery_plan

CONFIG = "a" * 64
NOW = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)


def passing_probe():
    return True, "passed", {}


def build_evidence(tmp_path):
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")
    manifest = build_backup_manifest(
        artifact,
        source_database="db",
        schema_revision="0007",
        table_counts={"x": 1},
        encrypted=True,
        complete=True,
        created_at=NOW,
    )
    restore = validate_restore(
        manifest,
        target_database="restore",
        restored_schema_revision="0007",
        restored_table_counts={"x": 1},
        replay_probe=lambda: True,
        restored_at=NOW,
    )
    recovery = build_recovery_plan(
        RestartState(
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
            now=NOW,
        )
    )
    drills = tuple(
        run_failure_drill(
            item,
            inject_failure=lambda: None,
            detect_failure=lambda: True,
            entries_blocked=lambda: True,
            recovery_probe=lambda: True,
            now=lambda: NOW,
        )
        for item in REQUIRED_DRILLS
    )
    return restore, recovery, drills


def test_offline_report_is_not_target_verified(tmp_path):
    report = build_target_acceptance_report(
        configuration_hash=CONFIG, state_dir=tmp_path, generated_at=NOW
    )
    assert report.target_verified is False
    assert report.paper_ready is False


def test_full_evidence_can_pass_on_linux(tmp_path):
    restore, recovery, drills = build_evidence(tmp_path)
    probes = {
        name: passing_probe
        for name in ("alpaca_account", "alpaca_clock", "postgresql", "system_ntp", "migration_head")
    }
    report = build_target_acceptance_report(
        configuration_hash=CONFIG,
        state_dir=tmp_path,
        probes=probes,
        restore_validation=restore,
        recovery_plan=recovery,
        drill_results=drills,
        generated_at=NOW,
    )
    assert report.target_verified is True
    # Host-specific systemd/file-limit checks may fail in constrained CI; the
    # report must reflect them honestly.
    assert report.paper_ready == all(
        check.status.value == "pass" for check in report.checks if check.required
    )


def test_missing_drill_prevents_readiness(tmp_path):
    restore, recovery, drills = build_evidence(tmp_path)
    probes = {
        name: passing_probe
        for name in ("alpaca_account", "alpaca_clock", "postgresql", "system_ntp", "migration_head")
    }
    report = build_target_acceptance_report(
        configuration_hash=CONFIG,
        state_dir=tmp_path,
        probes=probes,
        restore_validation=restore,
        recovery_plan=recovery,
        drill_results=drills[:-1],
        generated_at=NOW,
    )
    check = next(item for item in report.checks if item.name == "failure_drills")
    assert check.status.value == "fail"
    assert report.paper_ready is False
