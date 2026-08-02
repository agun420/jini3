from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from daybreak.core.config import DaybreakSettings, Environment
from daybreak.core.hashing import file_sha256

from .canonical import canonical_sha256
from .models import ConfigurationFreeze


def build_configuration_freeze(
    settings: DaybreakSettings,
    *,
    specification_path: str | Path,
    component_versions: Mapping[str, str],
    frozen_at: datetime | None = None,
) -> ConfigurationFreeze:
    if settings.runtime.environment is not Environment.PAPER:
        raise ValueError("production candidate configuration must use the paper environment")
    if settings.safety.live_execution_enabled:
        raise ValueError("live execution must remain disabled")
    timestamp = frozen_at or datetime.now(UTC)
    components = tuple(sorted(component_versions.items()))
    body = {
        "frozen_at": timestamp,
        "release_version": "1.0.2",
        "specification_version": "6.3",
        "environment": "paper",
        "live_execution_enabled": False,
        "configuration_hash": settings.configuration_hash(),
        "specification_sha256": file_sha256(Path(specification_path)),
        "migration_head": "0009_phase9_release",
        "component_versions": components,
    }
    return ConfigurationFreeze.model_validate({**body, "freeze_hash": canonical_sha256(body)})
