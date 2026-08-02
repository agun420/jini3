from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from daybreak_contracts.types import CanonicalTicker
from daybreak_risk.canonical import canonical_sha256 as risk_sha256
from daybreak_risk.models import Money, PositiveMoney, RiskDecision

from .enums import (
    BrokerOrderStatus,
    ExecutionEventType,
    ExecutionMode,
    ExecutionOutcome,
    ExecutionRejectionCode,
    OrderClass,
    OrderSide,
    OrderType,
    TimeInForce,
)


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ExecutionPolicy(StrictFrozenModel):
    policy_version: Literal["alpaca_execution_policy_v1"] = "alpaca_execution_policy_v1"
    mode: Literal[ExecutionMode.PAPER] = ExecutionMode.PAPER
    paper_base_url: Literal["https://paper-api.alpaca.markets"] = "https://paper-api.alpaca.markets"
    max_request_age_ms: Annotated[int, Field(gt=0, le=30000)] = 2000
    request_timeout_seconds: Annotated[float, Field(gt=0, le=30)] = 5.0
    cancel_unfilled_after_seconds: Annotated[int, Field(gt=0, le=120)] = 10
    partial_fill_protection_enabled: bool = True
    protective_stop_time_in_force: Literal[TimeInForce.DAY] = TimeInForce.DAY
    allow_live_execution: Literal[False] = False


class ExecutionRequest(StrictFrozenModel):
    execution_id: Annotated[str, Field(min_length=8, max_length=64)]
    run_id: Annotated[str, Field(min_length=1, max_length=128)]
    trading_date: date
    requested_at: datetime
    submission_cutoff_timestamp: datetime
    risk_decision: RiskDecision
    policy: ExecutionPolicy = ExecutionPolicy()
    configuration_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("requested_at", "submission_cutoff_timestamp")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def matches_risk_identity(self) -> ExecutionRequest:
        if self.run_id != self.risk_decision.run_id:
            raise ValueError("execution run_id must match risk decision")
        if self.trading_date != self.risk_decision.trading_date:
            raise ValueError("execution trading_date must match risk decision")
        if self.configuration_hash != self.risk_decision.configuration_hash:
            raise ValueError("execution configuration_hash must match risk decision")
        if self.submission_cutoff_timestamp < self.requested_at:
            raise ValueError("submission cutoff cannot precede requested_at")
        decision_body = self.risk_decision.model_dump(mode="python", exclude={"decision_hash"})
        if risk_sha256(decision_body) != self.risk_decision.decision_hash:
            raise ValueError("execution request contains an invalid risk decision hash")
        return self


class BrokerOrderCommand(StrictFrozenModel):
    command_id: Annotated[str, Field(min_length=8, max_length=64)]
    execution_id: str
    client_order_id: Annotated[str, Field(min_length=1, max_length=48)]
    symbol: CanonicalTicker
    quantity: Annotated[int, Field(gt=0)]
    side: OrderSide
    order_type: OrderType
    time_in_force: TimeInForce
    order_class: OrderClass
    limit_price: PositiveMoney | None = None
    stop_price: PositiveMoney | None = None
    take_profit_limit_price: PositiveMoney | None = None
    stop_loss_stop_price: PositiveMoney | None = None
    extended_hours: Literal[False] = False
    parent_client_order_id: str | None = None
    command_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_shape(self) -> BrokerOrderCommand:
        if self.order_class is OrderClass.BRACKET:
            if self.side is not OrderSide.BUY or self.order_type is not OrderType.LIMIT:
                raise ValueError("bracket entry must be a buy limit order")
            if self.limit_price is None:
                raise ValueError("bracket limit entry requires limit_price")
            if self.take_profit_limit_price is None or self.stop_loss_stop_price is None:
                raise ValueError("bracket entry requires take-profit and stop-loss prices")
            if not (self.stop_loss_stop_price < self.limit_price < self.take_profit_limit_price):
                raise ValueError("bracket prices must satisfy stop < entry < target")
        elif self.order_class is OrderClass.SIMPLE:
            if self.order_type is OrderType.STOP:
                if self.side is not OrderSide.SELL or self.stop_price is None:
                    raise ValueError("protective stop must be a sell stop with stop_price")
                if self.limit_price is not None:
                    raise ValueError("stop order cannot contain limit_price")
            else:
                raise ValueError("v1 simple commands support protective stop orders only")
        return self


