from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel

from .models import (
    BuildAttestation,
    ConfigurationFreeze,
    EvidenceManifest,
    ProductionCandidateReport,
)


class ReleaseRepository(Protocol):
    def save_evidence_manifest(self, value: EvidenceManifest) -> None: ...
    def save_build_attestation(self, value: BuildAttestation) -> None: ...
    def save_configuration_freeze(self, value: ConfigurationFreeze) -> None: ...
    def save_candidate_report(self, value: ProductionCandidateReport) -> None: ...


class MemoryReleaseRepository:
    def __init__(self) -> None:
        self.evidence_manifests: dict[str, EvidenceManifest] = {}
        self.build_attestations: dict[str, BuildAttestation] = {}
        self.configuration_freezes: dict[str, ConfigurationFreeze] = {}
        self.candidate_reports: dict[str, ProductionCandidateReport] = {}

    def save_evidence_manifest(self, value: EvidenceManifest) -> None:
        self.evidence_manifests.setdefault(value.manifest_hash, value)

    def save_build_attestation(self, value: BuildAttestation) -> None:
        self.build_attestations.setdefault(value.attestation_hash, value)

    def save_configuration_freeze(self, value: ConfigurationFreeze) -> None:
        self.configuration_freezes.setdefault(value.freeze_hash, value)

    def save_candidate_report(self, value: ProductionCandidateReport) -> None:
        self.candidate_reports.setdefault(value.report_id, value)


class PostgresReleaseRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _insert(self, table: str, id_column: str, identifier: str, value: BaseModel) -> None:
        import psycopg
        from psycopg import sql

        payload = json.dumps(value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        normalized = self.dsn.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(normalized) as connection, connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {table} ({id_column}, payload) "
                    "VALUES (%s, %s::jsonb) "
                    "ON CONFLICT ({id_column}) DO NOTHING"
                ).format(
                    table=sql.Identifier(table),
                    id_column=sql.Identifier(id_column),
                ),
                (identifier, payload),
            )

    def save_evidence_manifest(self, value: EvidenceManifest) -> None:
        self._insert("release_evidence_manifests", "manifest_hash", value.manifest_hash, value)

    def save_build_attestation(self, value: BuildAttestation) -> None:
        self._insert(
            "release_build_attestations", "attestation_hash", value.attestation_hash, value
        )

    def save_configuration_freeze(self, value: ConfigurationFreeze) -> None:
        self._insert("release_configuration_freezes", "freeze_hash", value.freeze_hash, value)

    def save_candidate_report(self, value: ProductionCandidateReport) -> None:
        self._insert("release_candidate_reports", "report_id", value.report_id, value)
