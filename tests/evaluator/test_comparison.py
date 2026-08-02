from pathlib import Path

from daybreak_contracts.output_models import DaybreakOutput
from daybreak_evaluator.comparison import compare_outputs

ROOT = Path(__file__).resolve().parents[2]


def test_comparison_detects_exact_match() -> None:
    output = DaybreakOutput.model_validate_json(
        (ROOT / "tests/fixtures/approved_output.json").read_text()
    )
    comparison = compare_outputs(
        primary_attempt_id="p",
        shadow_attempt_id="s",
        primary=output,
        shadow=output,
    )
    assert comparison.exact_output_match
    assert comparison.same_approved_order
    assert comparison.ticker_disagreements == ()
