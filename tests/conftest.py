from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_json(name: str):
    return json.loads((FIXTURE_DIR / name).read_text())


@pytest.fixture
def approved_input():
    return load_json("approved_input.json")


@pytest.fixture
def approved_output():
    return load_json("approved_output.json")
