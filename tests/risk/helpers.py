from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from daybreak_contracts.output_models import ApprovedSetup
from daybreak_risk.models import (
    AccountSnapshot,
    LiquiditySnapshot,
    QuoteSnapshot,
    RiskPolicyConfig,
    SessionRiskState,
    SizingRequest,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def approved_setup(*, risk_flags: tuple[str, ...] = ()) -> ApprovedSetup:
    raw = json.loads((FIXTURES / "approved_output.json").read_text(encoding="utf-8"))
    setup = ApprovedSetup.model_validate_json(json.dumps(raw["approved_setups"][0]))
    trade_parameters = setup.trade_parameters.model_copy(update={"premarket_low_used": 19.20})
    return setup.model_copy(update={"risk_flags": risk_flags, "trade_parameters": trade_parameters})


def sizing_request(
    *,
    policy: RiskPolicyConfig | None = None,
    setup: ApprovedSetup | None = None,
    now: datetime | None = None,
) -> SizingRequest:
    now = now or datetime(2026, 8, 3, 13, 30, 0, 500000, tzinfo=UTC)
    return SizingRequest(
        request_id="request-1",
        run_id="run-1",
        trading_date=now.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date(),
        final_rank=1,
        calculated_at=now,
        execution_cutoff_timestamp=now + timedelta(seconds=30),
        setup=setup or approved_setup(),
        policy=policy or RiskPolicyConfig.paper_v1(),
        account=AccountSnapshot(
            snapshot_timestamp=now - timedelta(milliseconds=200),
            status="ACTIVE",
            account_blocked=False,
            trading_blocked=False,
            trade_suspended_by_user=False,
            equity=Decimal("50000"),
            last_equity=Decimal("50000"),
            cash=Decimal("20000"),
            buying_power=Decimal("20000"),
            non_marginable_buying_power=Decimal("20000"),
            regt_buying_power=Decimal("20000"),
            initial_margin=Decimal("0"),
            maintenance_margin=Decimal("0"),
            long_market_value=Decimal("0"),
            multiplier=Decimal("1"),
            pending_transfer_in=Decimal("0"),
            pending_transfer_out=Decimal("0"),
        ),
        quote=QuoteSnapshot(
            quote_timestamp=now - timedelta(milliseconds=100),
            last_trade_timestamp=now - timedelta(milliseconds=80),
            bid_price=Decimal("20.04"),
            ask_price=Decimal("20.06"),
            bid_size=500,
            ask_size=500,
            last_price=Decimal("20.05"),
            first_regular_session_nbbo_confirmed=True,
        ),
        liquidity=LiquiditySnapshot(
            premarket_volume=1_000_000,
            adv20_shares=5_000_000,
            asset_tradable=True,
            asset_fractionable=False,
            asset_marginable=False,
            asset_status="active",
        ),
        session=SessionRiskState(
            session_reference_equity=Decimal("50000"),
            session_start_equity=Decimal("50000"),
            net_external_cash_flow=Decimal("0"),
            internal_realized_pnl=Decimal("0"),
            internal_unrealized_pnl=Decimal("0"),
        ),
        planned_entry_limit=Decimal("20.06"),
        tick_size=Decimal("0.01"),
        market_status_normal=True,
        symbol_halted=False,
        configuration_hash="a" * 64,
    )
