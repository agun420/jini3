from __future__ import annotations

import argparse
import json
from pathlib import Path

from daybreak_contracts.validation import validate_daybreak_run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()

    report = validate_daybreak_run(
        json.loads(args.input_json.read_text()),
        json.loads(args.output_json.read_text()),
    )
    print(report.model_dump_json(indent=2))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
