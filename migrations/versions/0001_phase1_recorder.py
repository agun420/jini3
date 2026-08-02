"""Phase 1 append-only recorder schema.

Revision ID: 0001_phase1_recorder
Revises: None
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op

revision = "0001_phase1_recorder"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE ingest_sessions (
            ingest_session_id UUID PRIMARY KEY,
            trading_date DATE NOT NULL,
            scheduled_start TIMESTAMPTZ NOT NULL,
            scheduled_stop TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            ended_at TIMESTAMPTZ,
            status TEXT NOT NULL CHECK (status IN (
                'starting', 'running', 'stopping', 'completed',
                'completed_partial', 'failed', 'skipped_non_trading_day'
            )),
            configuration_hash CHAR(64) NOT NULL
                CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
            host_name TEXT NOT NULL,
            process_id INTEGER NOT NULL CHECK (process_id > 0),
            alpaca_feed TEXT NOT NULL CHECK (alpaca_feed = 'sip'),
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (scheduled_stop > scheduled_start),
            CHECK (ended_at IS NULL OR ended_at >= started_at)
        );

        CREATE TABLE subscription_manifests (
            manifest_id UUID PRIMARY KEY,
            ingest_session_id UUID NOT NULL
                REFERENCES ingest_sessions(ingest_session_id),
            version INTEGER NOT NULL CHECK (version >= 1),
            effective_at TIMESTAMPTZ NOT NULL,
            feed TEXT NOT NULL CHECK (feed = 'sip'),
            manifest JSONB NOT NULL,
            configuration_hash CHAR(64) NOT NULL
                CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (ingest_session_id, version)
        );

        CREATE TABLE raw_events (
            ingest_seq BIGSERIAL PRIMARY KEY,
            event_id UUID NOT NULL UNIQUE,
            ingest_session_id UUID NOT NULL
                REFERENCES ingest_sessions(ingest_session_id),
            connection_id UUID NOT NULL,
            source TEXT NOT NULL CHECK (source IN (
                'alpaca_sip', 'alpaca_news', 'alpaca_trading',
                'sec_edgar', 'system'
            )),
            channel TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'trade', 'quote', 'minute_bar', 'updated_bar',
                'daily_bar', 'trading_status', 'trade_cancel',
                'trade_correction', 'news', 'trade_update',
                'sec_submissions_snapshot', 'sec_submission',
                'stream_connected',
                'stream_disconnected', 'subscription_manifest',
                'heartbeat', 'error'
            )),
            symbol TEXT,
            symbols TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            provider_event_id TEXT,
            event_timestamp TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            trading_date DATE NOT NULL,
            sequence_hint BIGINT CHECK (sequence_hint IS NULL OR sequence_hint >= 0),
            payload JSONB NOT NULL,
            payload_sha256 CHAR(64) NOT NULL
                CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
            idempotency_key CHAR(64) NOT NULL UNIQUE
                CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
            schema_version TEXT NOT NULL CHECK (schema_version = 'raw_event_v1'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (symbol IS NULL OR symbol = ANY(symbols))
        );

        CREATE INDEX raw_events_session_seq_idx
            ON raw_events (ingest_session_id, ingest_seq);
        CREATE INDEX raw_events_symbol_time_idx
            ON raw_events (symbol, event_timestamp, ingest_seq)
            WHERE symbol IS NOT NULL;
        CREATE INDEX raw_events_type_time_idx
            ON raw_events (event_type, event_timestamp, ingest_seq);
        CREATE INDEX raw_events_provider_id_idx
            ON raw_events (source, provider_event_id)
            WHERE provider_event_id IS NOT NULL;
        CREATE INDEX raw_events_symbols_gin_idx
            ON raw_events USING GIN (symbols);
        CREATE INDEX raw_events_received_at_idx
            ON raw_events (received_at, ingest_seq);

        CREATE TABLE raw_ingest_failures (
            failure_seq BIGSERIAL PRIMARY KEY,
            failure_id UUID NOT NULL UNIQUE,
            ingest_session_id UUID NOT NULL
                REFERENCES ingest_sessions(ingest_session_id),
            connection_id UUID,
            source TEXT NOT NULL CHECK (source IN (
                'alpaca_sip', 'alpaca_news', 'alpaca_trading',
                'sec_edgar', 'system'
            )),
            channel TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            error_type TEXT NOT NULL,
            error_message TEXT NOT NULL,
            raw_payload JSONB,
            raw_payload_sha256 CHAR(64)
                CHECK (raw_payload_sha256 IS NULL OR raw_payload_sha256 ~ '^[0-9a-f]{64}$'),
            schema_version TEXT NOT NULL
                CHECK (schema_version = 'raw_ingest_failure_v1'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (raw_payload IS NULL AND raw_payload_sha256 IS NULL)
                OR
                (raw_payload IS NOT NULL AND raw_payload_sha256 IS NOT NULL)
            )
        );

        CREATE INDEX raw_ingest_failures_session_idx
            ON raw_ingest_failures (ingest_session_id, failure_seq);

        CREATE TABLE sec_seen_accessions (
            cik CHAR(10) NOT NULL CHECK (cik ~ '^[0-9]{10}$'),
            accession_number TEXT NOT NULL,
            first_seen_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (cik, accession_number)
        );

        CREATE OR REPLACE FUNCTION daybreak_validate_session_update()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.ingest_session_id IS DISTINCT FROM OLD.ingest_session_id
               OR NEW.trading_date IS DISTINCT FROM OLD.trading_date
               OR NEW.scheduled_start IS DISTINCT FROM OLD.scheduled_start
               OR NEW.scheduled_stop IS DISTINCT FROM OLD.scheduled_stop
               OR NEW.started_at IS DISTINCT FROM OLD.started_at
               OR NEW.configuration_hash IS DISTINCT FROM OLD.configuration_hash
               OR NEW.host_name IS DISTINCT FROM OLD.host_name
               OR NEW.process_id IS DISTINCT FROM OLD.process_id
               OR NEW.alpaca_feed IS DISTINCT FROM OLD.alpaca_feed
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'Daybreak ingest-session identity fields are immutable';
            END IF;

            IF OLD.status IN ('completed', 'completed_partial', 'failed', 'skipped_non_trading_day') THEN
                RAISE EXCEPTION 'Daybreak terminal ingest sessions cannot be modified';
            END IF;

            IF OLD.status IN ('starting', 'running')
               AND NEW.status NOT IN ('stopping', 'completed', 'completed_partial', 'failed') THEN
                RAISE EXCEPTION 'Invalid Daybreak ingest-session transition';
            END IF;

            IF OLD.status = 'stopping'
               AND NEW.status NOT IN ('completed', 'completed_partial', 'failed') THEN
                RAISE EXCEPTION 'Invalid Daybreak ingest-session transition';
            END IF;

            IF NEW.status IN ('completed', 'completed_partial', 'failed') AND NEW.ended_at IS NULL THEN
                RAISE EXCEPTION 'Terminal Daybreak ingest sessions require ended_at';
            END IF;

            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER ingest_sessions_lifecycle_guard
            BEFORE UPDATE ON ingest_sessions
            FOR EACH ROW EXECUTE FUNCTION daybreak_validate_session_update();

        CREATE OR REPLACE FUNCTION daybreak_forbid_mutation()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'Daybreak raw audit tables are append-only';
        END;
        $$;

        CREATE TRIGGER raw_events_append_only
            BEFORE UPDATE OR DELETE ON raw_events
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();

        CREATE TRIGGER raw_ingest_failures_append_only
            BEFORE UPDATE OR DELETE ON raw_ingest_failures
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();

        CREATE TRIGGER subscription_manifests_append_only
            BEFORE UPDATE OR DELETE ON subscription_manifests
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();

        CREATE TRIGGER sec_seen_accessions_append_only
            BEFORE UPDATE OR DELETE ON sec_seen_accessions
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        r"""
        DROP TRIGGER IF EXISTS ingest_sessions_lifecycle_guard ON ingest_sessions;
        DROP TRIGGER IF EXISTS sec_seen_accessions_append_only ON sec_seen_accessions;
        DROP TRIGGER IF EXISTS subscription_manifests_append_only ON subscription_manifests;
        DROP TRIGGER IF EXISTS raw_ingest_failures_append_only ON raw_ingest_failures;
        DROP TRIGGER IF EXISTS raw_events_append_only ON raw_events;
        DROP FUNCTION IF EXISTS daybreak_forbid_mutation();
        DROP FUNCTION IF EXISTS daybreak_validate_session_update();
        DROP TABLE IF EXISTS sec_seen_accessions;
        DROP TABLE IF EXISTS raw_ingest_failures;
        DROP TABLE IF EXISTS raw_events;
        DROP TABLE IF EXISTS subscription_manifests;
        DROP TABLE IF EXISTS ingest_sessions;
        """
    )
