from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from daybreak import SPEC_VERSION, __version__
from daybreak_evaluator.prompt import spec_sha256

from .config import DaybreakSettings
from .hashing import canonical_sha256


class ReleaseManifest(BaseModel):
    """Deterministic manifest for one release and non-secret configuration."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    project: str
    release_version: str
    specification_version: str
    specification_sha256: str
    configuration_sha256: str
    components: tuple[str, ...]
    live_execution_available: bool

    def canonical_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def build_release_manifest(settings: DaybreakSettings) -> ReleaseManifest:
    spec_path = Path(settings.paths.spec_path)
    return ReleaseManifest(
        project="Project Daybreak",
        release_version=__version__,
        specification_version=SPEC_VERSION,
        specification_sha256=spec_sha256(spec_path),
        configuration_sha256=settings.configuration_hash(),
        components=(
            "platform_core",
            "evaluator_contracts",
            "invariant_registry_77",
            "phase1_recorder",
            "phase2_feature_engine",
            "daily_pivot_cluster_v1",
            "point_in_time_float_join",
            "phase3_structured_outputs_evaluator",
            "openai_responses_transport",
            "primary_shadow_comparison",
            "evaluator_cutoff_enforcement",
            "phase4_position_risk_engine",
            "position_risk_policy_v1",
            "risk_reservation_artifacts",
            "phase5_paper_execution_engine",
            "alpaca_paper_order_transport",
            "trade_update_reconciliation",
            "partial_fill_protection",
            "phase6_session_orchestration",
            "fenced_execution_leadership",
            "persistent_kill_switch",
            "daybreak_scoped_flatten",
            "paper_environment_acceptance",
            "phase7_operational_resilience",
            "target_vm_acceptance",
            "restart_recovery_planner",
            "backup_restore_verification",
            "failure_drill_evidence",
            "observability_snapshots",
            "phase8_replay_analytics",
            "full_session_replay_report",
            "performance_attribution",
            "paper_acceptance_ledger",
            "deployment_evidence_report",
            "phase9_production_candidate_review",
            "cryptographic_evidence_manifest",
            "configuration_freeze",
            "independent_review_gate",
            "paper_release_candidate_report",
        ),
        live_execution_available=False,
    )
