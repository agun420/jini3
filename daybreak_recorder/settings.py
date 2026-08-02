"""Environment-backed recorder settings without hidden defaults for secrets."""

from __future__ import annotations

import os
import re
from datetime import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .canonical import sha256_hex


class RecorderSettings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    environment: str = "development"
    database_url: str = "postgresql+psycopg://daybreak:daybreak@localhost:5432/daybreak"

    alpaca_api_key: SecretStr | None = None
    alpaca_secret_key: SecretStr | None = None
    alpaca_paper: bool = True
    alpaca_feed: str = "sip"

    timezone_name: str = "America/New_York"
    capture_start_et: time = time(4, 0)
    capture_stop_et: time = time(16, 5)
    preconnect_lead_seconds: int = Field(default=300, ge=0, le=1_800)

    queue_maxsize: int = Field(default=100_000, ge=1_000)
    batch_size: int = Field(default=1_000, ge=1, le=10_000)
    flush_interval_seconds: float = Field(default=0.25, gt=0, le=10)
    enqueue_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    shutdown_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    stream_connect_timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    wildcard_minute_bars: bool = True
    wildcard_trading_statuses: bool = True
    tick_symbols: tuple[str, ...] = ()
    news_symbols: tuple[str, ...] = ("*",)
    max_tick_symbols: int = Field(default=500, ge=1, le=10_000)

    sec_user_agent: str | None = None
    sec_ciks: tuple[str, ...] = ()
    sec_poll_interval_seconds: float = Field(default=60.0, ge=5.0)
    sec_bootstrap_lookback_hours: float = Field(default=96.0, gt=0, le=720.0)
    sec_requests_per_second: float = Field(default=5.0, gt=0, le=10.0)
    sec_timeout_seconds: float = Field(default=15.0, gt=0, le=60.0)

    log_level: str = "INFO"
    state_directory: Path = Path("./state")

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("DAYBREAK_DATABASE_URL must use PostgreSQL with psycopg")
        if not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError("database URL must include a host and database name")
        return value

    @field_validator("alpaca_feed")
    @classmethod
    def validate_feed(cls, value: str) -> str:
        if value.lower() != "sip":
            raise ValueError("Phase 1 requires the SIP feed")
        return "sip"

    @field_validator("tick_symbols", "news_symbols")
    @classmethod
    def normalize_symbol_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(symbol.strip().upper() for symbol in value if symbol.strip())
        if len(normalized) != len(set(normalized)):
            raise ValueError("symbol lists must be unique after normalization")
        return normalized

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone_name(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @field_validator("sec_ciks")
    @classmethod
    def validate_ciks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for cik in value:
            digits = cik.strip().removeprefix("CIK")
            if not digits.isdigit() or len(digits) > 10:
                raise ValueError(f"invalid SEC CIK: {cik}")
            normalized.append(digits.zfill(10))
        if len(normalized) != len(set(normalized)):
            raise ValueError("SEC CIK list contains duplicates")
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_limits(self) -> RecorderSettings:
        ticker_pattern = re.compile(r"^[A-Z0-9](?:[A-Z0-9.-]{0,13}[A-Z0-9])?$")
        if len(self.tick_symbols) > self.max_tick_symbols:
            raise ValueError("tick_symbols exceeds max_tick_symbols")
        if "*" in self.tick_symbols:
            raise ValueError("wildcard trades and quotes are prohibited in tick_symbols")
        invalid_ticks = [
            symbol for symbol in self.tick_symbols if not ticker_pattern.fullmatch(symbol)
        ]
        if invalid_ticks:
            raise ValueError(f"invalid tick_symbols: {invalid_ticks}")
        if not self.news_symbols:
            raise ValueError("news_symbols must contain at least one symbol or '*'")
        invalid_news = [
            symbol
            for symbol in self.news_symbols
            if symbol != "*" and not ticker_pattern.fullmatch(symbol)
        ]
        if invalid_news:
            raise ValueError(f"invalid news_symbols: {invalid_news}")
        if self.sec_ciks and not (self.sec_user_agent and self.sec_user_agent.strip()):
            raise ValueError("sec_user_agent is required when sec_ciks is configured")
        if self.capture_stop_et <= self.capture_start_et:
            raise ValueError("capture_stop_et must be later than capture_start_et")
        return self

    @property
    def redacted_database_url(self) -> str:
        parsed = urlsplit(self.database_url)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        auth = f"{quote(parsed.username, safe='')}@" if parsed.username else ""
        port = f":{parsed.port}" if parsed.port is not None else ""
        return urlunsplit(
            (parsed.scheme, f"{auth}{host}{port}", parsed.path, parsed.query, parsed.fragment)
        )

    @property
    def configuration_hash(self) -> str:
        public = self.model_dump(
            mode="python",
            exclude={"alpaca_api_key", "alpaca_secret_key", "database_url"},
        )
        public["database_url"] = self.redacted_database_url
        public["alpaca_api_key_present"] = self.alpaca_api_key is not None
        public["alpaca_secret_key_present"] = self.alpaca_secret_key is not None
        return sha256_hex(public)

    def require_alpaca_credentials(self) -> tuple[str, str]:
        if self.alpaca_api_key is None or self.alpaca_secret_key is None:
            raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
        return self.alpaca_api_key.get_secret_value(), self.alpaca_secret_key.get_secret_value()

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> RecorderSettings:
        env = environ if environ is not None else dict(os.environ)

        def csv(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
            raw = env.get(name)
            if raw is None:
                return default
            return tuple(part for part in raw.split(",") if part.strip())

        def as_bool(name: str, default: bool) -> bool:
            raw = env.get(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        def as_time(name: str, default: time) -> time:
            raw = env.get(name)
            if raw is None:
                return default
            return time.fromisoformat(raw)

        values: dict[str, Any] = {
            "environment": env.get("DAYBREAK_ENVIRONMENT", "development"),
            "database_url": env.get(
                "DAYBREAK_DATABASE_URL",
                "postgresql+psycopg://daybreak:daybreak@localhost:5432/daybreak",
            ),
            "alpaca_api_key": SecretStr(env["ALPACA_API_KEY"])
            if env.get("ALPACA_API_KEY")
            else None,
            "alpaca_secret_key": SecretStr(env["ALPACA_SECRET_KEY"])
            if env.get("ALPACA_SECRET_KEY")
            else None,
            "alpaca_paper": as_bool("ALPACA_PAPER", True),
            "alpaca_feed": env.get("ALPACA_DATA_FEED", "sip"),
            "timezone_name": env.get("DAYBREAK_TIMEZONE", "America/New_York"),
            "capture_start_et": as_time("DAYBREAK_CAPTURE_START_ET", time(4, 0)),
            "capture_stop_et": as_time("DAYBREAK_CAPTURE_STOP_ET", time(16, 5)),
            "preconnect_lead_seconds": int(env.get("DAYBREAK_PRECONNECT_LEAD_SECONDS", "300")),
            "queue_maxsize": int(env.get("DAYBREAK_QUEUE_MAXSIZE", "100000")),
            "batch_size": int(env.get("DAYBREAK_BATCH_SIZE", "1000")),
            "flush_interval_seconds": float(env.get("DAYBREAK_FLUSH_INTERVAL_SECONDS", "0.25")),
            "enqueue_timeout_seconds": float(env.get("DAYBREAK_ENQUEUE_TIMEOUT_SECONDS", "5")),
            "shutdown_timeout_seconds": float(env.get("DAYBREAK_SHUTDOWN_TIMEOUT_SECONDS", "15")),
            "stream_connect_timeout_seconds": float(
                env.get("DAYBREAK_STREAM_CONNECT_TIMEOUT_SECONDS", "20")
            ),
            "wildcard_minute_bars": as_bool("DAYBREAK_WILDCARD_MINUTE_BARS", True),
            "wildcard_trading_statuses": as_bool("DAYBREAK_WILDCARD_TRADING_STATUSES", True),
            "tick_symbols": csv("DAYBREAK_TICK_SYMBOLS"),
            "news_symbols": csv("DAYBREAK_NEWS_SYMBOLS", ("*",)),
            "max_tick_symbols": int(env.get("DAYBREAK_MAX_TICK_SYMBOLS", "500")),
            "sec_user_agent": env.get("SEC_USER_AGENT"),
            "sec_ciks": csv("DAYBREAK_SEC_CIKS"),
            "sec_poll_interval_seconds": float(env.get("DAYBREAK_SEC_POLL_INTERVAL_SECONDS", "60")),
            "sec_bootstrap_lookback_hours": float(
                env.get("DAYBREAK_SEC_BOOTSTRAP_LOOKBACK_HOURS", "96")
            ),
            "sec_requests_per_second": float(env.get("DAYBREAK_SEC_REQUESTS_PER_SECOND", "5")),
            "sec_timeout_seconds": float(env.get("DAYBREAK_SEC_TIMEOUT_SECONDS", "15")),
            "log_level": env.get("DAYBREAK_LOG_LEVEL", "INFO"),
            "state_directory": Path(env.get("DAYBREAK_STATE_DIRECTORY", "./state")),
        }
        return cls.model_validate(values)
