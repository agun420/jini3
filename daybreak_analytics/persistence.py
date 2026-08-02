from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel

from .models import (
    DeploymentEvidenceReport,
    FullSessionReplayReport,
    PaperAcceptanceLedger,
    SessionPerformance,
)


class AnalyticsRepository(Protocol):
    def save_session_performance(self, value: SessionPerformance) -> None: ...
    def save_replay_report(self, value: FullSessionReplayReport) -> None: ...
    def save_paper_ledger(self, value: PaperAcceptanceLedger) -> None: ...
    def save_deployment_report(self, value: DeploymentEvidenceReport) -> None: ...


class MemoryAnalyticsRepository:
    def __init__(self) -> None:
        self.session_performance: dict[str, SessionPerformance] = {}
        self.replay_reports: dict[str, FullSessionReplayReport] = {}
        self.paper_ledgers: dict[str, PaperAcceptanceLedger] = {}
        self.deployment_reports: dict[str, DeploymentEvidenceReport] = {}

    def save_session_performance(self, value: SessionPerformance) -> None:
        self.session_performance.setdefault(value.analytics_id, value)

    def save_replay_report(self, value: FullSessionReplayReport) -> None:
        self.replay_reports.setdefault(value.replay_id, value)

    def save_paper_ledger(self, value: PaperAcceptanceLedger) -> None:
        self.paper_ledgers.setdefault(value.ledger_id, value)

    def save_deployment_report(self, value: DeploymentEvidenceReport) -> None:
        self.deployment_reports.setdefault(value.report_id, value)


class PostgresAnalyticsRepository:
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

    def save_session_performance(self, value: SessionPerformance) -> None:
        self._insert("analytics_session_performance", "analytics_id", value.analytics_id, value)

    def save_replay_report(self, value: FullSessionReplayReport) -> None:
        self._insert("analytics_replay_reports", "replay_id", value.replay_id, value)

    def save_paper_ledger(self, value: PaperAcceptanceLedger) -> None:
        self._insert("analytics_paper_acceptance_ledgers", "ledger_id", value.ledger_id, value)

    def save_deployment_report(self, value: DeploymentEvidenceReport) -> None:
        self._insert("analytics_deployment_evidence", "report_id", value.report_id, value)