class BrokerOrderLeg(StrictFrozenModel):
    broker_order_id: str
    client_order_id: str | None = None
    side: str
    order_type: str
    status: str
    quantity: Decimal
    filled_quantity: Decimal
    limit_price: Money | None = None
    stop_price: Money | None = None


class BrokerOrderSnapshot(StrictFrozenModel):
    snapshot_id: Annotated[str, Field(min_length=8, max_length=64)]
    broker_order_id: str
    client_order_id: str
    symbol: CanonicalTicker
    side: OrderSide
    order_type: OrderType
    time_in_force: str
    order_class: str
    status: BrokerOrderStatus
    quantity: Decimal = Field(gt=0)
    filled_quantity: Decimal = Field(ge=0)
    filled_avg_price: Money | None = None
    limit_price: Money | None = None
    stop_price: Money | None = None
    submitted_at: datetime | None = None
    updated_at: datetime
    legs: tuple[BrokerOrderLeg, ...] = ()
    raw_response_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    raw_response: dict[str, Any]

    @field_validator("submitted_at", "updated_at")
    @classmethod
    def aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("broker timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def filled_not_above_quantity(self) -> BrokerOrderSnapshot:
        if self.filled_quantity > self.quantity:
            raise ValueError("filled quantity cannot exceed order quantity")
        return self


class BrokerPositionSnapshot(StrictFrozenModel):
    symbol: CanonicalTicker
    quantity: Decimal = Field(ge=0)
    average_entry_price: Money | None = None
    observed_at: datetime
    raw_response_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("observed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("position timestamp must be timezone-aware")
        return value.astimezone(UTC)


class ExecutionEvent(StrictFrozenModel):
    execution_id: str
    event_sequence: Annotated[int, Field(ge=1)]
    event_type: ExecutionEventType
    event_timestamp: datetime
    broker_order_id: str | None = None
    client_order_id: str | None = None
    status: str | None = None
    filled_quantity: Decimal | None = Field(default=None, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)
    event_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("event_timestamp")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event_timestamp must be timezone-aware")
        return value.astimezone(UTC)


class TradeUpdate(StrictFrozenModel):
    event_id: Annotated[str, Field(min_length=1, max_length=128)]
    event: str
    event_timestamp: datetime
    order: BrokerOrderSnapshot
    raw_event_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("event_timestamp")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("trade-update timestamp must be timezone-aware")
        return value.astimezone(UTC)


class ReconciliationReport(StrictFrozenModel):
    report_id: str
    execution_id: str
    client_order_id: str
    checked_at: datetime
    matched: bool
    mismatch_codes: tuple[str, ...]
    broker_order: BrokerOrderSnapshot | None
    broker_position: BrokerPositionSnapshot | None
    report_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("checked_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("checked_at must be timezone-aware")
        return value.astimezone(UTC)


class ExecutionResult(StrictFrozenModel):
    result_id: str
    execution_id: str
    outcome: ExecutionOutcome
    rejection_reasons: tuple[ExecutionRejectionCode, ...]
    command: BrokerOrderCommand | None
    broker_order: BrokerOrderSnapshot | None
    protective_order: BrokerOrderSnapshot | None = None
    reconciliation_required: bool
    events: tuple[ExecutionEvent, ...]
    completed_at: datetime
    request_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    result_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("completed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def terminal_shape(self) -> ExecutionResult:
        if self.outcome in {
            ExecutionOutcome.SUBMITTED,
            ExecutionOutcome.EXISTING_RECONCILED,
            ExecutionOutcome.PARTIAL_FILL_PROTECTED,
        }:
            if self.command is None or self.broker_order is None:
                raise ValueError("successful execution result requires command and broker order")
        if self.outcome is ExecutionOutcome.REJECTED and not self.rejection_reasons:
            raise ValueError("rejected result requires rejection reasons")
        if self.outcome is ExecutionOutcome.RECONCILIATION_REQUIRED:
            if not self.reconciliation_required:
                raise ValueError("reconciliation-required outcome must set the flag")
        return self
