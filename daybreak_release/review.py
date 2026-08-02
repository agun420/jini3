from __future__ import annotations

from collections import Counter

from daybreak_analytics.acceptance import deployment_report_body, paper_ledger_body
from daybreak_analytics.canonical import canonical_sha256 as analytics_sha256

from .canonical import canonical_sha256
from .enums import CandidateStatus, FindingStatus, ReviewSeverity
from .models import (
    ProductionCandidateReport,
    ProductionCandidateRequest,
    ReviewSummary,
)

_REQUIRED_ARTIFACTS = frozenset(
    {
        "migrations",
        "schemas_bundle",
        "source_archive",
        "specification",
        "verification_report",
        "wheel",
    }
)


def review_production_candidate(
    request: ProductionCandidateRequest,
) -> ProductionCandidateReport:
    policy = request.policy
    request_hash = canonical_sha256(request)
    blockers: list[str] = []
    warnings: list[str] = []

    manifest_body = {
        "generated_at": request.evidence_manifest.generated_at,
        "artifacts": request.evidence_manifest.artifacts,
    }
    if canonical_sha256(manifest_body) != request.evidence_manifest.manifest_hash:
        blockers.append("EVIDENCE_MANIFEST_HASH_INVALID")

    artifacts = {item.name: item for item in request.evidence_manifest.artifacts}
    missing_artifacts = sorted(_REQUIRED_ARTIFACTS - artifacts.keys())
    if missing_artifacts:
        blockers.append("REQUIRED_ARTIFACTS_MISSING")
    if any(item.required and item.size_bytes <= 0 for item in artifacts.values()):
        blockers.append("REQUIRED_ARTIFACT_EMPTY")

    build = request.build_attestation
    build_body = build.model_dump(mode="python", exclude={"attestation_hash"})
    if canonical_sha256(build_body) != build.attestation_hash:
        blockers.append("BUILD_ATTESTATION_HASH_INVALID")
    if build.tests_collected < policy.minimum_tests_collected:
        blockers.append("MINIMUM_TEST_COUNT_NOT_MET")
    if build.tests_passed != build.tests_collected:
        blockers.append("TEST_SUITE_NOT_GREEN")
    if build.schema_count < policy.minimum_schema_count:
        blockers.append("MINIMUM_SCHEMA_COUNT_NOT_MET")
    if policy.require_zero_secret_findings and build.secret_findings != 0:
        blockers.append("SECRET_FINDINGS_PRESENT")
    if policy.require_clean_install and not build.clean_install_passed:
        blockers.append("CLEAN_INSTALL_NOT_VERIFIED")
    if policy.require_extracted_source_test and not build.extracted_source_test_passed:
        blockers.append("EXTRACTED_SOURCE_TEST_NOT_VERIFIED")
    if policy.require_python_compile and not build.python_compile_passed:
        blockers.append("PYTHON_COMPILE_NOT_VERIFIED")
    if policy.require_wheel_smoke_test and not build.wheel_smoke_test_passed:
        blockers.append("WHEEL_SMOKE_TEST_NOT_VERIFIED")
    if build.migration_head != policy.expected_migration_head:
        blockers.append("MIGRATION_HEAD_MISMATCH")

    expected_artifact_hashes = {
        "migrations": build.migrations_sha256,
        "schemas_bundle": build.schemas_bundle_sha256,
        "source_archive": build.source_archive_sha256,
        "specification": request.configuration_freeze.specification_sha256,
        "verification_report": build.verification_report_sha256,
        "wheel": build.wheel_sha256,
    }
    if any(
        name not in artifacts or artifacts[name].sha256 != expected_hash
        for name, expected_hash in expected_artifact_hashes.items()
    ):
        blockers.append("EVIDENCE_MANIFEST_CHAIN_MISMATCH")

    freeze = request.configuration_freeze
    freeze_body = freeze.model_dump(mode="python", exclude={"freeze_hash"})
    if canonical_sha256(freeze_body) != freeze.freeze_hash:
        blockers.append("CONFIGURATION_FREEZE_HASH_INVALID")
    if freeze.migration_head != policy.expected_migration_head:
        blockers.append("CONFIGURATION_FREEZE_MIGRATION_HEAD_MISMATCH")
    if freeze.environment != "paper" or freeze.live_execution_enabled:
        blockers.append("CONFIGURATION_NOT_PAPER_ONLY")
    if (
        build.release_version != policy.release_version
        or freeze.release_version != policy.release_version
        or build.specification_version != policy.specification_version
        or freeze.specification_version != policy.specification_version
    ):
        blockers.append("RELEASE_METADATA_MISMATCH")

    if policy.require_paper_ledger and not request.paper_ledger.paper_ready:
        blockers.append("PAPER_LEDGER_NOT_QUALIFIED")
    if (
        analytics_sha256(paper_ledger_body(request.paper_ledger))
        != request.paper_ledger.ledger_hash
    ):
        blockers.append("PAPER_LEDGER_HASH_INVALID")
    if request.paper_ledger.ledger_id != f"PL-{request.paper_ledger.ledger_hash[:20]}":
        blockers.append("PAPER_LEDGER_ID_INVALID")
    if (
        policy.require_deployment_evidence
        and not request.deployment_evidence.paper_deployment_ready
    ):
        blockers.append("PAPER_DEPLOYMENT_EVIDENCE_NOT_QUALIFIED")
    if (
        analytics_sha256(deployment_report_body(request.deployment_evidence))
        != request.deployment_evidence.report_hash
    ):
        blockers.append("DEPLOYMENT_EVIDENCE_HASH_INVALID")
    if (
        request.deployment_evidence.report_id
        != f"DE-{request.deployment_evidence.report_hash[:20]}"
    ):
        blockers.append("DEPLOYMENT_EVIDENCE_ID_INVALID")
    if request.deployment_evidence.live_deployment_ready:
        blockers.append("INVALID_LIVE_DEPLOYMENT_EVIDENCE")

    deployment = request.deployment_evidence
    expected_deployment_hashes = {
        "configuration": freeze.configuration_hash,
        "migrations": build.migrations_sha256,
        "paper_ledger": request.paper_ledger.ledger_hash,
        "schemas_bundle": build.schemas_bundle_sha256,
        "source_archive": build.source_archive_sha256,
        "specification": freeze.specification_sha256,
        "verification_report": build.verification_report_sha256,
        "wheel": build.wheel_sha256,
    }
    if (
        deployment.configuration_hash != freeze.configuration_hash
        or request.paper_ledger.configuration_hash != freeze.configuration_hash
        or deployment.paper_ledger_id != request.paper_ledger.ledger_id
        or deployment.paper_ledger_hash != request.paper_ledger.ledger_hash
        or deployment.release_version != policy.release_version
        or deployment.specification_version != policy.specification_version
        or deployment.migration_head != policy.expected_migration_head
        or dict(deployment.evidence_hashes) != expected_deployment_hashes
        or deployment.tests_collected != build.tests_collected
        or deployment.tests_passed != build.tests_passed
        or deployment.schema_count != build.schema_count
        or deployment.secret_findings != build.secret_findings
    ):
        blockers.append("DEPLOYMENT_EVIDENCE_CHAIN_MISMATCH")
    rollback_body = request.rollback_evidence.model_dump(mode="python", exclude={"evidence_hash"})
    if canonical_sha256(rollback_body) != request.rollback_evidence.evidence_hash:
        blockers.append("ROLLBACK_EVIDENCE_HASH_INVALID")
    if policy.require_rollback_validation and not request.rollback_evidence.verified:
        blockers.append("ROLLBACK_EVIDENCE_NOT_VERIFIED")
    if policy.require_independent_review and not request.independent_review_complete:
        blockers.append("INDEPENDENT_REVIEW_INCOMPLETE")

    open_counts = Counter(
        item.severity for item in request.findings if item.status is FindingStatus.OPEN
    )
    if open_counts[ReviewSeverity.MEDIUM] > policy.maximum_open_medium_findings:
        blockers.append("OPEN_MEDIUM_FINDINGS_EXCEED_POLICY")
    if open_counts[ReviewSeverity.HIGH] > policy.maximum_open_high_findings:
        blockers.append("OPEN_HIGH_FINDINGS_PRESENT")
    if open_counts[ReviewSeverity.CRITICAL] > policy.maximum_open_critical_findings:
        blockers.append("OPEN_CRITICAL_FINDINGS_PRESENT")
    if open_counts[ReviewSeverity.LOW]:
        warnings.append("OPEN_LOW_FINDINGS_PRESENT")
    if open_counts[ReviewSeverity.INFO]:
        warnings.append("OPEN_INFORMATIONAL_FINDINGS_PRESENT")

    approved_roles = tuple(
        sorted(
            (item.role for item in request.approvals if item.approved),
            key=lambda item: item.value,
        )
    )
    missing_roles = tuple(
        sorted(
            set(policy.required_approval_roles) - set(approved_roles),
            key=lambda item: item.value,
        )
    )
    if missing_roles:
        blockers.append("REQUIRED_APPROVALS_MISSING")
    if any(not item.approved for item in request.approvals):
        blockers.append("EXPLICIT_APPROVAL_REJECTION_PRESENT")
    if any(
        item.evidence_package_hash != request.evidence_manifest.manifest_hash
        for item in request.approvals
    ):
        blockers.append("APPROVAL_EVIDENCE_CHAIN_MISMATCH")
    if any(
        item.approved_at < request.evidence_manifest.generated_at
        or item.approved_at > request.generated_at
        for item in request.approvals
    ):
        blockers.append("APPROVAL_TIMESTAMP_INVALID")

    summary = ReviewSummary(
        finding_count=len(request.findings),
        open_info_count=open_counts[ReviewSeverity.INFO],
        open_low_count=open_counts[ReviewSeverity.LOW],
        open_medium_count=open_counts[ReviewSeverity.MEDIUM],
        open_high_count=open_counts[ReviewSeverity.HIGH],
        open_critical_count=open_counts[ReviewSeverity.CRITICAL],
        approved_roles=approved_roles,
        missing_roles=missing_roles,
    )

    explicit_failure_codes = {
        "TEST_SUITE_NOT_GREEN",
        "SECRET_FINDINGS_PRESENT",
        "CONFIGURATION_NOT_PAPER_ONLY",
        "INVALID_LIVE_DEPLOYMENT_EVIDENCE",
        "OPEN_HIGH_FINDINGS_PRESENT",
        "OPEN_CRITICAL_FINDINGS_PRESENT",
        "EXPLICIT_APPROVAL_REJECTION_PRESENT",
    }
    if not blockers:
        status = CandidateStatus.PAPER_RELEASE_CANDIDATE
    elif any(item in explicit_failure_codes for item in blockers):
        status = CandidateStatus.BLOCKED
    else:
        status = CandidateStatus.INCOMPLETE

    blockers_tuple = tuple(sorted(set(blockers)))
    warnings_tuple = tuple(sorted(set(warnings)))
    body = {
        "generated_at": request.generated_at,
        "status": status,
        "paper_release_candidate": status is CandidateStatus.PAPER_RELEASE_CANDIDATE,
        "live_capital_eligible": False,
        "blockers": blockers_tuple,
        "warnings": warnings_tuple,
        "release_version": policy.release_version,
        "specification_version": policy.specification_version,
        "configuration_hash": freeze.configuration_hash,
        "evidence_manifest_hash": request.evidence_manifest.manifest_hash,
        "build_attestation_hash": build.attestation_hash,
        "configuration_freeze_hash": freeze.freeze_hash,
        "paper_ledger_id": request.paper_ledger.ledger_id,
        "deployment_report_id": request.deployment_evidence.report_id,
        "review_summary": summary,
        "request_hash": request_hash,
    }
    report_hash = canonical_sha256(body)
    return ProductionCandidateReport.model_validate(
        {
            **body,
            "report_id": f"PC-{report_hash[:20]}",
            "report_hash": report_hash,
        }
    )
