from __future__ import annotations

import json
from typing import Any, Protocol

from .canonical import canonical_sha256
from .models import RiskDecision, RiskReservation, SizingRequest


class RiskRepository(Protocol):
    def save_request(self, request: SizingRequest) -> None: ...
    def save_decision(self, decision: RiskDecision) -> None: ...
    def reserve(self, decision: RiskDecision) -> None: ...


class NullRiskRepository:
    def save_request(self, request: SizingRequest) -> None:
        return None

    def save_decision(self, decision: RiskDecision) -> None:
        return None

    def reserve(self, decision: RiskDecision) -> None:
        return None


class MemoryRiskRepository:
    def __init__(self) -> None:
        self.requests: dict[str, SizingRequest] = {}
        self.decisions: dict[str, RiskDecision] = {}
        self.reservations: dict[str, RiskReservation] = {}

    def save_request(self, request: SizingRequest) -> None:
        existing = self.requests.get(request.request_id)
        if existing is not None and existing != request:
            raise RuntimeError("risk sizing request identity collision")
        self.requests.setdefault(request.request_id, request)

    def save_decision(self, decision: RiskDecision) -> None:
        existing = self.decisions.get(decision.decision_id)
        if existing is not None and existing != decision:
            raise RuntimeError("risk decision identity collision")
        self.decisions.setdefault(decision.decision_id, decision)

    def reserve(self, decision: RiskDecision) -> None:
        self.save_decision(decision)
        if decision.reservation is None:
            return
        existing = self.reservations.get(decision.reservation.reservation_id)
        if existing is not None and existing != decision.reservation:
            raise RuntimeError("risk reservation identity collision")
        if any(
            item.client_order_id == decision.reservation.client_order_id
            and item.reservation_id != decision.reservation.reservation_id
            for item in self.reservations.values()
        ):
            raise RuntimeError("duplicate client_order_id reservation")
        self.reservations[decision.reservation.reservation_id] = decision.reservation


class PostgresRiskRepository:
    """Synchronous append-only repository with atomic decision/reservation commit."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+psycopg://", "postgresql://")

    def _connect(self) -> Any:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install project-daybreak[recorder] for PostgreSQL support") from exc
        return psycopg.connect(self._dsn)

    def save_request(self, request: SizingRequest) -> None:
        input_hash = canonical_sha256(request)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO risk_sizing_requests (
                    request_id, run_id, trading_date, ticker, final_rank, calculated_at,
                    configuration_hash, input_hash, request_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (request_id) DO NOTHING
                RETURNING input_hash
                """,
                (
                    request.request_id,
                    request.run_id,
                    request.trading_date,
                    request.setup.ticker,
                    request.final_rank,
                    request.calculated_at,
                    request.configuration_hash,
                    input_hash,
                    json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
            inserted = cur.fetchone()
            if inserted is None:
                cur.execute(
                    "SELECT input_hash FROM risk_sizing_requests WHERE request_id=%s",
                    (request.request_id,),
                )
                existing = cur.fetchone()
                if existing is None or existing[0] != input_hash:
                    raise RuntimeError("risk sizing request identity collision")

    def save_decision(self, decision: RiskDecision) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            self._insert_decision(cur, decision)

    def reserve(self, decision: RiskDecision) -> None:
        if decision.reservation is None:
            self.save_decision(decision)
            return
        with self._connect() as conn, conn.cursor() as cur:
            self._insert_decision(cur, decision)
            reservation = decision.reservation
            cur.execute(
                """
                INSERT INTO risk_reservations (
                    reservation_id, decision_id, request_id, run_id, trading_date, ticker,
                    client_order_id, reserved_quantity, reserved_notional,
                    reserved_modeled_risk, created_at, expires_at, initial_status,
                    reservation_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (reservation_id) DO NOTHING
                """,
                (
                    reservation.reservation_id,
                    decision.decision_id,
                    reservation.request_id,
                    reservation.run_id,
                    reservation.trading_date,
                    reservation.ticker,
                    reservation.client_order_id,
                    reservation.reserved_quantity,
                    reservation.reserved_notional,
                    reservation.reserved_modeled_risk,
                    reservation.created_at,
                    reservation.expires_at,
                    reservation.status.value,
                    json.dumps(reservation.model_dump(mode="json"), ensure_ascii=False),
                ),
            )
            cur.execute(
                """
                INSERT INTO risk_reservation_events (
                    reservation_id, event_sequence, status, event_timestamp, event_json
                ) VALUES (%s,1,%s,%s,%s::jsonb)
                ON CONFLICT (reservation_id, event_sequence) DO NOTHING
                """,
                (
                    reservation.reservation_id,
                    reservation.status.value,
                    reservation.created_at,
                    json.dumps(
                        {
                            "status": reservation.status.value,
                            "event_timestamp": reservation.created_at.isoformat(),
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

    @staticmethod
    def _insert_decision(cur: Any, decision: RiskDecision) -> None:
        cur.execute(
            """
            INSERT INTO risk_sizing_decisions (
                decision_id, request_id, run_id, trading_date, ticker, final_rank, decision,
                kill_switch_required, final_quantity, binding_cap, input_hash,
                decision_hash, decision_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT (decision_id) DO NOTHING
            RETURNING decision_hash
            """,
            (
                decision.decision_id,
                decision.request_id,
                decision.run_id,
                decision.trading_date,
                decision.ticker,
                decision.final_rank,
                decision.decision.value,
                decision.kill_switch_required,
                decision.final_quantity,
                None if decision.binding_cap is None else decision.binding_cap.value,
                decision.input_hash,
                decision.decision_hash,
                json.dumps(decision.model_dump(mode="json"), ensure_ascii=False),
            ),
        )
        inserted = cur.fetchone()
        if inserted is None:
            cur.execute(
                "SELECT decision_hash FROM risk_sizing_decisions WHERE decision_id=%s",
                (decision.decision_id,),
            )
            existing = cur.fetchone()
            if existing is None or existing[0] != decision.decision_hash:
                raise RuntimeError("risk decision identity collision")
