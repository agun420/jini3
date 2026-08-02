from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from daybreak_operations.enums import DrillType

from .enums import AcceptanceStatus, DeploymentStatus, ExitReason, ReplayComponent

HASH = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ID = Annotated[str, Field(min_length=8, max_length=64)]
Ticker = Annotated[str, Field(pattern=r"^[A-Z0-9](?:[A-Z0-9.-]{0,13}[A-Z0-9])?$")]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class AnalyticsPolicy(StrictFrozenModel):
    policy_version: Literal["analytics_policy_v1"] = "analytics_policy_v1"
    mode: Literal["paper"] = "paper"
    minimum_sessions: Annotated[int, Field(ge=1, le=365)] = 30
    minimum_filled_orders: Annotated[int, Field(ge=1, le=10000)] = 50
    minimum_clean_session_rate: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("1")
    maximum_invariant_violations: Annotated[int, Field(ge=0)] = 0
    maximum_unresolved_reconciliations: Annotated[int, Field(ge=0)] = 0
    maximum_duplicate_orders: Annotated[int, Field(ge=0)] = 0
    maximum_late_primary_responses: Annotated[int, Field(ge=0)] = 0
    require_all_positions_flat: Literal[True] = True
    require_complete_replay: Literal[True] = True
    require_target_acceptance: Literal[True] = True
    require_restore_validation: Literal[True] = True
    required_drill_count: Annotated[int, Field(ge=0, le=32)] = 7
    performance_is_acceptance_gate: Literal[False] = False
    allow_live_certification: Literal[False] = False


