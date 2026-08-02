from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import ConfigurationError
from .hashing import canonical_sha256


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PAPER = "paper"
    LIVE = "live"


class StrictSettings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class RuntimeSettings(StrictSettings):
    environment: Environment = Environment.DEVELOPMENT
    timezone: Literal["America/New_York"] = "America/New_York"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    json_logs: bool = True


class PathSettings(StrictSettings):
    state_dir: Path = Path("state")
    artifact_dir: Path = Path("artifacts")
    spec_path: Path = Path("docs/spec/Project_Daybreak_v6.3_Final.md")


class DatabaseSettings(StrictSettings):
    enabled: bool = False
    dsn_env: str = "DAYBREAK_DATABASE_URL"
    connect_timeout_seconds: int = Field(default=5, gt=0, le=60)


class RecorderSettings(StrictSettings):
    enabled: bool = False
    start_time_et: str = "03:55:00"
    feature_window_start_et: str = "04:00:00"
    feature_snapshot_time_et: str = "09:23:00"


class FeatureSettings(StrictSettings):
    enabled: bool = True
    snapshot_time_et: str = "09:23:00"
    max_evaluator_candidates: int = Field(default=20, ge=1, le=25)
    hard_max_evaluator_candidates: int = Field(default=25, ge=1, le=25)
    allow_single_source_float: bool = True


class EvaluatorSettings(StrictSettings):
    enabled: bool = False
    api_key_env: str = "OPENAI_API_KEY"
    primary_model: str = "gpt-5.6-terra"
    shadow_model: str | None = "gpt-5.6-sol"
    run_shadow: bool = True
    response_cutoff_time_et: str = "09:26:30"
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "low"
    max_output_tokens: int = Field(default=64000, ge=1000, le=128000)
    max_attempts: int = Field(default=2, ge=1, le=2)
    request_timeout_seconds: float = Field(default=90.0, gt=0, le=300)
    shadow_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    store_raw_provider_response: bool = True


class RiskSettings(StrictSettings):
    enabled: bool = False
    profile_name: Literal["paper_v1", "live_pilot_v1"] = "paper_v1"
    persist_reservations: bool = True


class ExecutionSettings(StrictSettings):
    enabled: bool = False
    mode: Literal["paper"] = "paper"
    api_key_env: str = "APCA_API_KEY_ID"
    secret_key_env: str = "APCA_API_SECRET_KEY"
    base_url: Literal["https://paper-api.alpaca.markets"] = "https://paper-api.alpaca.markets"
    request_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    cancel_unfilled_after_seconds: int = Field(default=10, gt=0, le=120)
    partial_fill_protection_enabled: bool = True


class OrchestrationSettings(StrictSettings):
    enabled: bool = False
    holder_id: str = "daybreak-orchestrator-1"
    recorder_warmup_time_et: str = "03:55:00"
    feature_window_start_time_et: str = "04:00:00"
    feature_snapshot_time_et: str = "09:23:00"
    evaluator_cutoff_time_et: str = "09:26:30"
    eligibility_lock_time_et: str = "09:29:30"
    regular_session_open_time_et: str = "09:30:00"
    new_entry_cutoff_time_et: str = "09:31:30"
    mandatory_flatten_time_et: str = "15:50:00"
    final_flatten_deadline_et: str = "15:55:00"
    leadership_ttl_seconds: int = Field(default=30, ge=5, le=300)
    leadership_renew_interval_seconds: int = Field(default=10, ge=1, le=60)
    flatten_poll_interval_seconds: float = Field(default=1.0, gt=0, le=30)
    flatten_verification_timeout_seconds: float = Field(default=300.0, gt=0, le=600)
    alert_dedup_window_seconds: int = Field(default=300, ge=0, le=3600)


class OperationsSettings(StrictSettings):
    enabled: bool = False
    heartbeat_interval_seconds: int = Field(default=5, ge=1, le=60)
    max_heartbeat_gap_seconds: int = Field(default=20, ge=2, le=300)
    minimum_free_disk_bytes: int = Field(default=5_000_000_000, ge=100_000_000)
    minimum_file_descriptor_limit: int = Field(default=4096, ge=256)
    required_backup_retention_count: int = Field(default=7, ge=1, le=365)

    @model_validator(mode="after")
    def heartbeat_window_is_coherent(self) -> OperationsSettings:
        if self.max_heartbeat_gap_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("max heartbeat gap must exceed heartbeat interval")
        return self


class AnalyticsSettings(StrictSettings):
    enabled: bool = False
    minimum_sessions: int = Field(default=30, ge=1, le=365)
    minimum_filled_orders: int = Field(default=50, ge=1, le=10000)
    minimum_clean_session_rate: float = Field(default=1.0, ge=0, le=1)
    required_drill_count: int = Field(default=7, ge=0, le=32)


class ProductionSettings(StrictSettings):
    enabled: bool = False
    minimum_tests_collected: int = Field(default=250, ge=1)
    minimum_schema_count: int = Field(default=47, ge=1)
    require_independent_review: bool = True


