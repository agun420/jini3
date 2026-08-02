from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal

from daybreak_contracts.enums import RiskFlag

from .canonical import canonical_sha256
from .enums import BindingCap, RiskDecisionStatus, RiskRejectionCode
from .models import (
    AccountSnapshot,
    BatchSizingRequest,
    BatchSizingResult,
    QuantityCaps,
    RiskDecision,
    RiskReservation,
    SessionRiskState,
    SizingRequest,
)
from .rounding import (
    floor_to_cent,
    floor_to_int,
    quantize_money,
    round_down_to_increment,
    round_up_to_increment,
)

_BINDING_ORDER: tuple[tuple[BindingCap, str], ...] = (
    (BindingCap.TRADE_RISK, "trade_risk"),
    (BindingCap.OPEN_RISK, "open_risk"),
    (BindingCap.DAILY_LOSS, "daily_loss"),
    (BindingCap.BUYING_POWER, "buying_power"),
    (BindingCap.POSITION_NOTIONAL, "position_notional"),
    (BindingCap.GROSS_EXPOSURE, "gross_exposure"),
    (BindingCap.ADV_LIQUIDITY, "adv_liquidity"),
    (BindingCap.PREMARKET_LIQUIDITY, "premarket_liquidity"),
)

_RISK_FLAG_MULTIPLIERS: dict[RiskFlag, Decimal] = {
    RiskFlag.PARABOLIC: Decimal("0.50"),
    RiskFlag.LOW_FLOAT: Decimal("0.50"),
    RiskFlag.SPIKY_VOLUME: Decimal("0.60"),
    RiskFlag.SECONDARY_SOURCE: Decimal("0.75"),
    RiskFlag.HARD_TO_BORROW: Decimal("1.00"),
    RiskFlag.UNKNOWN_BORROW: Decimal("1.00"),
}


def _unique_reasons(reasons: Iterable[RiskRejectionCode]) -> tuple[RiskRejectionCode, ...]:
    result: list[RiskRejectionCode] = []
    seen: set[RiskRejectionCode] = set()
    for reason in reasons:
        if reason not in seen:
            result.append(reason)
            seen.add(reason)
    return tuple(result)


def _finalize_decision(base: dict[str, object]) -> RiskDecision:
    """Hash the normalized decision shape, then run the full integrity validators."""
    draft = RiskDecision.model_construct(**base)  # type: ignore[arg-type]
    body = draft.model_dump(mode="python", exclude={"decision_hash"})
    base["decision_hash"] = canonical_sha256(body)
    return RiskDecision.model_validate(base)


