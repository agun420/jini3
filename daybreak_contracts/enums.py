from __future__ import annotations

from enum import StrEnum


class MarketStatus(StrEnum):
    NORMAL = "normal"
    LIMIT_UP_DOWN_ACTIVE = "limit_up_down_active"
    CIRCUIT_BREAKER_HALT = "circuit_breaker_halt"


class SourceType(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    UNCONFIRMED = "unconfirmed"


class VolumeProfile(StrEnum):
    CLEAN = "clean"
    SPIKY = "spiky"


class BorrowStatus(StrEnum):
    EASY = "easy"
    HARD_TO_BORROW = "hard_to_borrow"
    UNKNOWN = "unknown"


class ChartStructure(StrEnum):
    BLUE_SKY = "blue_sky"
    CLEAN_SHORT_TERM = "clean_short_term"
    MODERATE_ROOM = "moderate_room"
    CAPPED = "capped"


class DisqualifierFlag(StrEnum):
    PAID_PROMOTION = "paid_promotion"
    REVERSE_SPLIT_ONLY = "reverse_split_only"
    UNCONFIRMED_RUMOR = "unconfirmed_rumor"
    NON_OPERATING_PROMOTION = "non_operating_promotion"
    OTHER = "other_disqualifying_catalyst"


class RunStatus(StrEnum):
    APPROVED = "approved"
    NO_SETUPS = "no_setups"
    BLOCKED_MARKET = "blocked_market"
    STALE_PAYLOAD = "stale_payload"
    SCHEMA_FAILURE = "schema_failure"


class MagnitudeBucket(StrEnum):
    MAJOR_CONCRETE = "major_concrete"
    MATERIAL_PARTIALLY_QUANTIFIED = "material_partially_quantified"
    CREDIBLE_UNQUANTIFIED = "credible_unquantified"
    WEAK_OR_PRELIMINARY = "weak_or_preliminary"
    NO_VALID_DRIVER = "no_valid_driver"


class EvidencePurpose(StrEnum):
    MAGNITUDE = "magnitude"
    DISQUALIFIER = "disqualifier"
    NONE = "none"


class CatalystZeroReason(StrEnum):
    DISQUALIFIER_FLAG = "disqualifier_flag"
    UNCONFIRMED_SOURCE = "unconfirmed_source"
    STALE_CATALYST = "stale_catalyst"
    NO_VALID_DRIVER = "no_valid_driver"


class TechnicalGrade(StrEnum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"


class RiskFlag(StrEnum):
    PARABOLIC = "parabolic_vwap_extension"
    HARD_TO_BORROW = "hard_to_borrow"
    UNKNOWN_BORROW = "unknown_borrow"
    LOW_FLOAT = "low_float"
    SPIKY_VOLUME = "spiky_volume"
    SECONDARY_SOURCE = "secondary_source"


class ReasonCode(StrEnum):
    HALTED = "HALTED"
    CATALYST_SCORE_TOO_LOW = "CATALYST_SCORE_TOO_LOW"
    UNCORROBORATED_CATALYST = "UNCORROBORATED_CATALYST"
    GAP_TOO_SMALL = "GAP_TOO_SMALL"
    PREMARKET_VOLUME_TOO_LOW = "PREMARKET_VOLUME_TOO_LOW"
    RVOL_TOO_LOW = "RVOL_TOO_LOW"
    RESISTANCE_TOO_CLOSE = "RESISTANCE_TOO_CLOSE"
    CAPPED_CHART = "CAPPED_CHART"


class BlockerCode(StrEnum):
    MARKET_NOT_NORMAL = "MARKET_NOT_NORMAL"
    PAYLOAD_STALE = "PAYLOAD_STALE"


class SchemaFailureScope(StrEnum):
    PAYLOAD = "payload"
    TICKER = "ticker"
