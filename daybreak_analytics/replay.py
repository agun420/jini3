from __future__ import annotations

from .canonical import canonical_sha256
from .enums import ReplayComponent
from .models import FullSessionReplayReport, FullSessionReplayRequest

_REQUIRED = frozenset(ReplayComponent)


def build_full_session_replay_report(request: FullSessionReplayRequest) -> FullSessionReplayReport:
    request_hash = canonical_sha256(request)
    errors: list[str] = []
    present = frozenset(item.component for item in request.components)
    missing = sorted(item.value for item in _REQUIRED - present)
    if missing:
        errors.append("MISSING_COMPONENTS:" + ",".join(missing))
    if request.expected_raw_event_count != request.actual_raw_event_count:
        errors.append("RAW_EVENT_COUNT_MISMATCH")
    if not request.event_ordering_verified:
        errors.append("EVENT_ORDERING_NOT_VERIFIED")
    if not request.point_in_time_integrity_verified:
        errors.append("POINT_IN_TIME_INTEGRITY_NOT_VERIFIED")
    for component in request.components:
        if not component.verified:
            errors.append(f"COMPONENT_FAILED:{component.component.value}")
    complete = present == _REQUIRED
    passed = complete and not errors
    body = {
        "session_id": request.session_id,
        "trading_date": request.trading_date,
        "replayed_at": request.replayed_at,
        "complete": complete,
        "passed": passed,
        "expected_raw_event_count": request.expected_raw_event_count,
        "actual_raw_event_count": request.actual_raw_event_count,
        "event_ordering_verified": request.event_ordering_verified,
        "point_in_time_integrity_verified": request.point_in_time_integrity_verified,
        "components": request.components,
        "errors": tuple(errors),
        "request_hash": request_hash,
    }
    report_hash = canonical_sha256(body)
    return FullSessionReplayReport.model_validate(
        {
            **body,
            "replay_id": f"RP-{report_hash[:20]}",
            "report_hash": report_hash,
        }
    )
