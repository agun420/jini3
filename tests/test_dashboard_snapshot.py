from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from daybreak.dashboard_snapshot import DashboardSnapshotSources, build_dashboard_snapshot
from daybreak_analytics.acceptance import build_paper_acceptance_ledger
from daybreak_analytics.analytics import analyze_session
from daybreak_analytics.models import AnalyticsPolicy, PaperAcceptanceRequest
from daybreak_evaluator.models import (
    EvaluatorPolicy,
    RunStatus,
)
from daybreak_evaluator.persistence import MemoryEvaluatorRepository
from daybreak_evaluator.service import EvaluatorService
from daybreak_execution.alpaca import normalize_order
from daybreak_execution.canonical import canonical_sha256 as execution_sha256
from daybreak_execution.models import BrokerPositionSnapshot
from daybreak_operations.enums import DrillType
from daybreak_operations.observability import build_observability_snapshot
from daybreak_orchestration.canonical import canonical_sha256 as orchestration_sha256
from daybreak_orchestration.enums import AlertSeverity, PhaseStatus, SessionPhase
from daybreak_orchestration.kill_switch import activate_kill_switch, inactive_kill_switch
from daybreak_orchestration.models import AlertRecord, PhaseRecord
from daybreak_release.review import review_production_candidate
from tests.analytics.helpers import H, make_replay, make_session
from tests.release.helpers import make_request as make_release_request

ROOT = Path(__file__).resolve().parent


def test_empty_sources_still_produce_a_schema_shaped_dict() -> None:
    sources = DashboardSnapshotSources(session_id="s-1", trading_date=date(2026, 8, 3))
    snapshot = build_dashboard_snapshot(sources, generated_at=datetime(2026, 8, 3, tzinfo=UTC))

    assert snapshot["schema_version"] == "1.0"
    assert snapshot["data_mode"] == "local"
    assert snapshot["environment"] == "paper"
    assert snapshot["public_safe"] is False
    assert snapshot["safety"]["live_capital_eligible"] is False
    assert snapshot["safety"]["paper_only"] is True
    assert snapshot["safety"]["kill_switch_active"] is False
    assert snapshot["safety"]["all_positions_flat"] is True
    assert snapshot["session"]["session_id"] == "s-1"
    assert snapshot["session"]["state"] == "unknown"
    assert snapshot["signals"] == []
    assert snapshot["positions"] == []
    assert snapshot["orders"] == []
    assert snapshot["services"] == []
    assert snapshot["qualification"] == {"status": "unavailable", "items": [], "blockers": []}
    assert snapshot["release"]["status"] == "unavailable"
    assert snapshot["release"]["live_capital_eligible"] is False
    assert snapshot["alerts"] == []
    # every section required by dashboard.schema.json's additionalProperties:false object
    # is present as a plain dict, never a leftover dataclass/pydantic instance
    for key in (
        "system",
        "safety",
        "account",
        "session",
        "performance",
        "qualification",
        "release",
    ):
        assert isinstance(snapshot[key], dict)


def test_kill_switch_active_is_surfaced() -> None:
    active = activate_kill_switch(
        "s-1",
        __import__(
            "daybreak_orchestration.enums", fromlist=["KillSwitchReason"]
        ).KillSwitchReason.MANUAL,
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )
    sources = DashboardSnapshotSources(
        session_id="s-1", trading_date=date(2026, 8, 3), kill_switch=active
    )
    snapshot = build_dashboard_snapshot(sources)
    assert snapshot["safety"]["kill_switch_active"] is True

    inactive = inactive_kill_switch("s-1")
    sources2 = DashboardSnapshotSources(
        session_id="s-1", trading_date=date(2026, 8, 3), kill_switch=inactive
    )
    assert build_dashboard_snapshot(sources2)["safety"]["kill_switch_active"] is False


