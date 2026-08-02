"""Phase 2 immutable feature contexts and snapshots.

Revision ID: 0002_phase2_features
Revises: 0001_phase1_recorder
Create Date: 2026-08-01
"""

from __future__ import annotations

from alembic import op

revision = "0002_phase2_features"
down_revision = "0001_phase1_recorder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE feature_contexts (
            context_hash CHAR(64) PRIMARY KEY
                CHECK (context_hash ~ '^[0-9a-f]{64}$'),
            trading_date DATE NOT NULL,
            evaluation_timestamp TIMESTAMPTZ NOT NULL,
            payload_timestamp TIMESTAMPTZ NOT NULL,
            context_json JSONB NOT NULL,
            engine_version TEXT NOT NULL CHECK (engine_version = 'daily_features_v1'),
            configuration_hash CHAR(64) NOT NULL
                CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (evaluation_timestamp >= payload_timestamp)
        );

        CREATE INDEX feature_contexts_trading_date_idx
            ON feature_contexts (trading_date, payload_timestamp);

        CREATE TABLE feature_snapshots (
            snapshot_id CHAR(64) PRIMARY KEY
                CHECK (snapshot_id ~ '^[0-9a-f]{64}$'),
            context_hash CHAR(64) NOT NULL
                REFERENCES feature_contexts(context_hash),
            trading_date DATE NOT NULL,
            payload_timestamp TIMESTAMPTZ NOT NULL,
            payload_hash CHAR(64) NOT NULL
                CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
            feature_hash CHAR(64) NOT NULL
                CHECK (feature_hash ~ '^[0-9a-f]{64}$'),
            audit_hash CHAR(64) NOT NULL
                CHECK (audit_hash ~ '^[0-9a-f]{64}$'),
            configuration_hash CHAR(64) NOT NULL
                CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
            snapshot_json JSONB NOT NULL,
            payload_json JSONB NOT NULL,
            module_manifest JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (context_hash, payload_hash, feature_hash, audit_hash, configuration_hash)
        );

        CREATE INDEX feature_snapshots_trading_date_idx
            ON feature_snapshots (trading_date, payload_timestamp);
        CREATE INDEX feature_snapshots_payload_hash_idx
            ON feature_snapshots (payload_hash);
        CREATE INDEX feature_snapshots_context_hash_idx
            ON feature_snapshots (context_hash);

        CREATE TRIGGER feature_contexts_append_only
            BEFORE UPDATE OR DELETE ON feature_contexts
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();

        CREATE TRIGGER feature_snapshots_append_only
            BEFORE UPDATE OR DELETE ON feature_snapshots
            FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        r"""
        DROP TRIGGER IF EXISTS feature_snapshots_append_only ON feature_snapshots;
        DROP TRIGGER IF EXISTS feature_contexts_append_only ON feature_contexts;
        DROP TABLE IF EXISTS feature_snapshots;
        DROP TABLE IF EXISTS feature_contexts;
        """
    )
