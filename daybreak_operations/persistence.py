from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel

from .models import (
    BackupManifest,
    DrillResult,
    ObservabilitySnapshot,
    RecoveryPlan,
    RestoreValidation,
    TargetAcceptanceReport,
)


class OperationsRepository(Protocol):
    def save_observability(self, value: ObservabilitySnapshot) -> None: ...
    def save_recovery(self, value: RecoveryPlan) -> None: ...
    def save_backup(self, value: BackupManifest) -> None: ...
    def save_restore(self, value: RestoreValidation) -> None: ...
    def save_drill(self, value: DrillResult) -> None: ...
    def save_acceptance(self, value: TargetAcceptanceReport) -> None: ...


class MemoryOperationsRepository:
    def __init__(self) -> None:
        self.observability: dict[str, ObservabilitySnapshot] = {}
        self.recovery: dict[str, RecoveryPlan] = {}
        self.backups: dict[str, BackupManifest] = {}
        self.restores: dict[str, RestoreValidation] = {}
        self.drills: dict[str, DrillResult] = {}
        self.acceptance: dict[str, TargetAcceptanceReport] = {}

    def save_observability(self, value: ObservabilitySnapshot) -> None:
        self.observability.setdefault(value.snapshot_id, value)

    def save_recovery(self, value: RecoveryPlan) -> None:
        self.recovery.setdefault(value.plan_id, value)

    def save_backup(self, value: BackupManifest) -> None:
        self.backups.setdefault(value.backup_id, value)

    def save_restore(self, value: RestoreValidation) -> None:
        self.restores.setdefault(value.validation_id, value)

    def save_drill(self, value: DrillResult) -> None:
        self.drills.setdefault(value.drill_id, value)

    def save_acceptance(self, value: TargetAcceptanceReport) -> None:
        self.acceptance.setdefault(value.report_id, value)


class PostgresOperationsRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn.replace("postgresql+psycopg://", "postgresql://")

    def _insert(self, table: str, id_column: str, identifier: str, value: BaseModel) -> None:
        import psycopg
        from psycopg import sql

        payload = json.dumps(value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        with psycopg.connect(self.dsn) as connection, connection.cursor() as cursor:
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

    def save_observability(self, value: ObservabilitySnapshot) -> None:
        self._insert("operations_observability_snapshots", "snapshot_id", value.snapshot_id, value)

    def save_recovery(self, value: RecoveryPlan) -> None:
        self._insert("operations_recovery_plans", "plan_id", value.plan_id, value)

    def save_backup(self, value: BackupManifest) -> None:
        self._insert("operations_backup_manifests", "backup_id", value.backup_id, value)

    def save_restore(self, value: RestoreValidation) -> None:
        self._insert("operations_restore_validations", "validation_id", value.validation_id, value)

    def save_drill(self, value: DrillResult) -> None:
        self._insert("operations_drill_results", "drill_id", value.drill_id, value)

    def save_acceptance(self, value: TargetAcceptanceReport) -> None:
        self._insert("operations_acceptance_reports", "report_id", value.report_id, value)