def test_phases_and_alerts_populate_session_and_alerts() -> None:
    started = datetime(2026, 8, 3, 13, 0, tzinfo=UTC)
    phase_core = {
        "session_id": "s-1",
        "sequence": 1,
        "phase": SessionPhase.EXECUTION,
        "status": PhaseStatus.STARTED,
        "started_at": started,
        "ended_at": None,
        "details": {},
    }
    phase = PhaseRecord.model_validate(
        {**phase_core, "record_hash": orchestration_sha256(phase_core)}
    )
    alert_core = {
        "alert_id": "alert-00000001",
        "session_id": "s-1",
        "severity": AlertSeverity.WARNING,
        "code": "LATENCY_HIGH",
        "message": "Shadow evaluator latency above baseline.",
        "created_at": started + timedelta(minutes=5),
        "dedup_key": "latency-high",
        "details": {},
    }
    alert = AlertRecord.model_validate(
        {**alert_core, "alert_hash": orchestration_sha256(alert_core)}
    )

    sources = DashboardSnapshotSources(
        session_id="s-1", trading_date=date(2026, 8, 3), phases=(phase,), alerts=(alert,)
    )
    snapshot = build_dashboard_snapshot(sources)
    assert snapshot["session"]["state"] == "execution"
    assert snapshot["session"]["state_detail"] == "started"
    assert snapshot["session"]["started_at"] == "2026-08-03T13:00:00Z"
    assert len(snapshot["alerts"]) == 1
    assert snapshot["alerts"][0]["severity"] == "warning"
    assert snapshot["alerts"][0]["title"] == "LATENCY_HIGH"
    assert snapshot["alerts"][0]["message"] == "Shadow evaluator latency above baseline."


@pytest.mark.asyncio
async def test_signals_positions_and_account_join_across_evaluator_risk_and_broker() -> None:
    from tests.evaluator.test_service import make_request, provider
    from tests.risk.helpers import approved_setup, sizing_request

    request = make_request()

    class QueueTransport:
        def __init__(self, values):
            self.values = list(values)

        async def create(self, **kwargs):
            return self.values.pop(0)

    transport = QueueTransport(
        [
            provider(
                "approved_output.json",
                request.requested_at + timedelta(seconds=1),
                model="gpt-5.6-terra",
            )
        ]
    )
    repo = MemoryEvaluatorRepository()
    counter = iter([f"id-{n}" for n in range(10)])
    service = EvaluatorService(
        transport=transport,
        spec_path=str(ROOT.parent / "docs/spec/Project_Daybreak_v6.3_Final.md"),
        repository=repo,
        policy=EvaluatorPolicy(max_attempts=1),
        id_factory=lambda: next(counter),
    )
    run_result = await service.evaluate_primary(request)
    assert run_result.status == RunStatus.PRIMARY_VALID
    assert run_result.output is not None
    assert [item.ticker for item in run_result.output.approved_setups] == ["AAAA", "BBBB", "CCCC"]

    # A risk decision for the top-ranked approved ticker, reusing the same fixture setup.
    decision = None
    from daybreak_risk.engine import size_position

    sizing = sizing_request(setup=approved_setup())
    decision = size_position(sizing)
    assert decision.reservation is not None

    order_row = {
        "id": "alpaca-1",
        "client_order_id": decision.reservation.client_order_id,
        "symbol": "AAAA",
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "order_class": "bracket",
        "status": "filled",
        "qty": str(decision.final_quantity),
        "filled_qty": str(decision.final_quantity),
        "limit_price": str(decision.planned_entry_limit),
        "submitted_at": "2026-08-03T13:30:01Z",
        "updated_at": "2026-08-03T13:30:05Z",
        "legs": [],
    }
    order = normalize_order(order_row)

    position = BrokerPositionSnapshot(
        symbol="AAAA",
        quantity=Decimal(str(decision.final_quantity)),
        average_entry_price=decision.planned_entry_limit,
        observed_at=datetime(2026, 8, 3, 13, 31, tzinfo=UTC),
        raw_response_hash=execution_sha256({"symbol": "AAAA"}),
    )

    sources = DashboardSnapshotSources(
        session_id="s-1",
        trading_date=date(2026, 8, 3),
        run_result=run_result,
        decisions=(decision,),
        positions=(position,),
        orders=(order,),
        account={"equity": "50500.00", "last_equity": "50000.00", "buying_power": "20000.00"},
    )
    snapshot = build_dashboard_snapshot(sources)

    approved_signal = next(item for item in snapshot["signals"] if item["ticker"] == "AAAA")
    assert approved_signal["status"] == "approved"
    assert approved_signal["rank"] == decision.final_rank
    assert approved_signal["entry_price"] == float(decision.planned_entry_limit)
    assert approved_signal["stop_price"] == float(decision.stop_price)
    assert approved_signal["execution_status"] == "filled"

    qualified_signal = next(item for item in snapshot["signals"] if item["ticker"] == "DDDD")
    assert qualified_signal["status"] == "qualified"
    excluded_signal = next(item for item in snapshot["signals"] if item["ticker"] == "EEEE")
    assert excluded_signal["status"] == "excluded"

    position_out = snapshot["positions"][0]
    assert position_out["ticker"] == "AAAA"
    assert position_out["side"] == "long"
    assert position_out["stop_price"] == float(decision.stop_price)

    order_out = snapshot["orders"][0]
    assert order_out["client_order_id"] == decision.reservation.client_order_id
    assert order_out["status"] == "filled"

    assert snapshot["session"]["orders_submitted"] == 1
    assert snapshot["session"]["orders_filled"] == 1
    assert snapshot["session"]["approved_setup_count"] == 3
    assert snapshot["session"]["qualified_setup_count"] == 1
    assert snapshot["session"]["excluded_ticker_count"] == 1

    assert snapshot["account"]["equity"] == 50500.0
    assert snapshot["account"]["daily_pnl"] == pytest.approx(500.0)
    assert snapshot["account"]["open_risk"] == float(decision.reserved_modeled_risk)
    assert snapshot["safety"]["all_positions_flat"] is False


