from __future__ import annotations

from enum import StrEnum


class SessionPhase(StrEnum):
    CREATED = "created"
    PREFLIGHT = "preflight"
    LEADERSHIP_ACQUIRED = "leadership_acquired"
    RECORDER_WARMUP = "recorder_warmup"
    RECORDING = "recording"
    FEATURE_FREEZE = "feature_freeze"
    EVALUATION = "evaluation"
    RISK = "risk"
    ELIGIBILITY_LOCK = "eligibility_lock"
    EXECUTION = "execution"
    MONITORING = "monitoring"
    FLATTENING = "flattening"
    RECONCILIATION = "reconciliation"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


class SessionOutcome(StrEnum):
    COMPLETED = "completed"
    NO_SETUPS = "no_setups"
    BLOCKED = "blocked"
    FAILED = "failed"
    KILLED = "killed"
    FLATTEN_INCOMPLETE = "flatten_incomplete"


class PhaseStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class KillSwitchReason(StrEnum):
    MANUAL = "MANUAL"
    HARD_DAILY_LOSS = "HARD_DAILY_LOSS"
    ACCOUNT_BLOCKED = "ACCOUNT_BLOCKED"
    TRADING_BLOCKED = "TRADING_BLOCKED"
    MARKET_CIRCUIT_BREAKER = "MARKET_CIRCUIT_BREAKER"
    CLOCK_UNSYNCED = "CLOCK_UNSYNCED"
    DATABASE_UNHEALTHY = "DATABASE_UNHEALTHY"
    RECORDER_UNHEALTHY = "RECORDER_UNHEALTHY"
    MARKET_DATA_UNHEALTHY = "MARKET_DATA_UNHEALTHY"
    TRADE_UPDATE_STREAM_UNHEALTHY = "TRADE_UPDATE_STREAM_UNHEALTHY"
    BROKER_UNHEALTHY = "BROKER_UNHEALTHY"
    LEADERSHIP_LOST = "LEADERSHIP_LOST"
    CONFIGURATION_MISMATCH = "CONFIGURATION_MISMATCH"
    RECONCILIATION_FAILURE = "RECONCILIATION_FAILURE"
    UNPROTECTED_POSITION = "UNPROTECTED_POSITION"
    EXECUTION_CUTOFF_EXCEEDED = "EXECUTION_CUTOFF_EXCEEDED"
    FLATTEN_DEADLINE_EXCEEDED = "FLATTEN_DEADLINE_EXCEEDED"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AcceptanceStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class LeadershipEventType(StrEnum):
    ACQUIRED = "acquired"
    RENEWED = "renewed"
    RELEASED = "released"
    LOST = "lost"
