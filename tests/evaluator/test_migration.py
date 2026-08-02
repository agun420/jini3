from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_phase3_migration_is_append_only() -> None:
    text = (ROOT / "migrations/versions/0003_phase3_evaluator.py").read_text()
    for table in (
        "evaluator_runs",
        "evaluator_attempts",
        "evaluator_results",
        "evaluator_shadow_comparisons",
    ):
        assert f"CREATE TABLE {table}" in text
        assert f"{table}_append_only" in text
    assert 'down_revision = "0002_phase2_features"' in text