def _rejected(
    request: SizingRequest,
    reasons: Iterable[RiskRejectionCode],
    *,
    kill_switch_required: bool = False,
    calculations: dict[str, object] | None = None,
) -> RiskDecision:
    fields = calculations or {}
    input_hash = canonical_sha256(request)
    base = {
        "decision_id": f"risk-{request.request_id}",
        "request_id": request.request_id,
        "run_id": request.run_id,
        "trading_date": request.trading_date,
        "policy_version": request.policy.policy_version,
        "profile_name": request.policy.profile_name,
        "ticker": request.setup.ticker,
        "final_rank": request.final_rank,
        "decision": RiskDecisionStatus.REJECTED,
        "rejection_reasons": _unique_reasons(reasons),
        "kill_switch_required": kill_switch_required,
        "session_reference_equity": fields.get("session_reference_equity"),
        "broker_session_pnl": fields.get("broker_session_pnl"),
        "internal_session_pnl": fields.get("internal_session_pnl"),
        "risk_session_pnl": fields.get("risk_session_pnl"),
        "usable_buying_power": fields.get("usable_buying_power"),
        "base_trade_risk_budget": fields.get("base_trade_risk_budget"),
        "risk_flag_multiplier": fields.get("risk_flag_multiplier"),
        "adjusted_trade_risk_budget": fields.get("adjusted_trade_risk_budget"),
        "planned_entry_limit": fields.get("planned_entry_limit"),
        "stop_price": fields.get("stop_price"),
        "target_price": fields.get("target_price"),
        "structural_risk_per_share": fields.get("structural_risk_per_share"),
        "execution_risk_buffer": fields.get("execution_risk_buffer"),
        "modeled_risk_per_share": fields.get("modeled_risk_per_share"),
        "maximum_total_open_risk": fields.get("maximum_total_open_risk"),
        "remaining_open_risk_capacity": fields.get("remaining_open_risk_capacity"),
        "remaining_hard_loss_capacity": fields.get("remaining_hard_loss_capacity"),
        "maximum_position_notional": fields.get("maximum_position_notional"),
        "remaining_gross_exposure": fields.get("remaining_gross_exposure"),
        "quantity_caps": None,
        "binding_cap": None,
        "final_quantity": 0,
        "reserved_modeled_risk": None,
        "reserved_notional": None,
        "reservation": None,
        "calculated_at": request.calculated_at,
        "account_snapshot_timestamp": request.account.snapshot_timestamp,
        "quote_timestamp": request.quote.quote_timestamp,
        "configuration_hash": request.configuration_hash,
        "input_hash": input_hash,
        "decision_hash": "0" * 64,
    }
    return _finalize_decision(base)


def initialize_session_state(account: AccountSnapshot) -> SessionRiskState:
    """Create the frozen opening risk state from a normalized account snapshot."""
    reference_equity = min(account.equity, account.last_equity)
    if reference_equity <= 0 or account.equity <= 0:
        raise ValueError("account equity must be positive to initialize risk state")
    return SessionRiskState(
        session_reference_equity=reference_equity,
        session_start_equity=account.equity,
        current_long_market_value=max(Decimal("0"), account.long_market_value),
    )


