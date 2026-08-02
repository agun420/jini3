"""Phase 9 production-candidate review and release evidence.

Revision ID: 0009_phase9_release
Revises: 0008_phase8_analytics
Create Date: 2026-08-01
"""
from __future__ import annotations

from alembic import op

revision = "0009_phase9_release"
down_revision = "0008_phase8_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
    CREATE TABLE release_evidence_manifests (
        manifest_hash TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE release_build_attestations (
        attestation_hash TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE release_configuration_freezes (
        freeze_hash TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE release_candidate_reports (
        report_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE OR REPLACE FUNCTION daybreak_forbid_release_mutation()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Daybreak release evidence tables are append-only'; END;
    $$;
    CREATE TRIGGER release_manifest_append_only BEFORE UPDATE OR DELETE ON release_evidence_manifests FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_release_mutation();
    CREATE TRIGGER release_build_append_only BEFORE UPDATE OR DELETE ON release_build_attestations FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_release_mutation();
    CREATE TRIGGER release_freeze_append_only BEFORE UPDATE OR DELETE ON release_configuration_freezes FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_release_mutation();
    CREATE TRIGGER release_report_append_only BEFORE UPDATE OR DELETE ON release_candidate_reports FOR EACH ROW EXECUTE FUNCTION daybreak_forbid_release_mutation();
    """)


def downgrade() -> None:
    op.execute(r"""
    DROP TRIGGER IF EXISTS release_report_append_only ON release_candidate_reports;
    DROP TRIGGER IF EXISTS release_freeze_append_only ON release_configuration_freezes;
    DROP TRIGGER IF EXISTS release_build_append_only ON release_build_attestations;
    DROP TRIGGER IF EXISTS release_manifest_append_only ON release_evidence_manifests;
    DROP FUNCTION IF EXISTS daybreak_forbid_release_mutation();
    DROP TABLE IF EXISTS release_candidate_reports;
    DROP TABLE IF EXISTS release_configuration_freezes;
    DROP TABLE IF EXISTS release_build_attestations;
    DROP TABLE IF EXISTS release_evidence_manifests;
    """)
