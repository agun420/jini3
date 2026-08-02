"""Phase 6 integrated session orchestration and operational safety.

Revision ID: 0006_phase6_orchestration
Revises: 0005_phase5_execution
Create Date: 2026-08-01
"""
from __future__ import annotations

from alembic import op

revision = "0006_phase6_orchestration"
down_revision = "0005_phase5_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    CREATE TABLE orchestration_sessions (
        session_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        trading_date DATE NOT NULL,
        configuration_hash CHAR(64) NOT NULL CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
        plan_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE UNIQUE INDEX orchestration_session_run_idx
        ON orchestration_sessions(trading_date, run_id);

    CREATE TABLE orchestration_leases (
        session_id TEXT PRIMARY KEY REFERENCES orchestration_sessions(session_id),
        holder_id TEXT NOT NULL,
        acquired_at TIMESTAMPTZ NOT NULL,
        renewed_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        fencing_token BIGINT NOT NULL CHECK (fencing_token >= 1),
        active BOOLEAN NOT NULL DEFAULT TRUE,
        released_at TIMESTAMPTZ,
        CHECK (expires_at >= renewed_at),
        CHECK (renewed_at >= acquired_at),
        CHECK ((active AND released_at IS NULL) OR (NOT active AND released_at IS NOT NULL))
    );

    CREATE TABLE orchestration_leadership_events (
        event_hash CHAR(64) PRIMARY KEY CHECK (event_hash ~ '^[0-9a-f]{64}$'),
        session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
        holder_id TEXT NOT NULL,
        event_type TEXT NOT NULL CHECK (event_type IN ('acquired','renewed','released','lost')),
        event_timestamp TIMESTAMPTZ NOT NULL,
        fencing_token BIGINT NOT NULL CHECK (fencing_token >= 1),
        event_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE orchestration_phase_records (
        session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        phase TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('started','completed','failed','skipped')),
        started_at TIMESTAMPTZ NOT NULL,
        ended_at TIMESTAMPTZ,
        record_hash CHAR(64) NOT NULL UNIQUE CHECK (record_hash ~ '^[0-9a-f]{64}$'),
        record_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (session_id, sequence),
        CHECK (ended_at IS NULL OR ended_at >= started_at)
    );

    CREATE TABLE orchestration_kill_switch_events (
        state_hash CHAR(64) PRIMARY KEY CHECK (state_hash ~ '^[0-9a-f]{64}$'),
        session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
        active BOOLEAN NOT NULL,
        activated_at TIMESTAMPTZ,
        reason TEXT,
        state_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK ((active AND activated_at IS NOT NULL AND reason IS NOT NULL)
            OR (NOT active AND activated_at IS NULL AND reason IS NULL))
    );

    CREATE TABLE orchestration_alerts (
        alert_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
        severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
        code TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        dedup_key TEXT NOT NULL,
        alert_hash CHAR(64) NOT NULL UNIQUE CHECK (alert_hash ~ '^[0-9a-f]{64}$'),
        alert_json JSONB NOT NULL
    );
    CREATE INDEX orchestration_alerts_session_idx
        ON orchestration_alerts(session_id, created_at);

    CREATE TABLE orchestration_flatten_results (
        flatten_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
        started_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ NOT NULL,
        complete BOOLEAN NOT NULL,
        result_hash CHAR(64) NOT NULL UNIQUE CHECK (result_hash ~ '^[0-9a-f]{64}$'),
        result_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (completed_at >= started_at)
    );

    CREATE TABLE orchestration_session_results (
        result_hash CHAR(64) PRIMARY KEY CHECK (result_hash ~ '^[0-9a-f]{64}$'),
        session_id TEXT NOT NULL REFERENCES orchestration_sessions(session_id),
        outcome TEXT NOT NULL CHECK (outcome IN (
            'completed','no_setups','blocked','failed','killed','flatten_incomplete'
        )),
        completed_at TIMESTAMPTZ NOT NULL,
        final_phase TEXT NOT NULL,
        result_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE orchestration_acceptance_reports (
        report_id TEXT PRIMARY KEY,
        generated_at TIMESTAMPTZ NOT NULL,
        online_verified BOOLEAN NOT NULL,
        paper_ready BOOLEAN NOT NULL,
        configuration_hash CHAR(64) NOT NULL CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
        report_hash CHAR(64) NOT NULL UNIQUE CHECK (report_hash ~ '^[0-9a-f]{64}$'),
        report_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE OR REPLACE FUNCTION daybreak_forbid_orchestration_mutation()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Daybreak orchestration audit tables are append-only'; END;
    $$;
    CREATE TRIGGER orchestration_sessions_append_only BEFORE UPDATE OR DELETE ON orchestration_sessions FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_orchestration_mutation();
    CREATE TRIGGER orchestration_leadership_events_append_only BEFORE UPDATE OR DELETE ON orchestration_leadership_events FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_orchestration_mutation();
    CREATE TRIGGER orchestration_phase_records_append_only BEFORE UPDATE OR DELETE ON orchestration_phase_records FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_orchestration_mutation();
    CREATE TRIGGER orchestration_kill_switch_append_only BEFORE UPDATE OR DELETE ON orchestration_kill_switch_events FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_orchestration_mutation();
    CREATE TRIGGER orchestration_alerts_append_only BEFORE UPDATE OR DELETE ON orchestration_alerts FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_orchestration_mutation();
    CREATE TRIGGER orchestration_flatten_append_only BEFORE UPDATE OR DELETE ON orchestration_flatten_results FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_orchestration_mutation();
    CREATE TRIGGER orchestration_results_append_only BEFORE UPDATE OR DELETE ON orchestration_session_results FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_orchestration_mutation();
    CREATE TRIGGER orchestration_acceptance_append_only BEFORE UPDATE OR DELETE ON orchestration_acceptance_reports FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_orchestration_mutation();
    """)


def downgrade() -> None:
    op.execute(r"""
    DROP TRIGGER IF EXISTS orchestration_acceptance_append_only ON orchestration_acceptance_reports;
    DROP TRIGGER IF EXISTS orchestration_results_append_only ON orchestration_session_results;
    DROP TRIGGER IF EXISTS orchestration_flatten_append_only ON orchestration_flatten_results;
    DROP TRIGGER IF EXISTS orchestration_alerts_append_only ON orchestration_alerts;
    DROP TRIGGER IF EXISTS orchestration_kill_switch_append_only ON orchestration_kill_switch_events;
    DROP TRIGGER IF EXISTS orchestration_phase_records_append_only ON orchestration_phase_records;
    DROP TRIGGER IF EXISTS orchestration_leadership_events_append_only ON orchestration_leadership_events;
    DROP TRIGGER IF EXISTS orchestration_sessions_append_only ON orchestration_sessions;
    DROP FUNCTION IF EXISTS daybreak_forbid_orchestration_mutation();
    DROP TABLE IF EXISTS orchestration_acceptance_reports;
    DROP TABLE IF EXISTS orchestration_session_results;
    DROP TABLE IF EXISTS orchestration_flatten_results;
    DROP TABLE IF EXISTS orchestration_alerts;
    DROP TABLE IF EXISTS orchestration_kill_switch_events;
    DROP TABLE IF EXISTS orchestration_phase_records;
    DROP TABLE IF EXISTS orchestration_leadership_events;
    DROP TABLE IF EXISTS orchestration_leases;
    DROP TABLE IF EXISTS orchestration_sessions;
    """)
