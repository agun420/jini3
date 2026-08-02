from enum import StrEnum


class ReplayComponent(StrEnum):
    RECORDER = "recorder"
    FEATURES = "features"
    EVALUATOR = "evaluator"
    RISK = "risk"
    EXECUTION = "execution"
    ORCHESTRATION = "orchestration"


class ExitReason(StrEnum):
    TARGET = "target"
    STOP = "stop"
    TIME_EXIT = "time_exit"
    KILL_SWITCH = "kill_switch"
    MANUAL_SAFETY = "manual_safety"
    BROKER_RECONCILIATION = "broker_reconciliation"


class AcceptanceStatus(StrEnum):
    COLLECTING = "collecting"
    BLOCKED = "blocked"
    PAPER_QUALIFIED = "paper_qualified"


class DeploymentStatus(StrEnum):
    INCOMPLETE = "incomplete"
    PAPER_READY = "paper_ready"
