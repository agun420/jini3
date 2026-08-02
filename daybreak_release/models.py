from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from daybreak_analytics.models import DeploymentEvidenceReport, PaperAcceptanceLedger

from .enums import (
    ApprovalRole,
    CandidateStatus,
    FindingStatus,
    ReviewSeverity,
)

HASH = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ID = Annotated[str, Field(min_length=8, max_length=96)]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


class ProductionCandidatePolicy(StrictFrozenModel):
    policy_version: Literal["production_candidate_policy_v1"] = "production_candidate_policy_v1"
    release_version: Literal["1.0.2"] = "1.0.2"
    specification_version: Literal["6.3"] = "6.3"
    mode: Literal["paper"] = "paper"
    expected_migration_head: Literal["0009_phase9_release"] = "0009_phase9_release"
    minimum_tests_collected: Annotated[int, Field(ge=1)] = 250
    minimum_schema_count: Annotated[int, Field(ge=1)] = 47
    require_clean_install: Literal[True] = True
    require_extracted_source_test: Literal[True] = True
    require_python_compile: Literal[True] = True
    require_wheel_smoke_test: Literal[True] = True
    require_zero_secret_findings: Literal[True] = True
    require_paper_ledger: Literal[True] = True
    require_deployment_evidence: Literal[True] = True
    require_rollback_validation: Literal[True] = True
    require_independent_review: Literal[True] = True
    required_approval_roles: tuple[ApprovalRole, ...] = (
        ApprovalRole.ENGINEERING,
        ApprovalRole.INDEPENDENT_REVIEW,
        ApprovalRole.OPERATIONS,
        ApprovalRole.RISK,
        ApprovalRole.SECURITY,
    )
    maximum_open_medium_findings: Annotated[int, Field(ge=0)] = 0
    maximum_open_high_findings: Literal[0] = 0
    maximum_open_critical_findings: Literal[0] = 0
    allow_live_capital_certification: Literal[False] = False

    @field_validator("required_approval_roles")
    @classmethod
    def roles_sorted_unique(cls, value: tuple[ApprovalRole, ...]) -> tuple[ApprovalRole, ...]:
        if tuple(sorted(set(value), key=lambda item: item.value)) != value:
            raise ValueError("required approval roles must be sorted and unique")
        return value


class ArtifactEvidence(StrictFrozenModel):
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    sha256: HASH
    size_bytes: Annotated[int, Field(gt=0)]
    required: bool = True


class EvidenceManifest(StrictFrozenModel):
    generated_at: datetime
    artifacts: tuple[ArtifactEvidence, ...]
    manifest_hash: HASH

    _time = field_validator("generated_at")(_utc)

    @field_validator("artifacts")
    @classmethod
    def artifacts_sorted_unique(
        cls, value: tuple[ArtifactEvidence, ...]
    ) -> tuple[ArtifactEvidence, ...]:
        if tuple(sorted(value, key=lambda item: item.name)) != value:
            raise ValueError("artifacts must be sorted by name")
        if len({item.name for item in value}) != len(value):
            raise ValueError("artifact names must be unique")
        return value


class BuildAttestation(StrictFrozenModel):
    generated_at: datetime
    release_version: Literal["1.0.2"]
    specification_version: Literal["6.3"]
    migration_head: Literal["0009_phase9_release"]
    tests_collected: Annotated[int, Field(gt=0)]
    tests_passed: Annotated[int, Field(ge=0)]
    schema_count: Annotated[int, Field(gt=0)]
    secret_findings: Annotated[int, Field(ge=0)]
    clean_install_passed: bool
    extracted_source_test_passed: bool
    python_compile_passed: bool
    wheel_smoke_test_passed: bool
    source_archive_sha256: HASH
    wheel_sha256: HASH
    migrations_sha256: HASH
    schemas_bundle_sha256: HASH
    verification_report_sha256: HASH
    attestation_hash: HASH

    _time = field_validator("generated_at")(_utc)

    @model_validator(mode="after")
    def coherent(self) -> BuildAttestation:
        if self.tests_passed > self.tests_collected:
            raise ValueError("passed tests cannot exceed collected tests")
        return self