class TradeOutcome(StrictFrozenModel):
    trade_id: ID
    session_id: ID
    ticker: Ticker
    final_rank: Annotated[int, Field(ge=1, le=3)]
    quantity: Annotated[int, Field(gt=0)]
    entry_timestamp: datetime
    exit_timestamp: datetime
    planned_entry_price: Annotated[Decimal, Field(gt=0)]
    average_entry_price: Annotated[Decimal, Field(gt=0)]
    planned_stop_price: Annotated[Decimal, Field(gt=0)]
    planned_target_price: Annotated[Decimal, Field(gt=0)]
    average_exit_price: Annotated[Decimal, Field(gt=0)]
    fees: Annotated[Decimal, Field(ge=0)] = Decimal("0")
    source_type: Literal["primary", "secondary"]
    chart_structure: Literal["blue_sky", "clean_short_term", "moderate_room"]
    risk_flags: tuple[
        Literal[
            "parabolic_vwap_extension",
            "hard_to_borrow",
            "unknown_borrow",
            "low_float",
            "spiky_volume",
            "secondary_source",
        ],
        ...,
    ] = ()
    exit_reason: ExitReason

    @field_validator("entry_timestamp", "exit_timestamp")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("trade timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("risk_flags")
    @classmethod
    def risk_flags_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        order = {
            "parabolic_vwap_extension": 0,
            "hard_to_borrow": 1,
            "unknown_borrow": 2,
            "low_float": 3,
            "spiky_volume": 4,
            "secondary_source": 5,
        }
        if len(set(value)) != len(value):
            raise ValueError("risk flags must be unique")
        if tuple(sorted(value, key=order.__getitem__)) != value:
            raise ValueError("risk flags must use Daybreak canonical order")
        return value

    @model_validator(mode="after")
    def coherent(self) -> TradeOutcome:
        if self.exit_timestamp < self.entry_timestamp:
            raise ValueError("exit timestamp cannot precede entry timestamp")
        if self.planned_stop_price >= self.planned_entry_price:
            raise ValueError("long stop must be below planned entry")
        if self.planned_target_price <= self.planned_entry_price:
            raise ValueError("long target must be above planned entry")
        return self


class SessionEvidence(StrictFrozenModel):
    session_id: ID
    trading_date: date
    generated_at: datetime
    configuration_hash: HASH
    full_session_recorded: bool
    raw_event_count: Annotated[int, Field(ge=0)]
    evaluator_run_count: Annotated[int, Field(ge=0)]
    approved_setup_count: Annotated[int, Field(ge=0, le=3)]
    qualified_not_selected_count: Annotated[int, Field(ge=0)]
    excluded_ticker_count: Annotated[int, Field(ge=0)]
    orders_submitted: Annotated[int, Field(ge=0)]
    orders_filled: Annotated[int, Field(ge=0)]
    invariant_violations: Annotated[int, Field(ge=0)]
    unresolved_reconciliations: Annotated[int, Field(ge=0)]
    duplicate_order_count: Annotated[int, Field(ge=0)]
    late_primary_response_count: Annotated[int, Field(ge=0)]
    all_positions_flat: bool
    kill_switch_activation_count: Annotated[int, Field(ge=0)]
    trades: tuple[TradeOutcome, ...] = ()

    @field_validator("generated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("session timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self) -> SessionEvidence:
        if any(item.session_id != self.session_id for item in self.trades):
            raise ValueError("all trades must belong to the session")
        if len({item.trade_id for item in self.trades}) != len(self.trades):
            raise ValueError("trade ids must be unique within a session")
        if (
            tuple(sorted(self.trades, key=lambda item: (item.entry_timestamp, item.trade_id)))
            != self.trades
        ):
            raise ValueError("trades must be sorted by entry timestamp and trade id")
        if self.orders_filled != len(self.trades):
            raise ValueError("orders_filled must equal the number of completed trade outcomes")
        if self.orders_filled > self.orders_submitted:
            raise ValueError("filled orders cannot exceed submitted orders")
        return self


class AttributionBucket(StrictFrozenModel):
    dimension: Literal["source_type", "chart_structure", "risk_flag", "exit_reason"]
    key: str
    trade_count: Annotated[int, Field(gt=0)]
    net_pnl: Decimal
    win_rate: Annotated[Decimal, Field(ge=0, le=1)]
    expectancy: Decimal
    average_r_multiple: Decimal


class SessionPerformance(StrictFrozenModel):
    analytics_id: ID
    session_id: ID
    trading_date: date
    trade_count: Annotated[int, Field(ge=0)]
    winning_trade_count: Annotated[int, Field(ge=0)]
    losing_trade_count: Annotated[int, Field(ge=0)]
    breakeven_trade_count: Annotated[int, Field(ge=0)]
    gross_pnl: Decimal
    fees: Annotated[Decimal, Field(ge=0)]
    net_pnl: Decimal
    win_rate: Annotated[Decimal, Field(ge=0, le=1)]
    profit_factor: Decimal | None
    expectancy: Decimal
    average_win: Decimal
    average_loss: Decimal
    average_r_multiple: Decimal
    maximum_drawdown: Annotated[Decimal, Field(ge=0)]
    total_entry_slippage: Decimal
    average_entry_slippage_bps: Decimal
    attributions: tuple[AttributionBucket, ...]
    evidence_hash: HASH
    analytics_hash: HASH


class ReplayComponentEvidence(StrictFrozenModel):
    component: ReplayComponent
    expected_hash: HASH | None = None
    actual_hash: HASH | None = None
    evidence_count: Annotated[int, Field(ge=0)] = 0
    verified: bool
    errors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> ReplayComponentEvidence:
        expected = bool(
            self.expected_hash
            and self.actual_hash
            and self.expected_hash == self.actual_hash
            and not self.errors
        )
        if self.verified != expected:
            raise ValueError("component verified flag does not match hash/error evidence")
        return self


class FullSessionReplayRequest(StrictFrozenModel):
    session_id: ID
    trading_date: date
    replayed_at: datetime
    expected_raw_event_count: Annotated[int, Field(ge=0)]
    actual_raw_event_count: Annotated[int, Field(ge=0)]
    event_ordering_verified: bool
    point_in_time_integrity_verified: bool
    components: tuple[ReplayComponentEvidence, ...]

    @field_validator("replayed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("replay timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("components")
    @classmethod
    def unique_components(
        cls, value: tuple[ReplayComponentEvidence, ...]
    ) -> tuple[ReplayComponentEvidence, ...]:
        names = [item.component for item in value]
        if len(set(names)) != len(names):
            raise ValueError("replay component evidence must be unique")
        if tuple(sorted(value, key=lambda item: item.component.value)) != value:
            raise ValueError("replay components must be sorted by component name")
        return value


class FullSessionReplayReport(StrictFrozenModel):
    replay_id: ID
    session_id: ID
    trading_date: date
    replayed_at: datetime
    complete: bool
    passed: bool
    expected_raw_event_count: Annotated[int, Field(ge=0)]
    actual_raw_event_count: Annotated[int, Field(ge=0)]
    event_ordering_verified: bool
    point_in_time_integrity_verified: bool
    components: tuple[ReplayComponentEvidence, ...]
    errors: tuple[str, ...]
    request_hash: HASH
    report_hash: HASH

    @field_validator("replayed_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("replay timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("components")
    @classmethod
    def components_sorted_unique(
        cls, value: tuple[ReplayComponentEvidence, ...]
    ) -> tuple[ReplayComponentEvidence, ...]:
        names = [item.component for item in value]
        if len(set(names)) != len(names):
            raise ValueError("replay report components must be unique")
        if tuple(sorted(value, key=lambda item: item.component.value)) != value:
            raise ValueError("replay report components must be sorted")
        return value

    @model_validator(mode="after")
    def coherent(self) -> FullSessionReplayReport:
        required = frozenset(ReplayComponent)
        present = frozenset(item.component for item in self.components)
        expected_complete = present == required
        expected_passed = (
            expected_complete
            and self.expected_raw_event_count == self.actual_raw_event_count
            and self.event_ordering_verified
            and self.point_in_time_integrity_verified
            and all(item.verified for item in self.components)
            and not self.errors
        )
        if self.complete != expected_complete or self.passed != expected_passed:
            raise ValueError("replay completion/pass flags do not match evidence")
        return self


class PaperAcceptanceRequest(StrictFrozenModel):
    generated_at: datetime
    policy: AnalyticsPolicy = AnalyticsPolicy()
    sessions: tuple[SessionEvidence, ...]
    replay_reports: tuple[FullSessionReplayReport, ...]
    target_acceptance_verified: bool
    restore_validation_verified: bool
    passed_drills: tuple[DrillType, ...] = ()
    configuration_hash: HASH

    @field_validator("generated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ledger timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("sessions")
    @classmethod
    def sessions_sorted_unique(
        cls, value: tuple[SessionEvidence, ...]
    ) -> tuple[SessionEvidence, ...]:
        keys = [(item.trading_date, item.session_id) for item in value]
        if len(set(keys)) != len(keys):
            raise ValueError("session evidence must be unique")
        if tuple(sorted(value, key=lambda item: (item.trading_date, item.session_id))) != value:
            raise ValueError("sessions must be sorted by trading date and session id")
        return value

    @field_validator("replay_reports")
    @classmethod
    def reports_sorted_unique(
        cls, value: tuple[FullSessionReplayReport, ...]
    ) -> tuple[FullSessionReplayReport, ...]:
        keys = [(item.trading_date, item.session_id) for item in value]
        if len(set(keys)) != len(keys):
            raise ValueError("replay reports must be unique")
        if tuple(sorted(value, key=lambda item: (item.trading_date, item.session_id))) != value:
            raise ValueError("replay reports must be sorted")
        return value

    @field_validator("passed_drills")
    @classmethod
    def drills_sorted_unique(cls, value: tuple[DrillType, ...]) -> tuple[DrillType, ...]:
        if tuple(sorted(set(value), key=lambda item: item.value)) != value:
            raise ValueError("passed drills must be sorted and unique")
        return value

    @model_validator(mode="after")
    def evidence_sets_match(self) -> PaperAcceptanceRequest:
        session_map = {item.session_id: item for item in self.sessions}
        replay_map = {item.session_id: item for item in self.replay_reports}
        if self.policy.require_complete_replay and set(session_map) != set(replay_map):
            raise ValueError("replay reports must match the session evidence set exactly")
        for session in self.sessions:
            if session.configuration_hash != self.configuration_hash:
                raise ValueError("all session configuration hashes must match the ledger request")
            replay = replay_map.get(session.session_id)
            if replay is not None and replay.trading_date != session.trading_date:
                raise ValueError("replay trading date must match session evidence")
        return self


class SessionAcceptance(StrictFrozenModel):
    session_id: ID
    trading_date: date
    clean: bool
    reasons: tuple[str, ...]
    analytics_id: ID
    replay_id: ID | None


class AggregatePerformance(StrictFrozenModel):
    session_count: Annotated[int, Field(ge=0)]
    trade_count: Annotated[int, Field(ge=0)]
    gross_pnl: Decimal
    fees: Annotated[Decimal, Field(ge=0)]
    net_pnl: Decimal
    win_rate: Annotated[Decimal, Field(ge=0, le=1)]
    profit_factor: Decimal | None
    expectancy: Decimal
    maximum_drawdown: Annotated[Decimal, Field(ge=0)]
    average_r_multiple: Decimal


class PaperAcceptanceLedger(StrictFrozenModel):
    ledger_id: ID
    generated_at: datetime
    status: AcceptanceStatus
    paper_ready: bool
    live_ready: Literal[False] = False
    session_count: Annotated[int, Field(ge=0)]
    clean_session_count: Annotated[int, Field(ge=0)]
    filled_order_count: Annotated[int, Field(ge=0)]
    clean_session_rate: Annotated[Decimal, Field(ge=0, le=1)]
    sessions: tuple[SessionAcceptance, ...]
    performance: AggregatePerformance
    blockers: tuple[str, ...]
    policy: AnalyticsPolicy
    configuration_hash: HASH
    request_hash: HASH
    ledger_hash: HASH

    @field_validator("generated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ledger timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self) -> PaperAcceptanceLedger:
        if self.paper_ready != (self.status is AcceptanceStatus.PAPER_QUALIFIED):
            raise ValueError("paper_ready must match paper-qualified status")
        if self.paper_ready and self.blockers:
            raise ValueError("paper-ready ledger cannot contain blockers")
        return self


class DeploymentEvidenceRequest(StrictFrozenModel):
    generated_at: datetime
    release_version: Literal["1.0.2"]
    specification_version: Literal["6.3"] = "6.3"
    configuration_hash: HASH
    source_archive_sha256: HASH
    wheel_sha256: HASH
    migrations_sha256: HASH
    schemas_bundle_sha256: HASH
    verification_report_sha256: HASH
    specification_sha256: HASH
    migration_head: Literal["0009_phase9_release"]
    tests_collected: Annotated[int, Field(gt=0)]
    tests_passed: Annotated[int, Field(ge=0)]
    schema_count: Annotated[int, Field(gt=0)]
    secret_findings: Annotated[int, Field(ge=0)]
    paper_ledger: PaperAcceptanceLedger
    target_acceptance_verified: bool
    restore_validation_verified: bool
    required_drills_verified: bool
    online_paper_account_verified: bool
    postgres_verified: bool
    ntp_verified: bool

    @field_validator("generated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deployment report timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ledger_configuration_matches(self) -> DeploymentEvidenceRequest:
        if self.paper_ledger.configuration_hash != self.configuration_hash:
            raise ValueError("paper ledger configuration hash must match deployment request")
        return self


class DeploymentEvidenceReport(StrictFrozenModel):
    report_id: ID
    generated_at: datetime
    status: DeploymentStatus
    paper_deployment_ready: bool
    live_deployment_ready: Literal[False] = False
    blockers: tuple[str, ...]
    release_version: Literal["1.0.2"]
    specification_version: Literal["6.3"]
    migration_head: Literal["0009_phase9_release"]
    configuration_hash: HASH
    paper_ledger_id: ID
    paper_ledger_hash: HASH
    tests_collected: Annotated[int, Field(gt=0)]
    tests_passed: Annotated[int, Field(ge=0)]
    schema_count: Annotated[int, Field(gt=0)]
    secret_findings: Annotated[int, Field(ge=0)]
    evidence_hashes: tuple[tuple[str, HASH], ...]
    request_hash: HASH
    report_hash: HASH

    @field_validator("generated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deployment report timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("evidence_hashes")
    @classmethod
    def evidence_sorted_unique(
        cls, value: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        if tuple(sorted(value)) != value:
            raise ValueError("evidence hashes must be sorted")
        if len({name for name, _ in value}) != len(value):
            raise ValueError("evidence hash names must be unique")
        return value

    @model_validator(mode="after")
    def coherent(self) -> DeploymentEvidenceReport:
        if self.paper_deployment_ready != (self.status is DeploymentStatus.PAPER_READY):
            raise ValueError("paper readiness must match deployment status")
        if self.paper_deployment_ready and self.blockers:
            raise ValueError("paper-ready report cannot contain blockers")
        if self.tests_passed > self.tests_collected:
            raise ValueError("passed tests cannot exceed collected tests")
        return self
