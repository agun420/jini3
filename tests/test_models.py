from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from daybreak_contracts import DaybreakInput, DaybreakOutput


def parse(model, value):
    return model.model_validate_json(json.dumps(value, ensure_ascii=False))


def test_valid_models_parse(approved_input, approved_output):
    assert parse(DaybreakInput, approved_input).tickers[0].ticker == "AAAA"
    assert parse(DaybreakOutput, approved_output).run_status == "approved"


def test_numeric_strings_are_rejected(approved_input):
    broken = copy.deepcopy(approved_input)
    broken["payload_age_seconds"] = "1"
    with pytest.raises(ValidationError):
        parse(DaybreakInput, broken)


def test_unknown_output_fields_are_rejected(approved_output):
    broken = copy.deepcopy(approved_output)
    broken["approved_setups"][0]["model_comment"] = "not allowed"
    with pytest.raises(ValidationError):
        parse(DaybreakOutput, broken)


def test_duplicate_valid_tickers_are_rejected(approved_input):
    broken = copy.deepcopy(approved_input)
    broken["tickers"][1]["ticker"] = "AAAA"
    with pytest.raises(ValidationError):
        parse(DaybreakInput, broken)


def test_qualified_record_cannot_contain_trade_parameters(approved_output):
    broken = copy.deepcopy(approved_output)
    broken["qualified_not_selected"][0]["trade_parameters"] = approved_output["approved_setups"][0][
        "trade_parameters"
    ]
    with pytest.raises(ValidationError):
        parse(DaybreakOutput, broken)