class ConfigurationFreeze(StrictFrozenModel):
    frozen_at: datetime
    release_version: Literal["1.0.2"]
    specification_version: Literal["6.3"]
    environment: Literal["paper"]
    live_execution_enabled: Literal[False]
    configuration_hash: HASH
    specification_sha256: HASH
    migration_head: Literal["0009_phase9_release"]
    component_versions: tuple[tuple[str, str], ...]
    freeze_hash: HASH

    _time = field_validator("frozen_at")(_utc)

    @field_validator("component_versions")
    @classmethod
    def components_sorted_unique(
        cls, value: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        if tuple(sorted(value)) != value:
            raise ValueError("component versions must be sorted")
        if len({name for name, _ in value}) != len(value):
            raise ValueError("component version names must be unique")
        return value


class ReviewFinding(StrictFrozenModel):
    finding_id: ID
    severity: ReviewSeverity
    status: FindingStatus
    category: Annotated[str, Field(min_length=2, max_length=64)]
    title: Annotated[str, Field(min_length=4, max_length=240)]
    owner: Annotated[str, Field(min_length=2, max_length=128)]
    evidence_refs: tuple[str, ...] = ()

    @field_validator("evidence_refs")
    @classmethod
    def evidence_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(value))) != value:
            raise ValueError("finding evidence references must be sorted and unique")
        return value


class ApprovalAttestation(StrictFrozenModel):
    role: ApprovalRole
    reviewer_id: Annotated[str, Field(min_length=2, max_length=128)]
    approved: bool
    approved_at: datetime
    evidence_package_hash: HASH
    comment: Annotated[str, Field(max_length=500)] = ""

    _time = field_validator("approved_at")(_utc)


class RollbackEvidence(StrictFrozenModel):
    tested_at: datetime
    backup_restore_verified: bool
    previous_wheel_available: bool
    previous_source_archive_available: bool
    emergency_flatten_verified: bool
    database_forward_recovery_verified: bool
    rollback_plan_sha256: HASH
    evidence_hash: HASH

    _time = field_validator("tested_at")(_utc)

    @property
    def verified(self) -> bool:
        return all(
            (
                self.backup_restore_verified,
                self.previous_wheel_available,
                self.previous_source_archive_available,
                self.emergency_flatten_verified,
                self.database_forward_recovery_verified,
            )
        )


class ProductionCandidateRequest(StrictFrozenModel):
    generated_at: datetime
    policy: ProductionCandidatePolicy = ProductionCandidatePolicy()
    evidence_manifest: EvidenceManifest
    build_attestation: BuildAttestation
    configuration_freeze: ConfigurationFreeze
    paper_ledger: PaperAcceptanceLedger
    deployment_evidence: DeploymentEvidenceReport
    rollback_evidence: RollbackEvidence
    findings: tuple[ReviewFinding, ...] = ()
    approvals: tuple[ApprovalAttestation, ...] = ()
    independent_review_complete: bool

    _time = field_validator("generated_at")(_utc)

    @field_validator("findings")
    @classmethod
    def findings_sorted_unique(cls, value: tuple[ReviewFinding, ...]) -> tuple[ReviewFinding, ...]:
        if tuple(sorted(value, key=lambda item: item.finding_id)) != value:
            raise ValueError("findings must be sorted by finding id")
        if len({item.finding_id for item in value}) != len(value):
            raise ValueError("finding ids must be unique")
        return value

    @field_validator("approvals")
    @classmethod
    def approvals_sorted_unique(
        cls, value: tuple[ApprovalAttestation, ...]
    ) -> tuple[ApprovalAttestation, ...]:
        if tuple(sorted(value, key=lambda item: item.role.value)) != value:
            raise ValueError("approvals must be sorted by role")
        if len({item.role for item in value}) != len(value):
            raise ValueError("approval roles must be unique")
        return value

    @model_validator(mode="after")
    def evidence_coherent(self) -> ProductionCandidateRequest:
        hashes = {item.name: item.sha256 for item in self.evidence_manifest.artifacts}
        expected = {
            "source_archive": self.build_attestation.source_archive_sha256,
            "wheel": self.build_attestation.wheel_sha256,
            "migrations": self.build_attestation.migrations_sha256,
            "schemas_bundle": self.build_attestation.schemas_bundle_sha256,
            "verification_report": self.build_attestation.verification_report_sha256,
            "specification": self.configuration_freeze.specification_sha256,
        }
        for name, expected_hash in expected.items():
            if hashes.get(name) != expected_hash:
                raise ValueError(f"evidence manifest hash mismatch for {name}")
        if self.build_attestation.release_version != self.policy.release_version:
            raise ValueError("build release version must match policy")
        if self.configuration_freeze.release_version != self.policy.release_version:
            raise ValueError("configuration freeze release version must match policy")
        if self.build_attestation.specification_version != self.policy.specification_version:
            raise ValueError("build specification version must match policy")
        if self.configuration_freeze.specification_version != self.policy.specification_version:
            raise ValueError("configuration freeze specification version must match policy")
        if self.paper_ledger.configuration_hash != self.configuration_freeze.configuration_hash:
            raise ValueError("paper ledger configuration must match frozen configuration")
        if (
            self.deployment_evidence.configuration_hash
            != self.configuration_freeze.configuration_hash
        ):
            raise ValueError("deployment evidence configuration must match frozen configuration")
        if self.deployment_evidence.paper_ledger_id != self.paper_ledger.ledger_id:
            raise ValueError("deployment evidence must reference the supplied paper ledger")
        if self.deployment_evidence.paper_ledger_hash != self.paper_ledger.ledger_hash:
            raise ValueError("deployment evidence must bind the supplied paper ledger hash")
        if self.deployment_evidence.release_version != self.policy.release_version:
            raise ValueError("deployment release version must match policy")
        if self.deployment_evidence.specification_version != self.policy.specification_version:
            raise ValueError("deployment specification version must match policy")
        if self.deployment_evidence.migration_head != self.policy.expected_migration_head:
            raise ValueError("deployment migration head must match policy")
        deployment_hashes = dict(self.deployment_evidence.evidence_hashes)
        expected_deployment_hashes = {
            "configuration": self.configuration_freeze.configuration_hash,
            "migrations": self.build_attestation.migrations_sha256,
            "paper_ledger": self.paper_ledger.ledger_hash,
            "schemas_bundle": self.build_attestation.schemas_bundle_sha256,
            "source_archive": self.build_attestation.source_archive_sha256,
            "specification": self.configuration_freeze.specification_sha256,
            "verification_report": self.build_attestation.verification_report_sha256,
            "wheel": self.build_attestation.wheel_sha256,
        }
        if deployment_hashes != expected_deployment_hashes:
            raise ValueError("deployment evidence hashes must match the release evidence chain")
        if self.deployment_evidence.tests_collected != self.build_attestation.tests_collected:
            raise ValueError("deployment test count must match build attestation")
        if self.deployment_evidence.tests_passed != self.build_attestation.tests_passed:
            raise ValueError("deployment passed-test count must match build attestation")
        if self.deployment_evidence.schema_count != self.build_attestation.schema_count:
            raise ValueError("deployment schema count must match build attestation")
        if self.deployment_evidence.secret_findings != self.build_attestation.secret_findings:
            raise ValueError("deployment secret findings must match build attestation")
        evidence_package_hash = self.evidence_manifest.manifest_hash
        if any(item.evidence_package_hash != evidence_package_hash for item in self.approvals):
            raise ValueError("all approvals must attest the evidence manifest hash")
        if any(item.approved_at < self.evidence_manifest.generated_at for item in self.approvals):
            raise ValueError("approvals cannot predate the evidence manifest")
        if any(item.approved_at > self.generated_at for item in self.approvals):
            raise ValueError("approvals cannot postdate the candidate request")
        return self


