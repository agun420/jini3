from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from daybreak_contracts.output_models import ApprovedSetup
from daybreak_contracts.types import CanonicalTicker

from .canonical import canonical_sha256
from .enums import (
    BindingCap,
    ReservationStatus,
    RiskDecisionStatus,
    RiskProfileName,
    RiskRejectionCode,
)

Money = Annotated[Decimal, Field(max_digits=30, decimal_places=10)]
NonNegativeMoney = Annotated[Decimal, Field(ge=0, max_digits=30, decimal_places=10)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=30, decimal_places=10)]
PositiveRatio = Annotated[Decimal, Field(gt=0, lt=1)]
NonNegativeRatio = Annotated[Decimal, Field(ge=0, lt=1)]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class RiskPolicyConfig(StrictFrozenModel):
    policy_version: Literal["position_risk_policy_v1"] = "position_risk_policy_v1"
    profile_name: RiskProfileName

    allow_margin: Literal[False] = False
    allow_fractional_shares: Literal[False] = False
    allow_overnight_positions: Literal[False] = False

    risk_per_trade_pct: PositiveRatio
    max_open_risk_pct: PositiveRatio
    max_position_notional_pct: PositiveRatio
    max_gross_long_exposure_pct: PositiveRatio
    buying_power_reserve_pct: NonNegativeRatio

    max_concurrent_positions: Annotated[int, Field(gt=0, le=3)]
    max_new_entries_per_day: Annotated[int, Field(gt=0, le=3)]
    max_entries_per_ticker_per_day: Literal[1] = 1

    soft_daily_loss_pct: PositiveRatio
    hard_daily_loss_pct: PositiveRatio
    max_consecutive_losses: Annotated[int, Field(gt=0, le=10)]

    slippage_buffer_atr_multiple: Annotated[Decimal, Field(ge=0, le=2)]
    slippage_buffer_spread_multiple: Annotated[Decimal, Field(ge=0, le=5)]
    max_pct_adv20: PositiveRatio
    max_pct_premarket_volume: PositiveRatio

    max_account_snapshot_age_ms: Annotated[int, Field(gt=0, le=10000)] = 1000
    max_quote_age_ms: Annotated[int, Field(gt=0, le=10000)] = 1000
    max_last_trade_age_ms: Annotated[int, Field(gt=0, le=30000)] = 2000
    max_spread_pct: PositiveRatio = Decimal("0.01")
    max_spread_atr_fraction: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.10")
    max_entry_drift_pct: PositiveRatio = Decimal("0.01")
    max_entry_drift_atr_multiple: Annotated[Decimal, Field(gt=0, le=2)] = Decimal("0.25")
    pnl_reconciliation_tolerance: NonNegativeMoney = Decimal("1.00")

    minimum_quantity: Literal[1] = 1
    mandatory_flatten_time_et: time = time(15, 50)

    @model_validator(mode="after")
    def validate_coherence(self) -> RiskPolicyConfig:
        if self.soft_daily_loss_pct >= self.hard_daily_loss_pct:
            raise ValueError("soft_daily_loss_pct must be below hard_daily_loss_pct")
        if self.risk_per_trade_pct > self.max_open_risk_pct:
            raise ValueError("risk_per_trade_pct cannot exceed max_open_risk_pct")
        if self.max_position_notional_pct > self.max_gross_long_exposure_pct:
            raise ValueError("max_position_notional_pct cannot exceed max_gross_long_exposure_pct")
        if self.max_concurrent_positions > self.max_new_entries_per_day:
            raise ValueError("max_concurrent_positions cannot exceed max_new_entries_per_day")
        return self

    @classmethod
    def paper_v1(cls) -> RiskPolicyConfig:
        return cls(
            profile_name=RiskProfileName.PAPER_V1,
            risk_per_trade_pct=Decimal("0.0025"),
            max_open_risk_pct=Decimal("0.0075"),
            max_position_notional_pct=Decimal("0.10"),
            max_gross_long_exposure_pct=Decimal("0.25"),
            buying_power_reserve_pct=Decimal("0.20"),
            max_concurrent_positions=3,
            max_new_entries_per_day=3,
            soft_daily_loss_pct=Decimal("0.0075"),
            hard_daily_loss_pct=Decimal("0.0100"),
            max_consecutive_losses=2,
            slippage_buffer_atr_multiple=Decimal("0.10"),
            slippage_buffer_spread_multiple=Decimal("0.50"),
            max_pct_adv20=Decimal("0.001"),
            max_pct_premarket_volume=Decimal("0.005"),
        )

    @classmethod
    def live_pilot_v1(cls) -> RiskPolicyConfig:
        return cls(
            profile_name=RiskProfileName.LIVE_PILOT_V1,
            risk_per_trade_pct=Decimal("0.0010"),
            max_open_risk_pct=Decimal("0.0020"),
            max_position_notional_pct=Decimal("0.05"),
            max_gross_long_exposure_pct=Decimal("0.10"),
            buying_power_reserve_pct=Decimal("0.30"),
            max_concurrent_positions=1,
            max_new_entries_per_day=1,
            soft_daily_loss_pct=Decimal("0.0030"),
            hard_daily_loss_pct=Decimal("0.0050"),
            max_consecutive_losses=1,
            slippage_buffer_atr_multiple=Decimal("0.10"),
            slippage_buffer_spread_multiple=Decimal("0.50"),
            max_pct_adv20=Decimal("0.0005"),
            max_pct_premarket_volume=Decimal("0.0025"),
        )


