"""Phase 5 paper execution and broker reconciliation persistence.

Revision ID: 0005_phase5_execution
Revises: 0004_phase4_risk
Create Date: 2026-08-01
"""
from __future__ import annotations
from alembic import op
revision = "0005_phase5_execution"
down_revision = "0004_phase4_risk"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(r"""
    CREATE TABLE execution_requests (
        execution_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        trading_date DATE NOT NULL,
        ticker TEXT NOT NULL,
        requested_at TIMESTAMPTZ NOT NULL,
        submission_cutoff_timestamp TIMESTAMPTZ NOT NULL,
        risk_decision_id TEXT NOT NULL REFERENCES risk_sizing_decisions(decision_id),
        configuration_hash CHAR(64) NOT NULL CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
        request_hash CHAR(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
        request_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (submission_cutoff_timestamp >= requested_at)
    );
    CREATE INDEX execution_requests_run_idx ON execution_requests(run_id, ticker);

    CREATE TABLE execution_order_commands (
        command_id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
        client_order_id TEXT NOT NULL UNIQUE,
        symbol TEXT NOT NULL,
        quantity BIGINT NOT NULL CHECK (quantity > 0),
        side TEXT NOT NULL CHECK (side IN ('buy','sell')),
        order_type TEXT NOT NULL CHECK (order_type IN ('limit','stop')),
        time_in_force TEXT NOT NULL CHECK (time_in_force = 'day'),
        order_class TEXT NOT NULL CHECK (order_class IN ('bracket','simple')),
        command_hash CHAR(64) NOT NULL CHECK (command_hash ~ '^[0-9a-f]{64}$'),
        command_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX execution_commands_execution_idx ON execution_order_commands(execution_id);

    CREATE TABLE execution_broker_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
        broker_order_id TEXT NOT NULL,
        client_order_id TEXT NOT NULL,
        status TEXT NOT NULL,
        filled_quantity NUMERIC(30,10) NOT NULL CHECK (filled_quantity >= 0),
        observed_at TIMESTAMPTZ NOT NULL,
        raw_response_hash CHAR(64) NOT NULL CHECK (raw_response_hash ~ '^[0-9a-f]{64}$'),
        snapshot_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX execution_snapshots_order_idx ON execution_broker_snapshots(broker_order_id, observed_at);

    CREATE TABLE execution_events (
        execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
        event_sequence INTEGER NOT NULL CHECK (event_sequence >= 1),
        event_type TEXT NOT NULL,
        event_timestamp TIMESTAMPTZ NOT NULL,
        broker_order_id TEXT,
        client_order_id TEXT,
        status TEXT,
        event_hash CHAR(64) NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
        event_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (execution_id, event_sequence)
    );

    CREATE TABLE execution_results (
        result_id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
        outcome TEXT NOT NULL CHECK (outcome IN (
            'submitted','existing_reconciled','partial_fill_protected',
            'rejected','reconciliation_required'
        )),
        reconciliation_required BOOLEAN NOT NULL,
        completed_at TIMESTAMPTZ NOT NULL,
        request_hash CHAR(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
        result_hash CHAR(64) NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
        result_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX execution_results_execution_idx ON execution_results(execution_id, completed_at);

    CREATE TABLE execution_trade_updates (
        event_id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
        raw_event_hash CHAR(64) NOT NULL CHECK (raw_event_hash ~ '^[0-9a-f]{64}$'),
        claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE execution_reconciliation_reports (
        report_id TEXT PRIMARY KEY,
        execution_id TEXT NOT NULL REFERENCES execution_requests(execution_id),
        client_order_id TEXT NOT NULL,
        checked_at TIMESTAMPTZ NOT NULL,
        matched BOOLEAN NOT NULL,
        report_hash CHAR(64) NOT NULL CHECK (report_hash ~ '^[0-9a-f]{64}$'),
        report_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE OR REPLACE FUNCTION daybreak_forbid_execution_mutation()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Daybreak execution audit tables are append-only'; END;
    $$;
    CREATE TRIGGER execution_requests_append_only BEFORE UPDATE OR DELETE ON execution_requests FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_execution_mutation();
    CREATE TRIGGER execution_commands_append_only BEFORE UPDATE OR DELETE ON execution_order_commands FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_execution_mutation();
    CREATE TRIGGER execution_snapshots_append_only BEFORE UPDATE OR DELETE ON execution_broker_snapshots FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_execution_mutation();
    CREATE TRIGGER execution_events_append_only BEFORE UPDATE OR DELETE ON execution_events FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_execution_mutation();
    CREATE TRIGGER execution_results_append_only BEFORE UPDATE OR DELETE ON execution_results FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_execution_mutation();
    CREATE TRIGGER execution_trade_updates_append_only BEFORE UPDATE OR DELETE ON execution_trade_updates FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_execution_mutation();
    CREATE TRIGGER execution_reconciliation_append_only BEFORE UPDATE OR DELETE ON execution_reconciliation_reports FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_execution_mutation();
    """)

def downgrade() -> None:
    op.execute(r"""
    DROP TRIGGER IF EXISTS execution_reconciliation_append_only ON execution_reconciliation_reports;
    DROP TRIGGER IF EXISTS execution_trade_updates_append_only ON execution_trade_updates;
    DROP TRIGGER IF EXISTS execution_results_append_only ON execution_results;
    DROP TRIGGER IF EXISTS execution_events_append_only ON execution_events;
    DROP TRIGGER IF EXISTS execution_snapshots_append_only ON execution_broker_snapshots;
    DROP TRIGGER IF EXISTS execution_commands_append_only ON execution_order_commands;
    DROP TRIGGER IF EXISTS execution_requests_append_only ON execution_requests;
    DROP FUNCTION IF EXISTS daybreak_forbid_execution_mutation();
    DROP TABLE IF EXISTS execution_reconciliation_reports;
    DROP TABLE IF EXISTS execution_trade_updates;
    DROP TABLE IF EXISTS execution_results;
    DROP TABLE IF EXISTS execution_events;
    DROP TABLE IF EXISTS execution_broker_snapshots;
    DROP TABLE IF EXISTS execution_order_commands;
    DROP TABLE IF EXISTS execution_requests;
    """)
