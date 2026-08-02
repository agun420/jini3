from enum import StrEnum


class RecoveryAction(StrEnum):
    BLOCK = "block"
    CAPTURE_ONLY = "capture_only"
    RECONCILE_ONLY = "reconcile_only"
    FLATTEN_ONLY = "flatten_only"
    MANUAL_REVIEW = "manual_review"


class DrillType(StrEnum):
    DATABASE_DISCONNECT = "database_disconnect"
    MARKET_DATA_DISCONNECT = "market_data_disconnect"
    TRADE_UPDATE_DISCONNECT = "trade_update_disconnect"
    BROKER_TIMEOUT = "broker_timeout"
    CLOCK_SKEW = "clock_skew"
    PROCESS_RESTART = "process_restart"
    DISK_PRESSURE = "disk_pressure"


class DrillStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
