from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from daybreak_analytics.acceptance import (
    build_deployment_evidence_report,
    build_paper_acceptance_ledger,
)
from daybreak_analytics.models import (
    AnalyticsPolicy,
    DeploymentEvidenceRequest,
    PaperAcceptanceRequest,
)
from daybreak_operations.enums import DrillType
from daybreak_release.canonical import canonical_sha256
from daybreak_release.enums import ApprovalRole
from daybreak_release.models import (
    ApprovalAttestation,
    ArtifactEvidence,
    BuildAttestation,
    ConfigurationFreeze,
    EvidenceManifest,
    ProductionCandidateRequest,
    RollbackEvidence,
)
from tests.analytics.helpers import H, make_replay, make_session

NOW = datetime(2026, 8, 1, 22, 0, tzinfo=UTC)
HASHES = {
    "source_archive": "b" * 64,
    "wheel": "c" * 64,
    "migrations": "d" * 64,
    "schemas_bundle": "e" * 64,
    "verification_report": "f" * 64,
    "specification": "1" * 64,
}


def make_paper_ledger():
    sessions = tuple(make_session(index=i) for i in range(2))
    reports = tuple(make_replay(item) for item in sessions)
    request = PaperAcceptanceRequest(
        generated_at=NOW,
        policy=AnalyticsPolicy(
            minimum_sessions=2,
            minimum_filled_orders=4,
            minimum_clean_session_rate=Decimal("1"),
            required_drill_count=2,
        ),
        sessions=sessions,
        replay_reports=reports,
        target_acceptance_verified=True,
        restore_validation_verified=True,
        passed_drills=(DrillType.DATABASE_DISCONNECT, DrillType.PROCESS_RESTART),
        configuration_hash=H,
    )
    return build_paper_acceptance_ledger(request)


def make_deployment(ledger):
    return build_deployment_evidence_report(
        DeploymentEvidenceRequest(
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
            paper_ledger=ledger,
            target_acceptance_verified=True,
            restore_validation_verified=True,
            required_drills_verified=True,
            online_paper_account_verified=True,
            postgres_verified=True,
            ntp_verified=True,
        )
    )


def make_manifest():
    artifacts = tuple(
        ArtifactEvidence(name=name, sha256=value, size_bytes=100 + index)
        for index, (name, value) in enumerate(sorted(HASHES.items()))
    )
    body = {"generated_at": NOW, "artifacts": artifacts}
    return EvidenceManifest(**body, manifest_hash=canonical_sha256(body))


def make_build(**updates):
    body = {
        "generated_at": NOW,
        "release_version": "1.0.2",
        "specification_version": "6.3",
        "migration_head": "0009_phase9_release",
        "tests_collected": 303,
        "tests_passed": 303,
        "schema_count": 57,
        "secret_findings": 0,
        "clean_install_passed": True,
        "extracted_source_test_passed": True,
        "python_compile_passed": True,
        "wheel_smoke_test_passed": True,
        "source_archive_sha256": HASHES["source_archive"],
        "wheel_sha256": HASHES["wheel"],
        "migrations_sha256": HASHES["migrations"],
        "schemas_bundle_sha256": HASHES["schemas_bundle"],
        "verification_report_sha256": HASHES["verification_report"],
    }
    body.update(updates)
    return BuildAttestation(**body, attestation_hash=canonical_sha256(body))


def make_freeze():
    body = {
        "frozen_at": NOW,
        "release_version": "1.0.2",
        "specification_version": "6.3",
        "environment": "paper",
        "live_execution_enabled": False,
        "configuration_hash": H,
        "specification_sha256": HASHES["specification"],
        "migration_head": "0009_phase9_release",
        "component_versions": (("platform", "1.0.2"), ("release_engine", "1.0.2")),
    }
    return ConfigurationFreeze(**body, freeze_hash=canonical_sha256(body))


def make_rollback(**updates):
    body = {
        "tested_at": NOW,
        "backup_restore_verified": True,
        "previous_wheel_available": True,
        "previous_source_archive_available": True,
        "emergency_flatten_verified": True,
        "database_forward_recovery_verified": True,
        "rollback_plan_sha256": "4" * 64,
    }
    body.update(updates)
    return RollbackEvidence(**body, evidence_hash=canonical_sha256(body))


def make_approvals(manifest_hash: str):
    return tuple(
        ApprovalAttestation(
            role=role,
            reviewer_id=f"reviewer-{role.value}",
            approved=True,
            approved_at=NOW,
            evidence_package_hash=manifest_hash,
        )
        for role in sorted(ApprovalRole, key=lambda item: item.value)
    )


def make_request(**updates):
    ledger = make_paper_ledger()
    manifest = make_manifest()
    body = {
        "generated_at": NOW,
        "evidence_manifest": manifest,
        "build_attestation": make_build(),
        "configuration_freeze": make_freeze(),
        "paper_ledger": ledger,
        "deployment_evidence": make_deployment(ledger),
        "rollback_evidence": make_rollback(),
        "findings": (),
        "approvals": make_approvals(manifest.manifest_hash),
        "independent_review_complete": True,
    }
    body.update(updates)
    return ProductionCandidateRequest(**body)
