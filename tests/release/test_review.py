import pytest
from pydantic import ValidationError

from daybreak_analytics.acceptance import (
    build_deployment_evidence_report,
    deployment_report_body,
)
from daybreak_analytics.canonical import canonical_sha256 as analytics_sha256
from daybreak_analytics.models import DeploymentEvidenceRequest
from daybreak_release.enums import CandidateStatus, FindingStatus, ReviewSeverity
from daybreak_release.models import ReviewFinding
from daybreak_release.review import review_production_candidate

from .helpers import HASHES, NOW, make_build, make_paper_ledger, make_request


def test_complete_evidence_produces_paper_release_candidate():
    report = review_production_candidate(make_request())
    assert report.status is CandidateStatus.PAPER_RELEASE_CANDIDATE
    assert report.paper_release_candidate is True
    assert report.live_capital_eligible is False
    assert report.blockers == ()


def test_missing_approval_is_incomplete():
    request = make_request()
    request = request.model_copy(update={"approvals": request.approvals[:-1]})
    report = review_production_candidate(request)
    assert report.status is CandidateStatus.INCOMPLETE
    assert "REQUIRED_APPROVALS_MISSING" in report.blockers


def test_explicit_rejection_blocks_candidate():
    request = make_request()
    rejected = request.approvals[0].model_copy(update={"approved": False})
    request = request.model_copy(update={"approvals": (rejected,) + request.approvals[1:]})
    report = review_production_candidate(request)
    assert report.status is CandidateStatus.BLOCKED
    assert "EXPLICIT_APPROVAL_REJECTION_PRESENT" in report.blockers


def test_open_high_finding_blocks_candidate():
    finding = ReviewFinding(
        finding_id="FINDING-001",
        severity=ReviewSeverity.HIGH,
        status=FindingStatus.OPEN,
        category="execution",
        title="Unresolved high-severity execution finding",
        owner="engineering",
    )
    report = review_production_candidate(make_request(findings=(finding,)))
    assert report.status is CandidateStatus.BLOCKED
    assert "OPEN_HIGH_FINDINGS_PRESENT" in report.blockers


def test_low_finding_is_warning_only():
    finding = ReviewFinding(
        finding_id="FINDING-001",
        severity=ReviewSeverity.LOW,
        status=FindingStatus.OPEN,
        category="docs",
        title="Minor documentation refinement remains",
        owner="engineering",
    )
    report = review_production_candidate(make_request(findings=(finding,)))
    assert report.paper_release_candidate is True
    assert report.warnings == ("OPEN_LOW_FINDINGS_PRESENT",)


def test_failed_test_suite_blocks_candidate():
    bad_build = make_build(tests_passed=300)
    request = make_request().model_copy(update={"build_attestation": bad_build})
    report = review_production_candidate(request)
    assert report.status is CandidateStatus.BLOCKED
    assert "TEST_SUITE_NOT_GREEN" in report.blockers


def test_invalid_build_attestation_hash_is_detected():
    build = make_build().model_copy(update={"attestation_hash": "9" * 64})
    report = review_production_candidate(make_request(build_attestation=build))
    assert "BUILD_ATTESTATION_HASH_INVALID" in report.blockers


def test_unverified_rollback_is_incomplete():
    request = make_request()
    rollback = request.rollback_evidence.model_copy(update={"backup_restore_verified": False})
    report = review_production_candidate(request.model_copy(update={"rollback_evidence": rollback}))
    assert "ROLLBACK_EVIDENCE_HASH_INVALID" in report.blockers
    assert "ROLLBACK_EVIDENCE_NOT_VERIFIED" in report.blockers


def test_candidate_rejects_deployment_artifact_substitution():
    ledger = make_paper_ledger()
    substituted = build_deployment_evidence_report(
        DeploymentEvidenceRequest(
            generated_at=NOW,
            release_version="1.0.2",
            configuration_hash=ledger.configuration_hash,
            source_archive_sha256="2" * 64,
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
            paper_ledger=ledger,
            target_acceptance_verified=True,
            restore_validation_verified=True,
            required_drills_verified=True,
            online_paper_account_verified=True,
            postgres_verified=True,
            ntp_verified=True,
        )
    )
    with pytest.raises(ValidationError, match="deployment evidence hashes"):
        make_request(paper_ledger=ledger, deployment_evidence=substituted)


def test_review_recomputes_nested_ledger_and_deployment_hashes():
    request = make_request()
    forged_ledger = request.paper_ledger.model_copy(update={"ledger_hash": "9" * 64})
    forged_deployment = request.deployment_evidence.model_copy(update={"report_hash": "8" * 64})
    forged = request.model_copy(
        update={
            "paper_ledger": forged_ledger,
            "deployment_evidence": forged_deployment,
        }
    )

    report = review_production_candidate(forged)

    assert "PAPER_LEDGER_HASH_INVALID" in report.blockers
    assert "DEPLOYMENT_EVIDENCE_HASH_INVALID" in report.blockers


def test_review_rejects_rehashed_deployment_chain_substitution():
    request = make_request()
    substituted_hashes = tuple(
        (name, "2" * 64 if name == "source_archive" else value)
        for name, value in request.deployment_evidence.evidence_hashes
    )
    substituted = request.deployment_evidence.model_copy(
        update={"evidence_hashes": substituted_hashes}
    )
    report_hash = analytics_sha256(deployment_report_body(substituted))
    substituted = substituted.model_copy(
        update={
            "report_hash": report_hash,
            "report_id": f"DE-{report_hash[:20]}",
        }
    )
    forged = request.model_copy(update={"deployment_evidence": substituted})

    report = review_production_candidate(forged)

    assert "DEPLOYMENT_EVIDENCE_HASH_INVALID" not in report.blockers
    assert "DEPLOYMENT_EVIDENCE_CHAIN_MISMATCH" in report.blockers