def size_position(request: SizingRequest) -> RiskDecision:
    policy = request.policy
    reasons: list[RiskRejectionCode] = []
    calculations: dict[str, object] = {}
    kill_switch_required = False

    account_age_ms = int(
        (request.calculated_at - request.account.snapshot_timestamp).total_seconds() * 1000
    )
    quote_age_ms = int(
        (request.calculated_at - request.quote.quote_timestamp).total_seconds() * 1000
    )
    last_trade_age_ms = int(
        (request.calculated_at - request.quote.last_trade_timestamp).total_seconds() * 1000
    )

    if request.account.status != "ACTIVE":
        reasons.append(RiskRejectionCode.ACCOUNT_NOT_ACTIVE)
    if request.account.account_blocked:
        reasons.append(RiskRejectionCode.ACCOUNT_BLOCKED)
    if request.account.trading_blocked:
        reasons.append(RiskRejectionCode.TRADING_BLOCKED)
    if request.account.trade_suspended_by_user:
        reasons.append(RiskRejectionCode.TRADE_SUSPENDED_BY_USER)
    if account_age_ms < 0 or account_age_ms > policy.max_account_snapshot_age_ms:
        reasons.append(RiskRejectionCode.ACCOUNT_SNAPSHOT_STALE)

    account_values = (
        request.account.equity,
        request.account.last_equity,
        request.account.buying_power,
        request.account.non_marginable_buying_power,
        request.account.maintenance_margin,
    )
    if (
        request.account.equity <= 0
        or request.account.last_equity <= 0
        or any(value < 0 for value in account_values[2:])
    ):
        reasons.append(RiskRejectionCode.INVALID_ACCOUNT_VALUE)
    if request.account.pending_transfer_out > 0:
        reasons.append(RiskRejectionCode.PENDING_TRANSFER_OUT)
    if not request.session.account_state_reconciled:
        reasons.append(RiskRejectionCode.ACCOUNT_STATE_UNRECONCILED)
    if not request.session.streams_healthy:
        reasons.append(RiskRejectionCode.STREAM_HEALTH_FAILURE)
    if not request.session.database_healthy:
        reasons.append(RiskRejectionCode.DATABASE_HEALTH_FAILURE)
    if request.session.kill_switch_active:
        reasons.append(RiskRejectionCode.KILL_SWITCH_ACTIVE)
        kill_switch_required = True
    if not request.market_status_normal:
        reasons.append(RiskRejectionCode.MARKET_NOT_NORMAL)
    if request.symbol_halted:
        reasons.append(RiskRejectionCode.SYMBOL_HALTED)
    if request.calculated_at > request.execution_cutoff_timestamp:
        reasons.append(RiskRejectionCode.EXECUTION_CUTOFF_EXCEEDED)
    if quote_age_ms < 0 or quote_age_ms > policy.max_quote_age_ms:
        reasons.append(RiskRejectionCode.QUOTE_SNAPSHOT_STALE)
    if last_trade_age_ms < 0 or last_trade_age_ms > policy.max_last_trade_age_ms:
        reasons.append(RiskRejectionCode.LAST_TRADE_STALE)

    quote = request.quote
    if (
        quote.bid_price <= 0
        or quote.ask_price <= 0
        or quote.ask_price < quote.bid_price
        or quote.last_price <= 0
        or quote.bid_size <= 0
        or quote.ask_size <= 0
    ):
        reasons.append(RiskRejectionCode.INVALID_QUOTE)
    if not quote.first_regular_session_nbbo_confirmed:
        reasons.append(RiskRejectionCode.REGULAR_SESSION_NBBO_NOT_CONFIRMED)

    if not request.liquidity.asset_tradable or request.liquidity.asset_status.lower() != "active":
        reasons.append(RiskRejectionCode.INVALID_LIQUIDITY_INPUT)

    session_reference_equity = request.session.session_reference_equity
    calculations["session_reference_equity"] = session_reference_equity

    broker_session_pnl = (
        request.account.equity
        - request.session.session_start_equity
        - request.session.net_external_cash_flow
    )
    internal_session_pnl = (
        request.session.internal_realized_pnl + request.session.internal_unrealized_pnl
    )
    risk_session_pnl = min(broker_session_pnl, internal_session_pnl)
    calculations.update(
        broker_session_pnl=broker_session_pnl,
        internal_session_pnl=internal_session_pnl,
        risk_session_pnl=risk_session_pnl,
    )
    if abs(broker_session_pnl - internal_session_pnl) > policy.pnl_reconciliation_tolerance:
        reasons.append(RiskRejectionCode.SESSION_PNL_RECONCILIATION_FAILURE)

    soft_daily_loss_limit = floor_to_cent(session_reference_equity * policy.soft_daily_loss_pct)
    hard_daily_loss_limit = floor_to_cent(session_reference_equity * policy.hard_daily_loss_pct)
    if risk_session_pnl <= -hard_daily_loss_limit:
        reasons.append(RiskRejectionCode.HARD_DAILY_LOSS_LIMIT)
        kill_switch_required = True
    elif risk_session_pnl <= -soft_daily_loss_limit:
        reasons.append(RiskRejectionCode.SOFT_DAILY_LOSS_LIMIT)

    if request.session.consecutive_closed_losses >= policy.max_consecutive_losses:
        reasons.append(RiskRejectionCode.MAX_CONSECUTIVE_LOSSES)
    if request.session.completed_entry_count >= policy.max_new_entries_per_day:
        reasons.append(RiskRejectionCode.MAX_NEW_ENTRIES_PER_DAY)
    if request.setup.ticker in request.session.traded_tickers_today:
        reasons.append(RiskRejectionCode.DUPLICATE_TICKER_DAY)
    if (
        request.session.open_daybreak_position_count + request.session.reserved_entry_position_count
        >= policy.max_concurrent_positions
    ):
        reasons.append(RiskRejectionCode.MAX_CONCURRENT_POSITIONS)

    usable_buying_power = floor_to_cent(
        min(
            request.account.non_marginable_buying_power,
            request.account.buying_power,
        )
        * (Decimal("1") - policy.buying_power_reserve_pct)
        - request.session.reserved_entry_notional
    )
    calculations["usable_buying_power"] = usable_buying_power

    reference_price = quantize_money(Decimal(str(request.setup.trade_parameters.reference_price)))
    atr = quantize_money(Decimal(str(request.setup.trade_parameters.atr_value_used)))
    premarket_low = quantize_money(Decimal(str(request.setup.trade_parameters.premarket_low_used)))
    planned_entry_limit = round_up_to_increment(request.planned_entry_limit, request.tick_size)
    stop_price = round_down_to_increment(
        reference_price - Decimal(str(request.setup.trade_parameters.risk_stop_atr_multiple)) * atr,
        request.tick_size,
    )
    target_price = round_down_to_increment(
        reference_price
        + Decimal(str(request.setup.trade_parameters.profit_target_atr_multiple)) * atr,
        request.tick_size,
    )
    calculations.update(
        planned_entry_limit=planned_entry_limit,
        stop_price=stop_price,
        target_price=target_price,
    )

    if planned_entry_limit < quote.ask_price:
        reasons.append(RiskRejectionCode.ENTRY_LIMIT_NOT_MARKETABLE)
    if stop_price <= 0 or target_price <= planned_entry_limit or planned_entry_limit <= stop_price:
        reasons.append(RiskRejectionCode.INVALID_PRICE_GEOMETRY)
    if stop_price > premarket_low:
        reasons.append(RiskRejectionCode.STOP_ABOVE_PREMARKET_LOW)
    if min(quote.last_price, quote.bid_price) < premarket_low:
        reasons.append(RiskRejectionCode.PREMARKET_LOW_BROKEN)

    spread = quote.spread
    spread_pct = spread / quote.midpoint if quote.midpoint > 0 else Decimal("999")
    spread_atr_fraction = spread / atr if atr > 0 else Decimal("999")
    if spread_pct > policy.max_spread_pct or spread_atr_fraction > policy.max_spread_atr_fraction:
        reasons.append(RiskRejectionCode.SPREAD_TOO_WIDE)

    entry_drift = abs(planned_entry_limit - reference_price)
    entry_drift_pct = entry_drift / reference_price if reference_price > 0 else Decimal("999")
    entry_drift_atr = entry_drift / atr if atr > 0 else Decimal("999")
    if (
        entry_drift_pct > policy.max_entry_drift_pct
        or entry_drift_atr > policy.max_entry_drift_atr_multiple
    ):
        reasons.append(RiskRejectionCode.ENTRY_PRICE_DRIFT_TOO_LARGE)

    structural_risk_per_share = quantize_money(planned_entry_limit - stop_price)
    atr_buffer = quantize_money(policy.slippage_buffer_atr_multiple * atr)
    spread_buffer = quantize_money(policy.slippage_buffer_spread_multiple * spread)
    execution_risk_buffer = quantize_money(max(atr_buffer, spread_buffer))
    modeled_risk_per_share = quantize_money(structural_risk_per_share + execution_risk_buffer)
    calculations.update(
        structural_risk_per_share=structural_risk_per_share,
        execution_risk_buffer=execution_risk_buffer,
        modeled_risk_per_share=modeled_risk_per_share,
    )
    if structural_risk_per_share <= 0 or modeled_risk_per_share <= 0:
        reasons.append(RiskRejectionCode.INVALID_PRICE_GEOMETRY)

    base_trade_risk_budget = floor_to_cent(session_reference_equity * policy.risk_per_trade_pct)
    multipliers = [
        _RISK_FLAG_MULTIPLIERS.get(flag, Decimal("1.00")) for flag in request.setup.risk_flags
    ]
    risk_flag_multiplier = min(multipliers, default=Decimal("1.00"))
    adjusted_trade_risk_budget = floor_to_cent(base_trade_risk_budget * risk_flag_multiplier)
    calculations.update(
        base_trade_risk_budget=base_trade_risk_budget,
        risk_flag_multiplier=risk_flag_multiplier,
        adjusted_trade_risk_budget=adjusted_trade_risk_budget,
    )

    maximum_total_open_risk = floor_to_cent(session_reference_equity * policy.max_open_risk_pct)
    remaining_open_risk_capacity = floor_to_cent(
        maximum_total_open_risk - request.session.current_total_open_risk
    )
    current_loss = max(Decimal("0"), -risk_session_pnl)
    remaining_hard_loss_capacity = floor_to_cent(
        hard_daily_loss_limit - current_loss - request.session.current_total_open_risk
    )
    maximum_position_notional = floor_to_cent(
        session_reference_equity * policy.max_position_notional_pct
    )
    maximum_gross_long_exposure = floor_to_cent(
        session_reference_equity * policy.max_gross_long_exposure_pct
    )
    current_and_reserved_gross = (
        request.session.current_long_market_value + request.session.reserved_entry_notional
    )
    remaining_gross_exposure = floor_to_cent(
        maximum_gross_long_exposure - current_and_reserved_gross
    )
    calculations.update(
        maximum_total_open_risk=maximum_total_open_risk,
        remaining_open_risk_capacity=remaining_open_risk_capacity,
        remaining_hard_loss_capacity=remaining_hard_loss_capacity,
        maximum_position_notional=maximum_position_notional,
        remaining_gross_exposure=remaining_gross_exposure,
    )

    if usable_buying_power <= 0:
        reasons.append(RiskRejectionCode.NO_BUYING_POWER_CAPACITY)
    if remaining_open_risk_capacity <= 0:
        reasons.append(RiskRejectionCode.NO_OPEN_RISK_CAPACITY)
    if remaining_hard_loss_capacity <= 0:
        reasons.append(RiskRejectionCode.NO_DAILY_LOSS_CAPACITY)
    if remaining_gross_exposure <= 0:
        reasons.append(RiskRejectionCode.NO_GROSS_EXPOSURE_CAPACITY)

    if reasons:
        return _rejected(
            request,
            reasons,
            kill_switch_required=kill_switch_required,
            calculations=calculations,
        )

    caps = QuantityCaps(
        trade_risk=floor_to_int(adjusted_trade_risk_budget / modeled_risk_per_share),
        open_risk=floor_to_int(remaining_open_risk_capacity / modeled_risk_per_share),
        daily_loss=floor_to_int(remaining_hard_loss_capacity / modeled_risk_per_share),
        buying_power=floor_to_int(usable_buying_power / planned_entry_limit),
        position_notional=floor_to_int(maximum_position_notional / planned_entry_limit),
        gross_exposure=floor_to_int(remaining_gross_exposure / planned_entry_limit),
        adv_liquidity=floor_to_int(Decimal(request.liquidity.adv20_shares) * policy.max_pct_adv20),
        premarket_liquidity=floor_to_int(
            Decimal(request.liquidity.premarket_volume) * policy.max_pct_premarket_volume
        ),
    )
    cap_values = caps.model_dump(mode="python")
    final_quantity = min(cap_values.values())
    if final_quantity < policy.minimum_quantity:
        return _rejected(
            request,
            [RiskRejectionCode.FINAL_QUANTITY_BELOW_MINIMUM],
            calculations=calculations,
        )

    binding_cap = next(cap for cap, field in _BINDING_ORDER if cap_values[field] == final_quantity)
    reserved_modeled_risk = quantize_money(modeled_risk_per_share * final_quantity)
    reserved_notional = quantize_money(planned_entry_limit * final_quantity)
    input_hash = canonical_sha256(request)
    reservation = RiskReservation(
        reservation_id=f"reservation-{request.request_id}",
        request_id=request.request_id,
        run_id=request.run_id,
        trading_date=request.trading_date,
        ticker=request.setup.ticker,
        client_order_id=(
            f"DB-{request.trading_date.strftime('%Y%m%d')}-"
            f"{canonical_sha256(request.run_id)[:16]}-{request.setup.ticker}"
        ),
        reserved_quantity=final_quantity,
        reserved_notional=reserved_notional,
        reserved_modeled_risk=reserved_modeled_risk,
        created_at=request.calculated_at,
        expires_at=request.calculated_at + timedelta(minutes=2),
    )
    base = {
        "decision_id": f"risk-{request.request_id}",
        "request_id": request.request_id,
        "run_id": request.run_id,
        "trading_date": request.trading_date,
        "policy_version": policy.policy_version,
        "profile_name": policy.profile_name,
        "ticker": request.setup.ticker,
        "final_rank": request.final_rank,
        "decision": RiskDecisionStatus.APPROVED,
        "rejection_reasons": (),
        "kill_switch_required": False,
        "session_reference_equity": session_reference_equity,
        "broker_session_pnl": broker_session_pnl,
        "internal_session_pnl": internal_session_pnl,
        "risk_session_pnl": risk_session_pnl,
        "usable_buying_power": usable_buying_power,
        "base_trade_risk_budget": base_trade_risk_budget,
        "risk_flag_multiplier": risk_flag_multiplier,
        "adjusted_trade_risk_budget": adjusted_trade_risk_budget,
        "planned_entry_limit": planned_entry_limit,
        "stop_price": stop_price,
        "target_price": target_price,
        "structural_risk_per_share": structural_risk_per_share,
        "execution_risk_buffer": execution_risk_buffer,
        "modeled_risk_per_share": modeled_risk_per_share,
        "maximum_total_open_risk": maximum_total_open_risk,
        "remaining_open_risk_capacity": remaining_open_risk_capacity,
        "remaining_hard_loss_capacity": remaining_hard_loss_capacity,
        "maximum_position_notional": maximum_position_notional,
        "remaining_gross_exposure": remaining_gross_exposure,
        "quantity_caps": caps,
        "binding_cap": binding_cap,
        "final_quantity": final_quantity,
        "reserved_modeled_risk": reserved_modeled_risk,
        "reserved_notional": reserved_notional,
        "reservation": reservation,
        "calculated_at": request.calculated_at,
        "account_snapshot_timestamp": request.account.snapshot_timestamp,
        "quote_timestamp": request.quote.quote_timestamp,
        "configuration_hash": request.configuration_hash,
        "input_hash": input_hash,
        "decision_hash": "0" * 64,
    }
    return _finalize_decision(base)


def size_approved_batch(batch: BatchSizingRequest) -> BatchSizingResult:
    if not batch.requests:
        raise ValueError("batch must contain at least one request")
    current_state = batch.requests[0].session
    decisions: list[RiskDecision] = []
    for original_request in batch.requests:
        request = original_request.model_copy(update={"session": current_state})
        decision = size_position(request)
        decisions.append(decision)
        if decision.decision == RiskDecisionStatus.APPROVED:
            assert decision.reserved_modeled_risk is not None
            assert decision.reserved_notional is not None
            current_state = current_state.model_copy(
                update={
                    "current_total_open_risk": (
                        current_state.current_total_open_risk + decision.reserved_modeled_risk
                    ),
                    "reserved_entry_notional": (
                        current_state.reserved_entry_notional + decision.reserved_notional
                    ),
                    "reserved_entry_position_count": (
                        current_state.reserved_entry_position_count + 1
                    ),
                }
            )
    return BatchSizingResult(decisions=tuple(decisions), ending_session_state=current_state)
