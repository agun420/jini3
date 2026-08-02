from typing import Any

from .models import (
    ApprovalAttestation,
    ArtifactEvidence,
    BuildAttestation,
    ConfigurationFreeze,
    EvidenceManifest,
    ProductionCandidatePolicy,
    ProductionCandidateReport,
    ProductionCandidateRequest,
    ReviewFinding,
    RollbackEvidence,
)


def production_policy_schema() -> dict[str, Any]:
    return ProductionCandidatePolicy.model_json_schema()


def artifact_evidence_schema() -> dict[str, Any]:
    return ArtifactEvidence.model_json_schema()


def evidence_manifest_schema() -> dict[str, Any]:
    return EvidenceManifest.model_json_schema()


def build_attestation_schema() -> dict[str, Any]:
    return BuildAttestation.model_json_schema()


def configuration_freeze_schema() -> dict[str, Any]:
    return ConfigurationFreeze.model_json_schema()


def review_finding_schema() -> dict[str, Any]:
    return ReviewFinding.model_json_schema()


def approval_attestation_schema() -> dict[str, Any]:
    return ApprovalAttestation.model_json_schema()


def rollback_evidence_schema() -> dict[str, Any]:
    return RollbackEvidence.model_json_schema()


def production_candidate_request_schema() -> dict[str, Any]:
    return ProductionCandidateRequest.model_json_schema()


def production_candidate_report_schema() -> dict[str, Any]:
    return ProductionCandidateReport.model_json_schema()
