"""Phase 7 operational resilience, recovery, and target acceptance.

Revision ID: 0007_phase7_operations
Revises: 0006_phase6_orchestration
Create Date: 2026-08-01
"""
from __future__ import annotations

from alembic import op

revision = "0007_phase7_operations"
down_revision = "0006_phase6_orchestration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    CREATE TABLE operations_observability_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE operations_recovery_plans (
        plan_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE operations_backup_manifests (
        backup_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE operations_restore_validations (
        validation_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE operations_drill_results (
        drill_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE operations_acceptance_reports (
        report_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE OR REPLACE FUNCTION daybreak_forbid_operations_mutation()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Daybreak operations audit tables are append-only'; END;
    $$;
    CREATE TRIGGER operations_observability_append_only BEFORE UPDATE OR DELETE ON operations_observability_snapshots FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_operations_mutation();
    CREATE TRIGGER operations_recovery_append_only BEFORE UPDATE OR DELETE ON operations_recovery_plans FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_operations_mutation();
    CREATE TRIGGER operations_backup_append_only BEFORE UPDATE OR DELETE ON operations_backup_manifests FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_operations_mutation();
    CREATE TRIGGER operations_restore_append_only BEFORE UPDATE OR DELETE ON operations_restore_validations FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_operations_mutation();
    CREATE TRIGGER operations_drill_append_only BEFORE UPDATE OR DELETE ON operations_drill_results FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_operations_mutation();
    CREATE TRIGGER operations_acceptance_append_only BEFORE UPDATE OR DELETE ON operations_acceptance_reports FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_operations_mutation();
    """)


def downgrade() -> None:
    op.execute(r"""
    DROP TRIGGER IF EXISTS operations_acceptance_append_only ON operations_acceptance_reports;
    DROP TRIGGER IF EXISTS operations_drill_append_only ON operations_drill_results;
    DROP TRIGGER IF EXISTS operations_restore_append_only ON operations_restore_validations;
    DROP TRIGGER IF EXISTS operations_backup_append_only ON operations_backup_manifests;
    DROP TRIGGER IF EXISTS operations_recovery_append_only ON operations_recovery_plans;
    DROP TRIGGER IF EXISTS operations_observability_append_only ON operations_observability_snapshots;
    DROP FUNCTION IF EXISTS daybreak_forbid_operations_mutation();
    DROP TABLE IF EXISTS operations_acceptance_reports;
    DROP TABLE IF EXISTS operations_drill_results;
    DROP TABLE IF EXISTS operations_restore_validations;
    DROP TABLE IF EXISTS operations_backup_manifests;
    DROP TABLE IF EXISTS operations_recovery_plans;
    DROP TABLE IF EXISTS operations_observability_snapshots;
    """)
