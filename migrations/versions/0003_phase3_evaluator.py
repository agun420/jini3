"""Phase 3 evaluator requests, attempts, results, and shadow comparisons.

Revision ID: 0003_phase3_evaluator
Revises: 0002_phase2_features
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op

revision = "0003_phase3_evaluator"
down_revision = "0002_phase2_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE evaluator_runs (
            run_id TEXT PRIMARY KEY,
            requested_at TIMESTAMPTZ NOT NULL,
            response_cutoff_timestamp TIMESTAMPTZ NOT NULL,
            payload_hash CHAR(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            configuration_hash CHAR(64) NOT NULL
                CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
            request_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (response_cutoff_timestamp > requested_at)
        );

        CREATE TABLE evaluator_attempts (
            attempt_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES evaluator_runs(run_id),
            role TEXT NOT NULL CHECK (role IN ('primary', 'shadow')),
            attempt_number INTEGER NOT NULL CHECK (attempt_number BETWEEN 1 AND 2),
            model TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'succeeded', 'deadline_exceeded', 'transport_error', 'refused',
                'incomplete', 'empty_output', 'invalid_json', 'schema_invalid',
                'invariant_invalid', 'canceled'
            )),
            request_started_at TIMESTAMPTZ NOT NULL,
            response_received_at TIMESTAMPTZ,
            response_id TEXT,
            request_hash CHAR(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            prompt_hash CHAR(64) NOT NULL CHECK (prompt_hash ~ '^[0-9a-f]{64}$'),
            spec_hash CHAR(64) NOT NULL CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
            schema_hash CHAR(64) NOT NULL CHECK (schema_hash ~ '^[0-9a-f]{64}$'),
            response_text_hash CHAR(64)
                CHECK (response_text_hash IS NULL OR response_text_hash ~ '^[0-9a-f]{64}$'),
            raw_response_hash CHAR(64)
                CHECK (raw_response_hash IS NULL OR raw_response_hash ~ '^[0-9a-f]{64}$'),
            attempt_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (run_id, role, attempt_number)
        );

        CREATE INDEX evaluator_attempts_run_role_idx
            ON evaluator_attempts (run_id, role, attempt_number);
        CREATE INDEX evaluator_attempts_response_id_idx
            ON evaluator_attempts (response_id) WHERE response_id IS NOT NULL;

        CREATE TABLE evaluator_results (
            result_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE REFERENCES evaluator_runs(run_id),
            status TEXT NOT NULL CHECK (status IN (
                'primary_valid', 'primary_invalid', 'cutoff_missed', 'input_rejected'
            )),
            selected_primary_attempt_id TEXT REFERENCES evaluator_attempts(attempt_id),
            decision_ready_at TIMESTAMPTZ,
            late_response_rejected BOOLEAN NOT NULL,
            result_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE evaluator_shadow_comparisons (
            comparison_id BIGSERIAL PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE REFERENCES evaluator_runs(run_id),
            primary_attempt_id TEXT NOT NULL REFERENCES evaluator_attempts(attempt_id),
            shadow_attempt_id TEXT NOT NULL REFERENCES evaluator_attempts(attempt_id),
            exact_output_match BOOLEAN NOT NULL,
            comparison_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (primary_attempt_id <> shadow_attempt_id)
        );

        CREATE TRIGGER evaluator_runs_append_only
            BEFORE UPDATE OR DELETE ON evaluator_runs
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();
        CREATE TRIGGER evaluator_attempts_append_only
            BEFORE UPDATE OR DELETE ON evaluator_attempts
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();
        CREATE TRIGGER evaluator_results_append_only
            BEFORE UPDATE OR DELETE ON evaluator_results
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();
        CREATE TRIGGER evaluator_shadow_comparisons_append_only
            BEFORE UPDATE OR DELETE ON evaluator_shadow_comparisons
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        r"""
        DROP TRIGGER IF EXISTS evaluator_shadow_comparisons_append_only
            ON evaluator_shadow_comparisons;
        DROP TRIGGER IF EXISTS evaluator_results_append_only ON evaluator_results;
        DROP TRIGGER IF EXISTS evaluator_attempts_append_only ON evaluator_attempts;
        DROP TRIGGER IF EXISTS evaluator_runs_append_only ON evaluator_runs;
        DROP TABLE IF EXISTS evaluator_shadow_comparisons;
        DROP TABLE IF EXISTS evaluator_results;
        DROP TABLE IF EXISTS evaluator_attempts;
        DROP TABLE IF EXISTS evaluator_runs;
        """
    )