def test_performance_and_qualification_from_real_analytics_objects() -> None:
    session = make_session()
    performance = analyze_session(session)

    sessions = tuple(make_session(index=i) for i in range(2))
    reports = tuple(make_replay(item) for item in sessions)
    ledger = build_paper_acceptance_ledger(
        PaperAcceptanceRequest(
            generated_at=datetime(2026, 8, 1, tzinfo=UTC),
            policy=AnalyticsPolicy(
                minimum_sessions=2,
                minimum_filled_orders=4,
                minimum_clean_session_rate=Decimal("1"),
                required_drill_count=2,
            ),
            sessions=sessions,
            replay_reports=reports,
            target_acceptance_verified=True,
            restore_validation_verified=True,
            passed_drills=(DrillType.DATABASE_DISCONNECT, DrillType.PROCESS_RESTART),
            configuration_hash=H,
        )
    )

    sources = DashboardSnapshotSources(
        session_id=session.session_id,
        trading_date=date(2026, 8, 3),
        session_performance=performance,
        paper_ledger=ledger,
    )
    snapshot = build_dashboard_snapshot(sources)

    assert snapshot["performance"]["summary"]["trade_count"] == performance.trade_count
    assert snapshot["performance"]["summary"]["net_pnl"] == float(performance.net_pnl)
    assert len(snapshot["performance"]["attributions"]) == len(performance.attributions)
    assert snapshot["performance"]["equity_curve"] == []

    assert snapshot["qualification"]["status"] == ledger.status.value
    keys = {item["key"] for item in snapshot["qualification"]["items"]}
    assert keys == {"sessions", "clean_sessions", "filled_orders"}
    filled = next(
        item for item in snapshot["qualification"]["items"] if item["key"] == "filled_orders"
    )
    assert filled["current"] == ledger.filled_order_count
    assert filled["target"] == 4


def test_release_from_real_review_output() -> None:
    request = make_release_request()
    report = review_production_candidate(request)
    sources = DashboardSnapshotSources(
        session_id="s-1",
        trading_date=date(2026, 8, 3),
        candidate_report=report,
        build_attestation=request.build_attestation,
    )
    snapshot = build_dashboard_snapshot(sources)
    assert snapshot["release"]["status"] == report.status.value
    assert snapshot["release"]["release_version"] == "1.0.2"
    assert snapshot["release"]["tests_passed"] == request.build_attestation.tests_passed
    assert snapshot["release"]["schema_count"] == request.build_attestation.schema_count
    assert snapshot["release"]["live_capital_eligible"] is False
    assert snapshot["release"]["report_hash"] == report.report_hash


def test_observability_maps_to_a_single_aggregate_service() -> None:
    healthy = build_observability_snapshot(
        metrics={
            "heartbeat_gap_seconds": 2,
            "free_disk_bytes": 9_000_000_000,
            "file_descriptor_limit": 8192,
        },
        configuration_hash="a" * 64,
        observed_at=datetime(2026, 8, 3, 13, 0, tzinfo=UTC),
    )
    sources = DashboardSnapshotSources(
        session_id="s-1", trading_date=date(2026, 8, 3), observability=healthy
    )
    snapshot = build_dashboard_snapshot(sources)
    assert len(snapshot["services"]) == 1
    assert snapshot["services"][0]["status"] == "healthy"