class SafetySettings(StrictSettings):
    live_execution_enabled: bool = False
    require_ntp_sync: bool = True
    max_clock_skew_ms: int = Field(default=250, gt=0, le=5000)


class DaybreakSettings(StrictSettings):
    runtime: RuntimeSettings = RuntimeSettings()
    paths: PathSettings = PathSettings()
    database: DatabaseSettings = DatabaseSettings()
    recorder: RecorderSettings = RecorderSettings()
    features: FeatureSettings = FeatureSettings()
    evaluator: EvaluatorSettings = EvaluatorSettings()
    risk: RiskSettings = RiskSettings()
    execution: ExecutionSettings = ExecutionSettings()
    orchestration: OrchestrationSettings = OrchestrationSettings()
    operations: OperationsSettings = OperationsSettings()
    analytics: AnalyticsSettings = AnalyticsSettings()
    production: ProductionSettings = ProductionSettings()
    safety: SafetySettings = SafetySettings()

    @model_validator(mode="after")
    def protect_live_environment(self) -> DaybreakSettings:
        if self.safety.live_execution_enabled:
            raise ValueError("v1.0.2 is paper-only; live_execution_enabled must remain false")
        if self.execution.enabled and self.runtime.environment is Environment.LIVE:
            raise ValueError("v1.0.2 paper execution cannot run under the live environment profile")
        return self

    def public_dict(self) -> dict[str, object]:
        """Return deterministic non-secret settings suitable for logs and hashes."""
        return self.model_dump(mode="json")

    def configuration_hash(self) -> str:
        return canonical_sha256(self.public_dict())


def _normalize_toml_types(data: dict[str, object]) -> None:
    runtime = data.get("runtime")
    if isinstance(runtime, dict) and isinstance(runtime.get("environment"), str):
        runtime["environment"] = Environment(runtime["environment"])

    paths = data.get("paths")
    if isinstance(paths, dict):
        for key in ("state_dir", "artifact_dir", "spec_path"):
            value = paths.get(key)
            if isinstance(value, str):
                paths[key] = Path(value)


def _overlay_environment(data: dict[str, object], environ: Mapping[str, str]) -> None:
    mapping: tuple[tuple[str, str, str, object], ...] = (
        ("DAYBREAK_ENVIRONMENT", "runtime", "environment", str),
        ("DAYBREAK_LOG_LEVEL", "runtime", "log_level", str),
        ("DAYBREAK_JSON_LOGS", "runtime", "json_logs", _parse_bool),
        ("DAYBREAK_DATABASE_ENABLED", "database", "enabled", _parse_bool),
        ("DAYBREAK_RECORDER_ENABLED", "recorder", "enabled", _parse_bool),
        ("DAYBREAK_FEATURES_ENABLED", "features", "enabled", _parse_bool),
        ("DAYBREAK_EVALUATOR_ENABLED", "evaluator", "enabled", _parse_bool),
        ("DAYBREAK_EVALUATOR_RUN_SHADOW", "evaluator", "run_shadow", _parse_bool),
        ("DAYBREAK_EVALUATOR_PRIMARY_MODEL", "evaluator", "primary_model", str),
        ("DAYBREAK_EVALUATOR_SHADOW_MODEL", "evaluator", "shadow_model", str),
        ("DAYBREAK_RISK_ENABLED", "risk", "enabled", _parse_bool),
        ("DAYBREAK_RISK_PROFILE", "risk", "profile_name", str),
        ("DAYBREAK_EXECUTION_ENABLED", "execution", "enabled", _parse_bool),
        ("DAYBREAK_ORCHESTRATION_ENABLED", "orchestration", "enabled", _parse_bool),
        ("DAYBREAK_ORCHESTRATION_HOLDER_ID", "orchestration", "holder_id", str),
        ("DAYBREAK_OPERATIONS_ENABLED", "operations", "enabled", _parse_bool),
        ("DAYBREAK_ANALYTICS_ENABLED", "analytics", "enabled", _parse_bool),
        ("DAYBREAK_PRODUCTION_ENABLED", "production", "enabled", _parse_bool),
        ("DAYBREAK_REQUIRE_NTP_SYNC", "safety", "require_ntp_sync", _parse_bool),
    )
    for env_name, section, key, parser in mapping:
        raw = environ.get(env_name)
        if raw is None:
            continue
        section_dict = data.setdefault(section, {})
        if not isinstance(section_dict, dict):
            raise ConfigurationError(f"Configuration section {section!r} must be a table")
        section_dict[key] = parser(raw)  # type: ignore[operator]


def _parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"Invalid Boolean environment value: {raw!r}")


def load_settings(
    path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> DaybreakSettings:
    config_path = Path(path)
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Configuration file not found: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Invalid TOML in {config_path}: {exc}") from exc

    _overlay_environment(raw, os.environ if environ is None else environ)
    _normalize_toml_types(raw)
    try:
        return DaybreakSettings.model_validate(raw)
    except Exception as exc:
        raise ConfigurationError(f"Invalid Daybreak configuration: {exc}") from exc
