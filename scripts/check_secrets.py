"""Fail when detect-secrets finds a candidate secret in distributable sources."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_PATHS = (
    "daybreak",
    "daybreak_analytics",
    "daybreak_contracts",
    "daybreak_evaluator",
    "daybreak_execution",
    "daybreak_features",
    "daybreak_operations",
    "daybreak_orchestration",
    "daybreak_recorder",
    "daybreak_release",
    "daybreak_risk",
    "config",
    "deploy",
    "scripts",
)


def main() -> int:
    completed = subprocess.run(
        (
            "detect-secrets",
            "scan",
            *SCAN_PATHS,
            "--exclude-files",
            r".*\.example$",
        ),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    findings = payload.get("results", {})
    count = sum(len(items) for items in findings.values())
    if count:
        for path, items in sorted(findings.items()):
            print(f"{path}: {len(items)} candidate secret(s)", file=sys.stderr)
        return 1
    print("Secret scan passed: 0 candidate secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