class AccountSnapshot(StrictFrozenModel):
    snapshot_timestamp: datetime
    status: str
    account_blocked: bool
    trading_blocked: bool
    trade_suspended_by_user: bool
    equity: Money
    last_equity: Money
    cash: Money
    buying_power: Money
    non_marginable_buying_power: Money
    regt_buying_power: Money
    initial_margin: Money
    maintenance_margin: Money
    long_market_value: Money
    multiplier: Annotated[Decimal, Field(ge=0)]
    pending_transfer_in: Money = Decimal("0")
    pending_transfer_out: Money = Decimal("0")

    @field_validator("snapshot_timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot_timestamp must be timezone-aware")
        return value.astimezone(UTC)


class QuoteSnapshot(StrictFrozenModel):
    quote_timestamp: datetime
    last_trade_timestamp: datetime
    bid_price: Money
    ask_price: Money
    bid_size: Annotated[int, Field(ge=0)]
    ask_size: Annotated[int, Field(ge=0)]
    last_price: Money
    first_regular_session_nbbo_confirmed: bool

    @field_validator("quote_timestamp", "last_trade_timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("market timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @property
    def spread(self) -> Decimal:
        return self.ask_price - self.bid_price

    @property
    def midpoint(self) -> Decimal:
        return (self.bid_price + self.ask_price) / Decimal("2")


class LiquiditySnapshot(StrictFrozenModel):
    premarket_volume: Annotated[int, Field(gt=0)]
    adv20_shares: Annotated[int, Field(gt=0)]
    asset_tradable: bool = True
    asset_fractionable: bool = False
    asset_marginable: bool = False
    asset_status: str = "active"


class SessionRiskState(StrictFrozenModel):
    session_reference_equity: PositiveMoney
    session_start_equity: PositiveMoney
    net_external_cash_flow: Money = Decimal("0")
    internal_realized_pnl: Money = Decimal("0")
    internal_unrealized_pnl: Money = Decimal("0")
    current_total_open_risk: NonNegativeMoney = Decimal("0")
    reserved_entry_notional: NonNegativeMoney = Decimal("0")
    current_long_market_value: NonNegativeMoney = Decimal("0")
    open_daybreak_position_count: Annotated[int, Field(ge=0)] = 0
    reserved_entry_position_count: Annotated[int, Field(ge=0)] = 0
    completed_entry_count: Annotated[int, Field(ge=0)] = 0
    consecutive_closed_losses: Annotated[int, Field(ge=0)] = 0
    traded_tickers_today: tuple[CanonicalTicker, ...] = ()
    account_state_reconciled: bool = True
    streams_healthy: bool = True
    database_healthy: bool = True
    kill_switch_active: bool = False

    @field_validator("traded_tickers_today")
    @classmethod
    def tickers_sorted_unique(
        cls, value: tuple[CanonicalTicker, ...]
    ) -> tuple[CanonicalTicker, ...]:
        if tuple(sorted(set(value))) != value:
            raise ValueError("traded_tickers_today must be sorted and unique")
        return value


class SizingRequest(StrictFrozenModel):
    request_id: str
    run_id: str
    trading_date: date
    final_rank: Annotated[int, Field(ge=1, le=3)]
    calculated_at: datetime
    execution_cutoff_timestamp: datetime
    setup: ApprovedSetup
    policy: RiskPolicyConfig
    account: AccountSnapshot
    quote: QuoteSnapshot
    liquidity: LiquiditySnapshot
    session: SessionRiskState
    planned_entry_limit: PositiveMoney
    tick_size: PositiveMoney
    market_status_normal: bool = True
    symbol_halted: bool = False
    configuration_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("calculated_at", "execution_cutoff_timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("request timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def trading_date_matches_new_york(self) -> SizingRequest:
        et_date = self.calculated_at.astimezone(ZoneInfo("America/New_York")).date()
        if self.trading_date != et_date:
            raise ValueError("trading_date must match calculated_at in America/New_York")
        if self.execution_cutoff_timestamp < self.calculated_at:
            raise ValueError("execution cutoff cannot precede the sizing timestamp")
        return self


class QuantityCaps(StrictFrozenModel):
    trade_risk: Annotated[int, Field(ge=0)]
    open_risk: Annotated[int, Field(ge=0)]
    daily_loss: Annotated[int, Field(ge=0)]
    buying_power: Annotated[int, Field(ge=0)]
    position_notional: Annotated[int, Field(ge=0)]
    gross_exposure: Annotated[int, Field(ge=0)]
    adv_liquidity: Annotated[int, Field(ge=0)]
    premarket_liquidity: Annotated[int, Field(ge=0)]


class RiskReservation(StrictFrozenModel):
    reservation_id: str
    request_id: str
    run_id: str
    trading_date: date
    ticker: CanonicalTicker
    client_order_id: Annotated[str, Field(min_length=1, max_length=48)]
    reserved_quantity: Annotated[int, Field(gt=0)]
    reserved_notional: PositiveMoney
    reserved_modeled_risk: PositiveMoney
    created_at: datetime
    expires_at: datetime
    status: ReservationStatus = ReservationStatus.RESERVED

    @field_validator("created_at", "expires_at")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reservation timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def expiration_after_creation(self) -> RiskReservation:
        if self.expires_at <= self.created_at:
            raise ValueError("reservation expires_at must be after created_at")
        return self


class RiskDecision(StrictFrozenModel):
    decision_id: str
    request_id: str
    run_id: str
    trading_date: date
    policy_version: Literal["position_risk_policy_v1"]
    profile_name: RiskProfileName
    ticker: CanonicalTicker
    final_rank: Annotated[int, Field(ge=1, le=3)]
    decision: RiskDecisionStatus
    rejection_reasons: tuple[RiskRejectionCode, ...]
    kill_switch_required: bool

    session_reference_equity: Money | None
    broker_session_pnl: Money | None
    internal_session_pnl: Money | None
    risk_session_pnl: Money | None
    usable_buying_power: Money | None
    base_trade_risk_budget: Money | None
    risk_flag_multiplier: Decimal | None
    adjusted_trade_risk_budget: Money | None

    planned_entry_limit: Money | None
    stop_price: Money | None
    target_price: Money | None
    structural_risk_per_share: Money | None
    execution_risk_buffer: Money | None
    modeled_risk_per_share: Money | None
    maximum_total_open_risk: Money | None
    remaining_open_risk_capacity: Money | None
    remaining_hard_loss_capacity: Money | None
    maximum_position_notional: Money | None
    remaining_gross_exposure: Money | None

    quantity_caps: QuantityCaps | None
    binding_cap: BindingCap | None
    final_quantity: Annotated[int, Field(ge=0)]
    reserved_modeled_risk: Money | None
    reserved_notional: Money | None
    reservation: RiskReservation | None

    calculated_at: datetime
    account_snapshot_timestamp: datetime
    quote_timestamp: datetime
    configuration_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    input_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    decision_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> RiskDecision:
        if self.decision_id != f"risk-{self.request_id}":
            raise ValueError("risk decision id must derive from request_id")
        if self.decision == RiskDecisionStatus.APPROVED:
            if self.rejection_reasons:
                raise ValueError("approved decisions cannot contain rejection reasons")
            if self.final_quantity < 1 or self.reservation is None:
                raise ValueError("approved decisions require positive quantity and reservation")
            if self.binding_cap is None or self.quantity_caps is None:
                raise ValueError("approved decisions require quantity caps and binding cap")
            required_values = (
                self.planned_entry_limit,
                self.stop_price,
                self.target_price,
                self.modeled_risk_per_share,
                self.reserved_modeled_risk,
                self.reserved_notional,
            )
            if any(value is None for value in required_values):
                raise ValueError("approved decisions require complete price and risk evidence")
            reservation = self.reservation
            assert reservation is not None
            if (
                reservation.request_id != self.request_id
                or reservation.run_id != self.run_id
                or reservation.trading_date != self.trading_date
                or reservation.ticker != self.ticker
                or reservation.reserved_quantity != self.final_quantity
                or reservation.reserved_notional != self.reserved_notional
                or reservation.reserved_modeled_risk != self.reserved_modeled_risk
                or reservation.created_at != self.calculated_at
            ):
                raise ValueError("risk reservation identity does not match its decision")
        else:
            if not self.rejection_reasons:
                raise ValueError("rejected decisions require at least one reason")
            if self.final_quantity != 0 or self.reservation is not None:
                raise ValueError("rejected decisions cannot reserve quantity")
            if any(
                value is not None
                for value in (
                    self.quantity_caps,
                    self.binding_cap,
                    self.reserved_modeled_risk,
                    self.reserved_notional,
                )
            ):
                raise ValueError("rejected decisions cannot carry reservation evidence")
        body = self.model_dump(mode="python", exclude={"decision_hash"})
        if canonical_sha256(body) != self.decision_hash:
            raise ValueError("risk decision hash does not match canonical decision body")
        return self


class BatchSizingRequest(StrictFrozenModel):
    requests: tuple[SizingRequest, ...]

    @model_validator(mode="after")
    def validate_rank_order(self) -> BatchSizingRequest:
        if not self.requests:
            raise ValueError("batch must contain at least one request")
        if len(self.requests) > 3:
            raise ValueError("at most three approved setups may be sized")
        ranks = [request.final_rank for request in self.requests]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("batch requests must use contiguous ranks beginning at 1")
        if len({request.request_id for request in self.requests}) != len(self.requests):
            raise ValueError("batch request_id values must be unique")
        if len({request.setup.ticker for request in self.requests}) != len(self.requests):
            raise ValueError("batch tickers must be unique")
        first = self.requests[0]
        for request in self.requests[1:]:
            if request.run_id != first.run_id:
                raise ValueError("all batch requests must use the same run_id")
            if request.configuration_hash != first.configuration_hash:
                raise ValueError("all batch requests must use the same configuration_hash")
            if request.calculated_at != first.calculated_at:
                raise ValueError("all batch requests must use the same calculated_at")
            if request.execution_cutoff_timestamp != first.execution_cutoff_timestamp:
                raise ValueError("all batch requests must use the same execution cutoff")
            if request.policy != first.policy:
                raise ValueError("all batch requests must use the same risk policy")
            if request.account != first.account:
                raise ValueError("all batch requests must use the same account snapshot")
            if request.session != first.session:
                raise ValueError("all batch requests must use the same initial session state")
        return self


class BatchSizingResult(StrictFrozenModel):
    decisions: tuple[RiskDecision, ...]
    ending_session_state: SessionRiskState
