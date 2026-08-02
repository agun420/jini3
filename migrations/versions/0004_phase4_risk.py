"""Phase 4 deterministic risk engine persistence.

Revision ID: 0004_phase4_risk
Revises: 0003_phase3_evaluator
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op

revision = "0004_phase4_risk"
down_revision = "0003_phase3_evaluator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE risk_sizing_requests (
            request_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            trading_date DATE NOT NULL,
            ticker TEXT NOT NULL,
            final_rank INTEGER NOT NULL CHECK (final_rank BETWEEN 1 AND 3),
            calculated_at TIMESTAMPTZ NOT NULL,
            configuration_hash CHAR(64) NOT NULL
                CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
            input_hash CHAR(64) NOT NULL
                CHECK (input_hash ~ '^[0-9a-f]{64}$'),
            request_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX risk_sizing_requests_run_idx
            ON risk_sizing_requests (run_id, final_rank);

        CREATE TABLE risk_sizing_decisions (
            decision_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL REFERENCES risk_sizing_requests(request_id),
            run_id TEXT NOT NULL,
            trading_date DATE NOT NULL,
            ticker TEXT NOT NULL,
            final_rank INTEGER NOT NULL CHECK (final_rank BETWEEN 1 AND 3),
            decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
            kill_switch_required BOOLEAN NOT NULL,
            final_quantity BIGINT NOT NULL CHECK (final_quantity >= 0),
            binding_cap TEXT CHECK (binding_cap IS NULL OR binding_cap IN (
                'TRADE_RISK', 'OPEN_RISK', 'DAILY_LOSS', 'BUYING_POWER',
                'POSITION_NOTIONAL', 'GROSS_EXPOSURE', 'ADV_LIQUIDITY',
                'PREMARKET_LIQUIDITY'
            )),
            input_hash CHAR(64) NOT NULL
                CHECK (input_hash ~ '^[0-9a-f]{64}$'),
            decision_hash CHAR(64) NOT NULL UNIQUE
                CHECK (decision_hash ~ '^[0-9a-f]{64}$'),
            decision_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (decision = 'approved' AND final_quantity > 0 AND binding_cap IS NOT NULL)
                OR
                (decision = 'rejected' AND final_quantity = 0 AND binding_cap IS NULL)
            )
        );

        CREATE INDEX risk_sizing_decisions_run_idx
            ON risk_sizing_decisions (run_id, final_rank);

        CREATE TABLE risk_reservations (
            reservation_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL UNIQUE
                REFERENCES risk_sizing_decisions(decision_id),
            request_id TEXT NOT NULL REFERENCES risk_sizing_requests(request_id),
            run_id TEXT NOT NULL,
            trading_date DATE NOT NULL,
            ticker TEXT NOT NULL,
            client_order_id TEXT NOT NULL UNIQUE,
            reserved_quantity BIGINT NOT NULL CHECK (reserved_quantity > 0),
            reserved_notional NUMERIC(30,10) NOT NULL CHECK (reserved_notional > 0),
            reserved_modeled_risk NUMERIC(30,10) NOT NULL
                CHECK (reserved_modeled_risk > 0),
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            initial_status TEXT NOT NULL CHECK (initial_status = 'reserved'),
            reservation_json JSONB NOT NULL,
            inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (expires_at > created_at)
        );

        CREATE INDEX risk_reservations_run_idx
            ON risk_reservations (run_id, ticker);

        CREATE TABLE risk_reservation_events (
            reservation_id TEXT NOT NULL REFERENCES risk_reservations(reservation_id),
            event_sequence INTEGER NOT NULL CHECK (event_sequence >= 1),
            status TEXT NOT NULL CHECK (status IN (
                'reserved', 'submitted', 'partially_filled', 'filled',
                'released', 'expired', 'reconciliation_required'
            )),
            event_timestamp TIMESTAMPTZ NOT NULL,
            event_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (reservation_id, event_sequence)
        );

        CREATE OR REPLACE FUNCTION daybreak_forbid_risk_mutation()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Daybreak risk audit tables are append-only';
        END;
        $$;

        CREATE TRIGGER risk_sizing_requests_append_only
            BEFORE UPDATE OR DELETE ON risk_sizing_requests
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_risk_mutation();
        CREATE TRIGGER risk_sizing_decisions_append_only
            BEFORE UPDATE OR DELETE ON risk_sizing_decisions
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_risk_mutation();
        CREATE TRIGGER risk_reservations_append_only
            BEFORE UPDATE OR DELETE ON risk_reservations
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_risk_mutation();
        CREATE TRIGGER risk_reservation_events_append_only
            BEFORE UPDATE OR DELETE ON risk_reservation_events
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_risk_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        r"""
        DROP TRIGGER IF EXISTS risk_reservation_events_append_only ON risk_reservation_events;
        DROP TRIGGER IF EXISTS risk_reservations_append_only ON risk_reservations;
        DROP TRIGGER IF EXISTS risk_sizing_decisions_append_only ON risk_sizing_decisions;
        DROP TRIGGER IF EXISTS risk_sizing_requests_append_only ON risk_sizing_requests;
        DROP FUNCTION IF EXISTS daybreak_forbid_risk_mutation();
        DROP TABLE IF EXISTS risk_reservation_events;
        DROP TABLE IF EXISTS risk_reservations;
        DROP TABLE IF EXISTS risk_sizing_decisions;
        DROP TABLE IF EXISTS risk_sizing_requests;
        """
    )
