"""Phase 8 replay analytics, paper acceptance, and deployment evidence.

Revision ID: 0008_phase8_analytics
Revises: 0007_phase7_operations
Create Date: 2026-08-01
"""
from __future__ import annotations

from alembic import op

revision = "0008_phase8_analytics"
down_revision = "0007_phase7_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    CREATE TABLE analytics_session_performance (
        analytics_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE analytics_replay_reports (
        replay_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE analytics_paper_acceptance_ledgers (
        ledger_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE analytics_deployment_evidence (
        report_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE OR REPLACE FUNCTION daybreak_forbid_analytics_mutation()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Daybreak analytics and evidence tables are append-only'; END;
    $$;
    CREATE TRIGGER analytics_session_append_only BEFORE UPDATE OR DELETE ON analytics_session_performance FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_analytics_mutation();
    CREATE TRIGGER analytics_replay_append_only BEFORE UPDATE OR DELETE ON analytics_replay_reports FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_analytics_mutation();
    CREATE TRIGGER analytics_ledger_append_only BEFORE UPDATE OR DELETE ON analytics_paper_acceptance_ledgers FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_analytics_mutation();
    CREATE TRIGGER analytics_deployment_append_only BEFORE UPDATE OR DELETE ON analytics_deployment_evidence FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_analytics_mutation();
    """)


def downgrade() -> None:
    op.execute(r"""
    DROP TRIGGER IF EXISTS analytics_deployment_append_only ON analytics_deployment_evidence;
    DROP TRIGGER IF EXISTS analytics_ledger_append_only ON analytics_paper_acceptance_ledgers;
    DROP TRIGGER IF EXISTS analytics_replay_append_only ON analytics_replay_reports;
    DROP TRIGGER IF EXISTS analytics_session_append_only ON analytics_session_performance;
    DROP FUNCTION IF EXISTS daybreak_forbid_analytics_mutation();
    DROP TABLE IF EXISTS analytics_deployment_evidence;
    DROP TABLE IF EXISTS analytics_paper_acceptance_ledgers;
    DROP TABLE IF EXISTS analytics_replay_reports;
    DROP TABLE IF EXISTS analytics_session_performance;
    """)
