from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel

from .models import (
    AcceptanceReport,
    AlertRecord,
    FlattenResult,
    KillSwitchState,
    PhaseRecord,
    SessionPlan,
    SessionResult,
)


class OrchestrationRepository(Protocol):
    def save_plan(self, plan: SessionPlan) -> None: ...
    def append_phase(self, record: PhaseRecord) -> None: ...
    def save_kill_switch(self, state: KillSwitchState) -> None: ...
    def get_latest_kill_switch(self, session_id: str) -> KillSwitchState | None: ...
    def save_alert(self, alert: AlertRecord) -> None: ...
    def save_flatten(self, result: FlattenResult) -> None: ...
    def save_result(self, result: SessionResult) -> None: ...
    def save_acceptance(self, report: AcceptanceReport) -> None: ...
    def list_phases(self, session_id: str) -> tuple[PhaseRecord, ...]: ...
    def list_alerts(self, session_id: str) -> tuple[AlertRecord, ...]: ...


class MemoryOrchestrationRepository:
    def __init__(self) -> None:
        self.plans: dict[str, SessionPlan] = {}
        self.phases: dict[str, list[PhaseRecord]] = {}
        self.kill_switches: dict[str, KillSwitchState] = {}
        self.alerts: dict[str, list[AlertRecord]] = {}
        self.flattens: dict[str, FlattenResult] = {}
        self.results: dict[str, SessionResult] = {}
        self.acceptance: dict[str, AcceptanceReport] = {}

    def save_plan(self, plan: SessionPlan) -> None:
        existing = self.plans.get(plan.session_id)
        if existing is not None and existing != plan:
            raise RuntimeError("session plan identity collision")
        self.plans.setdefault(plan.session_id, plan)

    def append_phase(self, record: PhaseRecord) -> None:
        items = self.phases.setdefault(record.session_id, [])
        if items and record.sequence != items[-1].sequence + 1:
            raise RuntimeError("phase sequence is not contiguous")
        if not items and record.sequence != 1:
            raise RuntimeError("first phase sequence must be one")
        items.append(record)

    def save_kill_switch(self, state: KillSwitchState) -> None:
        existing = self.kill_switches.get(state.state_hash)
        if existing is not None and existing != state:
            raise RuntimeError("kill-switch state collision")
        self.kill_switches[state.state_hash] = state

    def get_latest_kill_switch(self, session_id: str) -> KillSwitchState | None:
        matches = [state for state in self.kill_switches.values() if state.session_id == session_id]
        return matches[-1] if matches else None

    def save_alert(self, alert: AlertRecord) -> None:
        items = self.alerts.setdefault(alert.session_id, [])
        if all(existing.alert_id != alert.alert_id for existing in items):
            items.append(alert)

    def save_flatten(self, result: FlattenResult) -> None:
        self.flattens.setdefault(result.flatten_id, result)

    def save_result(self, result: SessionResult) -> None:
        self.results.setdefault(result.result_hash, result)

    def save_acceptance(self, report: AcceptanceReport) -> None:
        self.acceptance.setdefault(report.report_id, report)

    def list_phases(self, session_id: str) -> tuple[PhaseRecord, ...]:
        return tuple(self.phases.get(session_id, []))

    def list_alerts(self, session_id: str) -> tuple[AlertRecord, ...]:
        return tuple(self.alerts.get(session_id, []))


class PostgresOrchestrationRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://")

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install project-daybreak[recorder] for PostgreSQL support") from exc
        return psycopg.connect(self._dsn)

    @staticmethod
    def _dump(model: BaseModel) -> str:
        return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)

    def save_plan(self, plan: SessionPlan) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestration_sessions (
                    session_id, run_id, trading_date, configuration_hash, plan_json
                ) VALUES (%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (session_id) DO NOTHING
                """,
                (
                    plan.session_id,
                    plan.run_id,
                    plan.trading_date,
                    plan.configuration_hash,
                    self._dump(plan),
                ),
            )

    def append_phase(self, record: PhaseRecord) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestration_phase_records (
                    session_id, sequence, phase, status, started_at, ended_at,
                    record_hash, record_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    record.session_id,
                    record.sequence,
                    record.phase.value,
                    record.status.value,
                    record.started_at,
                    record.ended_at,
                    record.record_hash,
                    self._dump(record),
                ),
            )

    def save_kill_switch(self, state: KillSwitchState) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestration_kill_switch_events (
                    state_hash, session_id, active, activated_at, reason, state_json
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (state_hash) DO NOTHING
                """,
                (
                    state.state_hash,
                    state.session_id,
                    state.active,
                    state.activated_at,
                    None if state.reason is None else state.reason.value,
                    self._dump(state),
                ),
            )

    def get_latest_kill_switch(self, session_id: str) -> KillSwitchState | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT state_json
                FROM orchestration_kill_switch_events
                WHERE session_id=%s
                ORDER BY created_at DESC, state_hash DESC
                LIMIT 1
                """,
                (session_id,),
            )
            row = cur.fetchone()
        return None if row is None else KillSwitchState.model_validate(row[0])

    def save_alert(self, alert: AlertRecord) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestration_alerts (
                    alert_id, session_id, severity, code, created_at,
                    dedup_key, alert_hash, alert_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (alert_id) DO NOTHING
                """,
                (
                    alert.alert_id,
                    alert.session_id,
                    alert.severity.value,
                    alert.code,
                    alert.created_at,
                    alert.dedup_key,
                    alert.alert_hash,
                    self._dump(alert),
                ),
            )

    def save_flatten(self, result: FlattenResult) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestration_flatten_results (
                    flatten_id, session_id, started_at, completed_at, complete,
                    result_hash, result_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (flatten_id) DO NOTHING
                """,
                (
                    result.flatten_id,
                    result.session_id,
                    result.started_at,
                    result.completed_at,
                    result.complete,
                    result.result_hash,
                    self._dump(result),
                ),
            )

    def save_result(self, result: SessionResult) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestration_session_results (
                    result_hash, session_id, outcome, completed_at, final_phase, result_json
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (result_hash) DO NOTHING
                """,
                (
                    result.result_hash,
                    result.session_id,
                    result.outcome.value,
                    result.completed_at,
                    result.final_phase.value,
                    self._dump(result),
                ),
            )

    def save_acceptance(self, report: AcceptanceReport) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestration_acceptance_reports (
                    report_id, generated_at, online_verified, paper_ready, configuration_hash,
                    report_hash, report_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (report_id) DO NOTHING
                """,
                (
                    report.report_id,
                    report.generated_at,
                    report.online_verified,
                    report.paper_ready,
                    report.configuration_hash,
                    report.report_hash,
                    self._dump(report),
                ),
            )

    def list_phases(self, session_id: str) -> tuple[PhaseRecord, ...]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT record_json FROM orchestration_phase_records "
                "WHERE session_id=%s ORDER BY sequence",
                (session_id,),
            )
            rows = cur.fetchall()
        return tuple(PhaseRecord.model_validate(row[0]) for row in rows)

    def list_alerts(self, session_id: str) -> tuple[AlertRecord, ...]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT alert_json FROM orchestration_alerts "
                "WHERE session_id=%s ORDER BY created_at",
                (session_id,),
            )
            rows = cur.fetchall()
        return tuple(AlertRecord.model_validate(row[0]) for row in rows)
