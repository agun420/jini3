from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from .canonical import canonical_sha256
from .enums import AlertSeverity
from .models import AlertRecord


class AlertSink(Protocol):
    def send(self, alert: AlertRecord) -> None: ...


class LoggingAlertSink:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("daybreak.orchestration.alerts")

    def send(self, alert: AlertRecord) -> None:
        level = {
            AlertSeverity.INFO: logging.INFO,
            AlertSeverity.WARNING: logging.WARNING,
            AlertSeverity.CRITICAL: logging.CRITICAL,
        }[alert.severity]
        self._logger.log(
            level,
            "%s: %s",
            alert.code,
            alert.message,
            extra={"daybreak_alert": alert.model_dump(mode="json")},
        )


class CompositeAlertSink:
    def __init__(self, *sinks: AlertSink) -> None:
        self._sinks = sinks

    def send(self, alert: AlertRecord) -> None:
        errors: list[Exception] = []
        for sink in self._sinks:
            try:
                sink.send(alert)
            except Exception as exc:  # alert delivery must not suppress other sinks
                errors.append(exc)
        if errors and len(errors) == len(self._sinks):
            raise RuntimeError("all alert sinks failed") from errors[0]


class MemoryAlertSink:
    def __init__(self) -> None:
        self.alerts: list[AlertRecord] = []

    def send(self, alert: AlertRecord) -> None:
        self.alerts.append(alert)


class AlertManager:
    def __init__(self, sink: AlertSink, *, dedup_window_seconds: int = 300) -> None:
        self._sink = sink
        self._dedup_window = timedelta(seconds=dedup_window_seconds)
        self._last_sent: dict[str, datetime] = {}

    def emit(
        self,
        *,
        session_id: str,
        severity: AlertSeverity,
        code: str,
        message: str,
        now: datetime,
        details: dict[str, object] | None = None,
        dedup_key: str | None = None,
    ) -> AlertRecord | None:
        now = now.astimezone(UTC)
        key = dedup_key or f"{session_id}:{code}"
        previous = self._last_sent.get(key)
        if previous is not None and now - previous < self._dedup_window:
            return None
        core = {
            "session_id": session_id,
            "severity": severity,
            "code": code,
            "message": message,
            "created_at": now,
            "dedup_key": key,
            "details": details or {},
        }
        alert_hash = canonical_sha256(core)
        alert_id = uuid5(NAMESPACE_URL, f"daybreak-alert:{alert_hash}").hex
        alert = AlertRecord.model_validate({**core, "alert_id": alert_id, "alert_hash": alert_hash})
        self._last_sent[key] = now
        self._sink.send(alert)
        return alert
