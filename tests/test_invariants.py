from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from daybreak_contracts.validation import ValidationMetadata, validate_daybreak_run
from daybreak_contracts.validation.invariants import INVARIANT_REGISTRY

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURE_DIR / name).read_text())


def execution_metadata(candidate_count: int) -> ValidationMetadata:
    return ValidationMetadata(
        evaluator_candidate_count=candidate_count,
        max_evaluator_candidates_hard=25,
        evaluator_response_timestamp=datetime(2026, 7, 31, 13, 26, tzinfo=UTC),
        execution_cutoff_timestamp=datetime(2026, 7, 31, 13, 26, 30, tzinfo=UTC),
        order_authorized=True,
        scoring_completed_before_gates=True,
        operational_blockers_after_schema_validation=True,
        duplicate_detection_after_ticker_validation=True,
        duplicate_detection_valid_only=True,
    )


def test_registry_contains_exactly_77_consecutive_invariants():
    assert list(INVARIANT_REGISTRY) == list(range(1, 78))


def test_approved_golden_fixture_passes_response_validation(approved_input, approved_output):
    report = validate_daybreak_run(approved_input, approved_output)
    assert report.valid, report.failures
    assert len(report.checks) == 77
    assert not report.execution_ready


def test_approved_fixture_is_execution_ready_with_required_trace(approved_input, approved_output):
    report = validate_daybreak_run(
        approved_input,
        approved_output,
        metadata=execution_metadata(len(approved_input["tickers"])),
        require_execution_evidence=True,
    )
    assert report.valid, report.failures
    assert report.execution_ready


def test_truth_replay_detects_volume_score_mutation(approved_input, approved_output):
    broken = copy.deepcopy(approved_output)
    broken["approved_setups"][0]["score_breakdown"]["volume_points"] = 25
    broken["approved_setups"][0]["conviction_score"] = 90
    report = validate_daybreak_run(approved_input, broken)
    failed_numbers = {check.invariant_number for check in report.failures}
    assert 17 in failed_numbers or 26 in failed_numbers


def test_no_setups_fixture_passes():
    report = validate_daybreak_run(load("no_setups_input.json"), load("no_setups_output.json"))
    assert report.valid, report.failures


def test_blocked_fixture_passes():
    report = validate_daybreak_run(load("blocked_input.json"), load("blocked_output.json"))
    assert report.valid, report.failures


def test_stale_fixture_passes():
    report = validate_daybreak_run(load("stale_input.json"), load("stale_output.json"))
    assert report.valid, report.failures


def test_schema_failure_fixture_passes_shape_validation():
    report = validate_daybreak_run(
        load("schema_failure_input.json"), load("schema_failure_output.json")
    )
    assert report.valid, (report.model_errors, report.failures)


def test_unicode_code_point_offsets_pass():
    report = validate_daybreak_run(load("unicode_input.json"), load("unicode_output.json"))
    assert report.valid, report.failures
    assert 71 not in {check.invariant_number for check in report.failures}


def test_qualified_partition_detects_wrong_rank(approved_input, approved_output):
    broken = copy.deepcopy(approved_output)
    broken["qualified_not_selected"][0]["final_rank"] = 5
    report = validate_daybreak_run(approved_input, broken)
    assert 67 in {check.invariant_number for check in report.failures}


def test_late_response_cannot_authorize_order(approved_input, approved_output):
    metadata = execution_metadata(len(approved_input["tickers"]))
    metadata = metadata.model_copy(
        update={
            "evaluator_response_timestamp": datetime(2026, 7, 31, 13, 27, tzinfo=UTC),
            "order_authorized": True,
        }
    )
    report = validate_daybreak_run(approved_input, approved_output, metadata=metadata)
    assert 44 in {check.invariant_number for check in report.failures}


def test_semantic_reachability_fixture_covers_zero_override_properties():
    metadata = ValidationMetadata(
        semantic_magnitude_before_override=frozenset({"DISC", "NODR"}),
        invisible_disqualifier_tickers=frozenset({"DISC"}),
    )
    report = validate_daybreak_run(
        load("semantic_input.json"), load("semantic_output.json"), metadata=metadata
    )
    assert report.valid, report.failures
    passed = {check.invariant_number for check in report.checks if check.status == "pass"}
    assert {35, 36, 39}.issubset(passed)


def test_chart_reachability_fixture_covers_both_primary_outcomes():
    report = validate_daybreak_run(load("chart_input.json"), load("chart_output.json"))
    assert report.valid, report.failures
    passed = {check.invariant_number for check in report.checks if check.status == "pass"}
    assert {45, 46, 47, 55}.issubset(passed)


def test_duplicate_fixture_preserves_independent_ticker_failure():
    metadata = ValidationMetadata(
        duplicate_detection_after_ticker_validation=True,
        duplicate_detection_valid_only=True,
        operational_blockers_after_schema_validation=True,
    )
    report = validate_daybreak_run(
        load("duplicate_input.json"), load("duplicate_output.json"), metadata=metadata
    )
    assert report.valid, (report.model_errors, report.failures)
    passed = {check.invariant_number for check in report.checks if check.status == "pass"}
    assert {57, 58, 59, 60, 62, 66}.issubset(passed)


def test_every_invariant_has_at_least_one_positive_fixture():
    reports = []
    approved = load("approved_input.json")
    reports.append(
        validate_daybreak_run(
            approved,
            load("approved_output.json"),
            metadata=execution_metadata(len(approved["tickers"])),
        )
    )
    reports.append(
        validate_daybreak_run(
            load("semantic_input.json"),
            load("semantic_output.json"),
            metadata=ValidationMetadata(
                semantic_magnitude_before_override=frozenset({"DISC", "NODR"}),
                invisible_disqualifier_tickers=frozenset({"DISC"}),
            ),
        )
    )
    reports.append(validate_daybreak_run(load("chart_input.json"), load("chart_output.json")))
    reports.append(
        validate_daybreak_run(
            load("duplicate_input.json"),
            load("duplicate_output.json"),
            metadata=ValidationMetadata(
                duplicate_detection_after_ticker_validation=True,
                duplicate_detection_valid_only=True,
                operational_blockers_after_schema_validation=True,
            ),
        )
    )
    passed = {
        check.invariant_number
        for report in reports
        for check in report.checks
        if check.status == "pass"
    }
    assert passed == set(range(1, 78)), sorted(set(range(1, 78)) - passed)
