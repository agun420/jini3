from pathlib import Path

from daybreak.core.config import DaybreakSettings, PathSettings
from daybreak.core.health import required_checks_pass, run_health_checks
from daybreak.core.manifest import build_release_manifest


def test_health_and_manifest(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_bytes(Path("docs/spec/Project_Daybreak_v6.3_Final.md").read_bytes())
    settings = DaybreakSettings(
        paths=PathSettings(
            state_dir=tmp_path / "state",
            artifact_dir=tmp_path / "artifacts",
            spec_path=spec,
        )
    )
    checks = run_health_checks(settings)
    assert required_checks_pass(checks)
    manifest = build_release_manifest(settings)
    assert manifest.release_version == "1.0.2"
    assert manifest.live_execution_available is False
    assert len(manifest.canonical_hash()) == 64
