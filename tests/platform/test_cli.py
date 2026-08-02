import json
from pathlib import Path

from daybreak.cli import main


def test_version_command(capsys) -> None:
    assert main(["version"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["release_version"] == "1.0.2"


def test_doctor_command(tmp_path: Path, capsys) -> None:
    spec = tmp_path / "spec.md"
    spec.write_bytes(Path("docs/spec/Project_Daybreak_v6.3_Final.md").read_bytes())
    config = tmp_path / "settings.toml"
    config.write_text(
        "[paths]\n"
        + f"state_dir = '{tmp_path / 'state'}'\n"
        + f"artifact_dir = '{tmp_path / 'artifacts'}'\n"
        + f"spec_path = '{spec}'\n",
        encoding="utf-8",
    )
    assert main(["doctor", "--config", str(config), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_build_features_command(tmp_path, capsys) -> None:
    from pathlib import Path

    context_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "features" / "passing_context.json"
    )
    expected_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "features" / "passing_snapshot.json"
    )
    output_path = tmp_path / "snapshot.json"
    assert main(["build-features", str(context_path), "--output", str(output_path)]) == 0
    assert output_path.read_bytes() == expected_path.read_bytes()
    assert capsys.readouterr().err == ""


def test_execution_build_order_cli_matches_golden(tmp_path: Path) -> None:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "execution"
    output = tmp_path / "command.json"
    assert (
        main(
            [
                "execution-build-order",
                str(fixtures / "execution_request.json"),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_bytes() == (fixtures / "entry_command.json").read_bytes()


def test_execution_schema_cli(tmp_path: Path) -> None:
    output = tmp_path / "execution.schema.json"
    assert main(["execution-schema", "result", "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["title"] == "ExecutionResult"
