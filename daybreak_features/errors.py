"""Feature-engine exception hierarchy."""

from __future__ import annotations


class FeatureEngineError(ValueError):
    """Base deterministic feature-engine error."""


class DataQualityError(FeatureEngineError):
    """Raised when an input cannot support a valid feature calculation."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class ConfigurationError(FeatureEngineError):
    """Raised for internally incoherent feature configuration."""