class ReviewSummary(StrictFrozenModel):
    finding_count: Annotated[int, Field(ge=0)]
    open_info_count: Annotated[int, Field(ge=0)]
    open_low_count: Annotated[int, Field(ge=0)]
    open_medium_count: Annotated[int, Field(ge=0)]
    open_high_count: Annotated[int, Field(ge=0)]
    open_critical_count: Annotated[int, Field(ge=0)]
    approved_roles: tuple[ApprovalRole, ...]
    missing_roles: tuple[ApprovalRole, ...]

    @field_validator("approved_roles", "missing_roles")
    @classmethod
    def roles_sorted_unique(cls, value: tuple[ApprovalRole, ...]) -> tuple[ApprovalRole, ...]:
        if tuple(sorted(set(value), key=lambda item: item.value)) != value:
            raise ValueError("review roles must be sorted and unique")
        return value


class ProductionCandidateReport(StrictFrozenModel):
    report_id: ID
    generated_at: datetime
    status: CandidateStatus
    paper_release_candidate: bool
    live_capital_eligible: Literal[False] = False
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    release_version: Literal["1.0.2"]
    specification_version: Literal["6.3"]
    configuration_hash: HASH
    evidence_manifest_hash: HASH
    build_attestation_hash: HASH
    configuration_freeze_hash: HASH
    paper_ledger_id: ID
    deployment_report_id: ID
    review_summary: ReviewSummary
    request_hash: HASH
    report_hash: HASH

    _time = field_validator("generated_at")(_utc)

    @model_validator(mode="after")
    def coherent(self) -> ProductionCandidateReport:
        expected = self.status is CandidateStatus.PAPER_RELEASE_CANDIDATE
        if self.paper_release_candidate != expected:
            raise ValueError("paper candidate flag must match candidate status")
        if self.paper_release_candidate and self.blockers:
            raise ValueError("paper release candidate cannot contain blockers")
        return self
