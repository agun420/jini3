from __future__ import annotations

import json
from typing import Any, Protocol

from .canonical import canonical_sha256
from .models import (
    BrokerOrderCommand,
    BrokerOrderSnapshot,
    ExecutionEvent,
    ExecutionRequest,
    ExecutionResult,
    ReconciliationReport,
)


class ExecutionRepository(Protocol):
    def save_request(self, request: ExecutionRequest) -> None: ...
    def save_command(self, command: BrokerOrderCommand) -> None: ...
    def get_command_by_client_order_id(self, client_order_id: str) -> BrokerOrderCommand | None: ...
    def get_request(self, execution_id: str) -> ExecutionRequest | None: ...
    def save_snapshot(self, execution_id: str, snapshot: BrokerOrderSnapshot) -> None: ...
    def append_event(self, event: ExecutionEvent) -> None: ...
    def next_event_sequence(self, execution_id: str) -> int: ...
    def list_events(self, execution_id: str) -> tuple[ExecutionEvent, ...]: ...
    def save_result(self, result: ExecutionResult) -> None: ...
    def save_reconciliation(self, report: ReconciliationReport) -> None: ...
    def claim_trade_update(self, event_id: str, execution_id: str, raw_event_hash: str) -> bool: ...


class MemoryExecutionRepository:
    def __init__(self) -> None:
        self.requests: dict[str, ExecutionRequest] = {}
        self.commands: dict[str, BrokerOrderCommand] = {}
        self.snapshots: dict[str, BrokerOrderSnapshot] = {}
        self.events: dict[str, list[ExecutionEvent]] = {}
        self.results: dict[str, ExecutionResult] = {}
        self.reconciliations: dict[str, ReconciliationReport] = {}
        self.trade_update_ids: dict[str, tuple[str, str]] = {}

    def save_request(self, request: ExecutionRequest) -> None:
        existing = self.requests.get(request.execution_id)
        if existing is not None and existing != request:
            raise RuntimeError("execution request identity collision")
        self.requests.setdefault(request.execution_id, request)

    def save_command(self, command: BrokerOrderCommand) -> None:
        existing = self.commands.get(command.client_order_id)
        if existing is not None and existing != command:
            raise RuntimeError("client_order_id command collision")
        self.commands.setdefault(command.client_order_id, command)

    def get_command_by_client_order_id(self, client_order_id: str) -> BrokerOrderCommand | None:
        return self.commands.get(client_order_id)

    def get_request(self, execution_id: str) -> ExecutionRequest | None:
        return self.requests.get(execution_id)

    def save_snapshot(self, execution_id: str, snapshot: BrokerOrderSnapshot) -> None:
        self.snapshots.setdefault(snapshot.snapshot_id, snapshot)

    def append_event(self, event: ExecutionEvent) -> None:
        items = self.events.setdefault(event.execution_id, [])
        if items and event.event_sequence != items[-1].event_sequence + 1:
            raise RuntimeError("execution event sequence is not contiguous")
        if not items and event.event_sequence != 1:
            raise RuntimeError("first execution event sequence must be one")
        items.append(event)

    def next_event_sequence(self, execution_id: str) -> int:
        return len(self.events.get(execution_id, [])) + 1

    def list_events(self, execution_id: str) -> tuple[ExecutionEvent, ...]:
        return tuple(self.events.get(execution_id, []))

    def save_result(self, result: ExecutionResult) -> None:
        existing = self.results.get(result.result_id)
        if existing is not None and existing != result:
            raise RuntimeError("execution result identity collision")
        self.results.setdefault(result.result_id, result)

    def save_reconciliation(self, report: ReconciliationReport) -> None:
        self.reconciliations.setdefault(report.report_id, report)

    def claim_trade_update(self, event_id: str, execution_id: str, raw_event_hash: str) -> bool:
        existing = self.trade_update_ids.get(event_id)
        if existing is not None:
            if existing != (execution_id, raw_event_hash):
                raise RuntimeError("trade update identity collision")
            return False
        self.trade_update_ids[event_id] = (execution_id, raw_event_hash)
        return True


class NullExecutionRepository(MemoryExecutionRepository):
    pass


class PostgresExecutionRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://")

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install project-daybreak[recorder] for PostgreSQL support") from exc
        return psycopg.connect(self._dsn)

    def save_request(self, request: ExecutionRequest) -> None:
        request_hash = canonical_sha256(request)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_requests (
                    execution_id, run_id, trading_date, ticker, requested_at,
                    submission_cutoff_timestamp, risk_decision_id, configuration_hash,
                    request_hash, request_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (execution_id) DO NOTHING
                RETURNING request_hash
                """,
                (
                    request.execution_id,
                    request.run_id,
                    request.trading_date,
                    request.risk_decision.ticker,
                    request.requested_at,
                    request.submission_cutoff_timestamp,
                    request.risk_decision.decision_id,
                    request.configuration_hash,
                    request_hash,
                    json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
            inserted = cur.fetchone()
            if inserted is None:
                cur.execute(
                    "SELECT request_hash FROM execution_requests WHERE execution_id=%s",
                    (request.execution_id,),
                )
                existing = cur.fetchone()
                if existing is None or existing[0] != request_hash:
                    raise RuntimeError("execution request identity collision")

    def save_command(self, command: BrokerOrderCommand) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_order_commands (
                    command_id, execution_id, client_order_id, symbol, quantity, side,
                    order_type, time_in_force, order_class, command_hash, command_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (command_id) DO NOTHING
                RETURNING command_hash
                """,
                (
                    command.command_id,
                    command.execution_id,
                    command.client_order_id,
                    command.symbol,
                    command.quantity,
                    command.side.value,
                    command.order_type.value,
                    command.time_in_force.value,
                    command.order_class.value,
                    command.command_hash,
                    json.dumps(command.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
            inserted = cur.fetchone()
            if inserted is None:
                cur.execute(
                    "SELECT command_hash FROM execution_order_commands WHERE command_id=%s",
                    (command.command_id,),
                )
                existing = cur.fetchone()
                if existing is None or existing[0] != command.command_hash:
                    raise RuntimeError("execution command identity collision")

    def get_command_by_client_order_id(self, client_order_id: str) -> BrokerOrderCommand | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT command_json FROM execution_order_commands WHERE client_order_id=%s",
                (client_order_id,),
            )
            row = cur.fetchone()
        return None if row is None else BrokerOrderCommand.model_validate(row[0])

    def get_request(self, execution_id: str) -> ExecutionRequest | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT request_json FROM execution_requests WHERE execution_id=%s", (execution_id,)
            )
            row = cur.fetchone()
        return None if row is None else ExecutionRequest.model_validate(row[0])

    def save_snapshot(self, execution_id: str, snapshot: BrokerOrderSnapshot) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_broker_snapshots (
                    snapshot_id, execution_id, broker_order_id, client_order_id,
                    status, filled_quantity, observed_at, raw_response_hash, snapshot_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (snapshot_id) DO NOTHING
                """,
                (
                    snapshot.snapshot_id,
                    execution_id,
                    snapshot.broker_order_id,
                    snapshot.client_order_id,
                    snapshot.status.value,
                    snapshot.filled_quantity,
                    snapshot.updated_at,
                    snapshot.raw_response_hash,
                    json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def append_event(self, event: ExecutionEvent) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_events (
                    execution_id, event_sequence, event_type, event_timestamp,
                    broker_order_id, client_order_id, status, event_hash, event_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    event.execution_id,
                    event.event_sequence,
                    event.event_type.value,
                    event.event_timestamp,
                    event.broker_order_id,
                    event.client_order_id,
                    event.status,
                    event.event_hash,
                    json.dumps(event.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def next_event_sequence(self, execution_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(event_sequence),0)+1 "
                "FROM execution_events WHERE execution_id=%s",
                (execution_id,),
            )
            row = cur.fetchone()
        return int(row[0])

    def list_events(self, execution_id: str) -> tuple[ExecutionEvent, ...]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT event_json FROM execution_events "
                "WHERE execution_id=%s ORDER BY event_sequence",
                (execution_id,),
            )
            rows = cur.fetchall()
        return tuple(ExecutionEvent.model_validate(row[0]) for row in rows)

    def save_result(self, result: ExecutionResult) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_results (
                    result_id, execution_id, outcome, reconciliation_required,
                    completed_at, request_hash, result_hash, result_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (result_id) DO NOTHING
                """,
                (
                    result.result_id,
                    result.execution_id,
                    result.outcome.value,
                    result.reconciliation_required,
                    result.completed_at,
                    result.request_hash,
                    result.result_hash,
                    json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                ),
            )

    def claim_trade_update(self, event_id: str, execution_id: str, raw_event_hash: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_trade_updates (event_id, execution_id, raw_event_hash)
                VALUES (%s,%s,%s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                (event_id, execution_id, raw_event_hash),
            )
            inserted = cur.fetchone() is not None
            if not inserted:
                cur.execute(
                    "SELECT execution_id, raw_event_hash "
                    "FROM execution_trade_updates WHERE event_id=%s",
                    (event_id,),
                )
                row = cur.fetchone()
                if row is None or row[0] != execution_id or row[1] != raw_event_hash:
                    raise RuntimeError("trade update identity collision")
            return inserted

    def save_reconciliation(self, report: ReconciliationReport) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO execution_reconciliation_reports (
                    report_id, execution_id, client_order_id, checked_at,
                    matched, report_hash, report_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (report_id) DO NOTHING
                """,
                (
                    report.report_id,
                    report.execution_id,
                    report.client_order_id,
                    report.checked_at,
                    report.matched,
                    report.report_hash,
                    json.dumps(report.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
