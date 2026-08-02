from pathlib import Path


def test_phase8_migration_is_append_only_and_chained():
    text = Path("migrations/versions/0008_phase8_analytics.py").read_text(encoding="utf-8")
    assert 'down_revision = "0007_phase7_operations"' in text
    assert "analytics_session_performance" in text
    assert "analytics_paper_acceptance_ledgers" in text
    assert "BEFORE UPDATE OR DELETE" in text
