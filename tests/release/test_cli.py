import json
from pathlib import Path

from daybreak.cli import main
from daybreak_release.canonical import canonical_json_text

from .helpers import make_request


def test_production_schema_cli(capsys):
    assert main(["production-schema", "report"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "ProductionCandidateReport"


def test_production_review_cli(tmp_path: Path):
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "report.json"
    request_path.write_text(canonical_json_text(make_request()), encoding="utf-8")
    assert main(["production-review", str(request_path), "--output", str(output_path)]) == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["paper_release_candidate"] is True
    assert payload["live_capital_eligible"] is False


def test_production_evidence_manifest_cli(tmp_path: Path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    assert (
        main(
            [
                "production-evidence-manifest",
                "--file",
                f"source_archive={first}",
                "--file",
                f"wheel={second}",
            ]
        )
        == 0
    )
