from __future__ import annotations

from enum import StrEnum


class ExecutionMode(StrEnum):
    PAPER = "paper"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    LIMIT = "limit"
    STOP = "stop"


class TimeInForce(StrEnum):
    DAY = "day"


class OrderClass(StrEnum):
    BRACKET = "bracket"
    SIMPLE = "simple"


class BrokerOrderStatus(StrEnum):
    ACCEPTED = "accepted"
    ACCEPTED_FOR_BIDDING = "accepted_for_bidding"
    PENDING_NEW = "pending_new"
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    DONE_FOR_DAY = "done_for_day"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"
    PENDING_REPLACE = "pending_replace"
    STOPPED = "stopped"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    CALCULATED = "calculated"


class ExecutionOutcome(StrEnum):
    SUBMITTED = "submitted"
    EXISTING_RECONCILED = "existing_reconciled"
    PARTIAL_FILL_PROTECTED = "partial_fill_protected"
    REJECTED = "rejected"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class ExecutionEventType(StrEnum):
    REQUEST_ACCEPTED = "request_accepted"
    COMMAND_PERSISTED = "command_persisted"
    BROKER_LOOKUP = "broker_lookup"
    SUBMIT_STARTED = "submit_started"
    BROKER_ACKNOWLEDGED = "broker_acknowledged"
    TRADE_UPDATE = "trade_update"
    CANCEL_REQUESTED = "cancel_requested"
    PROTECTIVE_STOP_SUBMIT_STARTED = "protective_stop_submit_started"
    PROTECTIVE_STOP_ACKNOWLEDGED = "protective_stop_acknowledged"
    REJECTED = "rejected"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class ExecutionRejectionCode(StrEnum):
    PAPER_MODE_REQUIRED = "PAPER_MODE_REQUIRED"
    LIVE_ENDPOINT_FORBIDDEN = "LIVE_ENDPOINT_FORBIDDEN"
    RISK_DECISION_NOT_APPROVED = "RISK_DECISION_NOT_APPROVED"
    RESERVATION_MISSING = "RESERVATION_MISSING"
    RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
    SUBMISSION_CUTOFF_EXCEEDED = "SUBMISSION_CUTOFF_EXCEEDED"
    REQUEST_STALE = "REQUEST_STALE"
    INVALID_ORDER_GEOMETRY = "INVALID_ORDER_GEOMETRY"
    COMMAND_IDENTITY_CONFLICT = "COMMAND_IDENTITY_CONFLICT"
    BROKER_ORDER_MISMATCH = "BROKER_ORDER_MISMATCH"
    BROKER_REJECTED = "BROKER_REJECTED"
    BROKER_TIMEOUT_UNKNOWN_STATE = "BROKER_TIMEOUT_UNKNOWN_STATE"
    BROKER_TRANSPORT_FAILURE = "BROKER_TRANSPORT_FAILURE"
    PARTIAL_FILL_PROTECTION_FAILED = "PARTIAL_FILL_PROTECTION_FAILED"
    POSITION_RECONCILIATION_FAILURE = "POSITION_RECONCILIATION_FAILURE"
