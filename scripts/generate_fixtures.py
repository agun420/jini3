"""Regenerate deterministic analytics and release example fixtures."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daybreak_analytics.acceptance import (
    build_deployment_evidence_report,
    build_paper_acceptance_ledger,
)
from daybreak_analytics.analytics import analyze_session
from daybreak_analytics.canonical import canonical_json_text as analytics_json
from daybreak_analytics.models import (
    AnalyticsPolicy,
    DeploymentEvidenceRequest,
    PaperAcceptanceRequest,
)
from daybreak_operations.enums import DrillType
from daybreak_release.canonical import canonical_json_text as release_json
from daybreak_release.enums import FindingStatus, ReviewSeverity
from daybreak_release.models import ReviewFinding
from daybreak_release.review import review_production_candidate
from tests.analytics.helpers import H, make_replay, make_session
from tests.release.helpers import HASHES, NOW, make_request


def _write(path: Path, text: str) -> None:
    path.write_text(text + "\n", encoding="utf-8")


def main() -> int:
    analytics_dir = ROOT / "fixtures" / "analytics"
    release_dir = ROOT / "fixtures" / "release"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    release_dir.mkdir(parents=True, exist_ok=True)

    sessions = tuple(make_session(index=index) for index in range(2))
    replays = tuple(make_replay(session) for session in sessions)
    paper_request = PaperAcceptanceRequest(
        generated_at=NOW,
        policy=AnalyticsPolicy(
            minimum_sessions=2,
            minimum_filled_orders=4,
            minimum_clean_session_rate=Decimal("1"),
            required_drill_count=2,
        ),
        sessions=sessions,
        replay_reports=replays,
        target_acceptance_verified=True,
        restore_validation_verified=True,
        passed_drills=(
            DrillType.DATABASE_DISCONNECT,
            DrillType.PROCESS_RESTART,
        ),
        configuration_hash=H,
    )
    paper_ledger = build_paper_acceptance_ledger(paper_request)
    deployment_request = DeploymentEvidenceRequest(
        generated_at=NOW,
        release_version="1.0.2",
        configuration_hash=H,
        source_archive_sha256=HASHES["source_archive"],
        wheel_sha256=HASHES["wheel"],
        migrations_sha256=HASHES["migrations"],
        schemas_bundle_sha256=HASHES["schemas_bundle"],
        verification_report_sha256=HASHES["verification_report"],
        specification_sha256=HASHES["specification"],
        migration_head="0009_phase9_release",
        tests_collected=303,
        tests_passed=303,
        schema_count=57,
        secret_findings=0,
        paper_ledger=paper_ledger,
        target_acceptance_verified=False,
        restore_validation_verified=False,
        required_drills_verified=False,
        online_paper_account_verified=False,
        postgres_verified=False,
        ntp_verified=False,
    )
    deployment_report = build_deployment_evidence_report(deployment_request)

    _write(analytics_dir / "session_evidence.json", analytics_json(sessions[0]))
    _write(
        analytics_dir / "session_performance.json",
        analytics_json(analyze_session(sessions[0])),
    )
    _write(analytics_dir / "replay_report.json", analytics_json(replays[0]))
    _write(analytics_dir / "paper_ledger_request.json", analytics_json(paper_request))
    _write(analytics_dir / "paper_ledger.json", analytics_json(paper_ledger))
    _write(
        analytics_dir / "deployment_request_offline.json",
        analytics_json(deployment_request),
    )
    _write(
        analytics_dir / "deployment_report_offline.json",
        analytics_json(deployment_report),
    )

    candidate = make_request()
    blocked_finding = ReviewFinding(
        finding_id="FINDING-BLOCK-001",
        severity=ReviewSeverity.HIGH,
        status=FindingStatus.OPEN,
        category="execution",
        title="Representative unresolved high-severity finding",
        owner="independent-review",
    )
    blocked_candidate = make_request(findings=(blocked_finding,))
    _write(
        release_dir / "production_candidate_request.json",
        release_json(candidate),
    )
    _write(
        release_dir / "production_candidate_report.json",
        release_json(review_production_candidate(candidate)),
    )
    _write(
        release_dir / "production_candidate_request_blocked.json",
        release_json(blocked_candidate),
    )
    _write(
        release_dir / "production_candidate_report_blocked.json",
        release_json(review_production_candidate(blocked_candidate)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
