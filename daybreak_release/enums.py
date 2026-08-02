from enum import StrEnum


class ReviewSeverity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ApprovalRole(StrEnum):
    ENGINEERING = "engineering"
    OPERATIONS = "operations"
    RISK = "risk"
    SECURITY = "security"
    INDEPENDENT_REVIEW = "independent_review"


class CandidateStatus(StrEnum):
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"
    PAPER_RELEASE_CANDIDATE = "paper_release_candidate"
