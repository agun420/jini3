"""Strict recorder-domain models."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .canonical import canonical_json_bytes, ensure_utc, sha256_hex

EVENT_NAMESPACE = UUID("6d38d616-616d-4b8a-bd7b-64a48cbf36ce")
NY = ZoneInfo("America/New_York")


class RecorderSource(StrEnum):
    ALPACA_SIP = "alpaca_sip"
    ALPACA_NEWS = "alpaca_news"
    ALPACA_TRADING = "alpaca_trading"
    SEC_EDGAR = "sec_edgar"
    SYSTEM = "system"


class EventType(StrEnum):
    TRADE = "trade"
    QUOTE = "quote"
    MINUTE_BAR = "minute_bar"
    UPDATED_BAR = "updated_bar"
    DAILY_BAR = "daily_bar"
    TRADING_STATUS = "trading_status"
    TRADE_CANCEL = "trade_cancel"
    TRADE_CORRECTION = "trade_correction"
    NEWS = "news"
    TRADE_UPDATE = "trade_update"
    SEC_SUBMISSIONS_SNAPSHOT = "sec_submissions_snapshot"
    SEC_SUBMISSION = "sec_submission"
    STREAM_CONNECTED = "stream_connected"
    STREAM_DISCONNECTED = "stream_disconnected"
    SUBSCRIPTION_MANIFEST = "subscription_manifest"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class SessionStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    COMPLETED_PARTIAL = "completed_partial"
    FAILED = "failed"
    SKIPPED_NON_TRADING_DAY = "skipped_non_trading_day"


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class RawEvent(StrictFrozenModel):
    schema_version: Literal["raw_event_v1"] = "raw_event_v1"
    event_id: UUID
    ingest_session_id: UUID
    connection_id: UUID
    source: RecorderSource
    channel: str = Field(min_length=1, max_length=64)
    event_type: EventType
    symbol: str | None = Field(default=None, min_length=1, max_length=32)
    symbols: tuple[str, ...] = ()
    provider_event_id: str | None = Field(default=None, max_length=256)
    event_timestamp: datetime
    received_at: datetime
    trading_date: date
    sequence_hint: int | None = Field(default=None, ge=0)
    payload: dict[str, Any]
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("event_timestamp", "received_at")
    @classmethod
    def validate_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("symbols must be unique")
        for symbol in value:
            if not symbol or len(symbol) > 32:
                raise ValueError("each symbol must contain 1-32 characters")
        return value

    @model_validator(mode="after")
    def validate_integrity(self) -> RawEvent:
        expected_hash = sha256_hex(self.payload)
        if self.payload_sha256 != expected_hash:
            raise ValueError("payload_sha256 does not match payload")
        identity = {
            "ingest_session_id": self.ingest_session_id,
            "source": self.source.value,
            "channel": self.channel,
            "event_type": self.event_type.value,
            "symbols": self.symbols,
            "provider_event_id": self.provider_event_id,
            "event_timestamp": self.event_timestamp,
            "payload_sha256": self.payload_sha256,
        }
        expected_key = sha256_hex(identity)
        if self.idempotency_key != expected_key:
            raise ValueError("idempotency_key does not match event identity")
        if self.event_id != uuid5(EVENT_NAMESPACE, expected_key):
            raise ValueError("event_id does not match deterministic event identity")
        if self.trading_date != self.event_timestamp.astimezone(NY).date():
            raise ValueError(
                "trading_date must be derived from event_timestamp in America/New_York"
            )
        if self.symbol is not None and self.symbol not in self.symbols:
            raise ValueError("primary symbol must be present in symbols")
        return self

    @classmethod
    def create(
        cls,
        *,
        ingest_session_id: UUID,
        connection_id: UUID,
        source: RecorderSource,
        channel: str,
        event_type: EventType,
        event_timestamp: datetime,
        received_at: datetime,
        payload: dict[str, Any],
        symbols: tuple[str, ...] = (),
        provider_event_id: str | None = None,
        sequence_hint: int | None = None,
    ) -> RawEvent:
        event_timestamp = ensure_utc(event_timestamp)
        received_at = ensure_utc(received_at)
        ordered_symbols = tuple(dict.fromkeys(symbols))
        primary_symbol = ordered_symbols[0] if ordered_symbols else None
        payload_hash = sha256_hex(payload)
        identity = {
            "ingest_session_id": ingest_session_id,
            "source": source.value,
            "channel": channel,
            "event_type": event_type.value,
            "symbols": ordered_symbols,
            "provider_event_id": provider_event_id,
            "event_timestamp": event_timestamp,
            "payload_sha256": payload_hash,
        }
        idempotency_key = sha256_hex(identity)
        return cls(
            event_id=uuid5(EVENT_NAMESPACE, idempotency_key),
            ingest_session_id=ingest_session_id,
            connection_id=connection_id,
            source=source,
            channel=channel,
            event_type=event_type,
            symbol=primary_symbol,
            symbols=ordered_symbols,
            provider_event_id=provider_event_id,
            event_timestamp=event_timestamp,
            received_at=received_at,
            trading_date=event_timestamp.astimezone(NY).date(),
            sequence_hint=sequence_hint,
            payload=payload,
            payload_sha256=payload_hash,
            idempotency_key=idempotency_key,
        )


class RawIngestFailure(StrictFrozenModel):
    schema_version: Literal["raw_ingest_failure_v1"] = "raw_ingest_failure_v1"
    failure_id: UUID = Field(default_factory=uuid4)
    ingest_session_id: UUID
    connection_id: UUID | None = None
    source: RecorderSource
    channel: str = Field(min_length=1, max_length=64)
    received_at: datetime
    error_type: str = Field(min_length=1, max_length=128)
    error_message: str = Field(min_length=1, max_length=4096)
    raw_payload: Any | None = None
    raw_payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("received_at")
    @classmethod
    def validate_received_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def validate_hash(self) -> RawIngestFailure:
        if self.raw_payload is None and self.raw_payload_sha256 is not None:
            raise ValueError("raw_payload_sha256 requires raw_payload")
        if self.raw_payload is not None:
            expected = sha256_hex(self.raw_payload)
            if self.raw_payload_sha256 != expected:
                raise ValueError("raw_payload_sha256 does not match raw_payload")
        return self

    @classmethod
    def create(cls, **kwargs: Any) -> RawIngestFailure:
        raw_payload = kwargs.get("raw_payload")
        kwargs["raw_payload_sha256"] = sha256_hex(raw_payload) if raw_payload is not None else None
        return cls(**kwargs)


class SubscriptionManifest(StrictFrozenModel):
    schema_version: Literal["subscription_manifest_v1"] = "subscription_manifest_v1"
    manifest_id: UUID = Field(default_factory=uuid4)
    ingest_session_id: UUID
    version: int = Field(ge=1)
    effective_at: datetime
    feed: Literal["sip"] = "sip"
    wildcard_minute_bars: bool = True
    wildcard_trading_statuses: bool = True
    wildcard_quotes: Literal[False] = False
    wildcard_trades: Literal[False] = False
    tick_symbols: tuple[str, ...] = ()
    news_symbols: tuple[str, ...] = ("*",)
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("effective_at")
    @classmethod
    def validate_effective_at(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("tick_symbols", "news_symbols")
    @classmethod
    def unique_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("subscription symbols must be unique")
        return value


class IngestSession(StrictFrozenModel):
    ingest_session_id: UUID = Field(default_factory=uuid4)
    trading_date: date
    scheduled_start: datetime
    scheduled_stop: datetime
    started_at: datetime
    ended_at: datetime | None = None
    status: SessionStatus = SessionStatus.STARTING
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    host_name: str = Field(min_length=1, max_length=255)
    process_id: int = Field(gt=0)
    alpaca_feed: Literal["sip"] = "sip"
    error_message: str | None = Field(default=None, max_length=4096)

    @field_validator("scheduled_start", "scheduled_stop", "started_at", "ended_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_order(self) -> IngestSession:
        if self.scheduled_stop <= self.scheduled_start:
            raise ValueError("scheduled_stop must be after scheduled_start")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not precede started_at")
        return self


class AppendBatchResult(StrictFrozenModel):
    attempted: int = Field(ge=0)
    inserted: int = Field(ge=0)
    duplicates: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> AppendBatchResult:
        if self.inserted + self.duplicates != self.attempted:
            raise ValueError("inserted + duplicates must equal attempted")
        return self


class PersistedRawEvent(StrictFrozenModel):
    ingest_seq: int = Field(gt=0)
    event: RawEvent


def payload_bytes(event: RawEvent) -> bytes:
    return canonical_json_bytes(event.payload)
