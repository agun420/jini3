class DaybreakError(Exception):
    """Base error for platform-level failures."""


class ConfigurationError(DaybreakError):
    """Raised when runtime configuration is invalid or unavailable."""


class HealthCheckError(DaybreakError):
    """Raised when a required health check fails."""
