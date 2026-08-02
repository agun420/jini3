"""Validate the dashboard/ static site before it is published to GitHub Pages.

Checks, in order:
  1. Every dashboard/data/*.json snapshot is public-safe: paper environment,
     live-capital-ineligible, and free of credential-shaped keys.
  2. Every HTML file under dashboard/ has no inline <script> body, no inline
     event-handler attributes, and no reference to an external (http/https) asset.
  3. Every .mjs/.js file under dashboard/ has no dynamic code execution
     (eval / new Function) and no external (http/https) import or fetch target.
  4. No local asset reference anywhere under dashboard/ escapes the dashboard/
     directory via a relative path.

Exits non-zero with a description of every violation found.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "dashboard"

CREDENTIAL_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|password|passwd|token|credential|access[_-]?key|"
    r"private[_-]?key|dsn|auth[_-]?header)",
    re.IGNORECASE,
)

INLINE_EVENT_HANDLER_PATTERN = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
INLINE_SCRIPT_BODY_PATTERN = re.compile(
    r"<script(?![^>]*\bsrc=)[^>]*>\s*(?!\s*</script>)\S", re.IGNORECASE
)
EXTERNAL_URL_PATTERN = re.compile(r"""(?:src|href)\s*=\s*["']https?://""", re.IGNORECASE)
EXTERNAL_JS_TARGET_PATTERN = re.compile(
    r"""(?:import\s+[^"']*from\s*["']|import\(\s*["']|fetch\(\s*["'])https?://""",
    re.IGNORECASE,
)
DYNAMIC_EXECUTION_PATTERN = re.compile(r"\b(eval|new\s+Function)\s*\(")
LOCAL_ASSET_REFERENCE_PATTERN = re.compile(
    r"""(?:src|href)\s*=\s*["']([^"']+)["']|"""
    r"""(?:import\s+[^"']*from\s*["']|import\(\s*["'])([^"']+)["']""",
    re.IGNORECASE,
)


def find_credential_keys(value: object, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_path = f"{path}.{key}"
            if CREDENTIAL_KEY_PATTERN.search(str(key)):
                found.append(key_path)
            found.extend(find_credential_keys(nested, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(find_credential_keys(item, f"{path}[{index}]"))
    return found


def validate_snapshot(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON ({exc})"]

    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
    if meta.get("environment") != "paper":
        errors.append(f'{path}: meta.environment must be "paper"')
    if meta.get("live_capital_eligible") is not False:
        errors.append(f"{path}: meta.live_capital_eligible must be false")
    if meta.get("public_safe") is not True:
        errors.append(f"{path}: meta.public_safe must be true for a committed snapshot")

    for key_path in find_credential_keys(payload):
        errors.append(f"{path}: credential-shaped key at {key_path}")

    return errors


def validate_html(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    if INLINE_SCRIPT_BODY_PATTERN.search(text):
        errors.append(f"{path}: contains an inline <script> body (use a src= module instead)")
    if INLINE_EVENT_HANDLER_PATTERN.search(text):
        errors.append(f"{path}: contains an inline event-handler attribute (onX=)")
    if EXTERNAL_URL_PATTERN.search(text):
        errors.append(f"{path}: references an external http(s) asset")
    errors.extend(validate_local_references(path, text))
    return errors


def validate_script(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    if DYNAMIC_EXECUTION_PATTERN.search(text):
        errors.append(f"{path}: uses eval()/new Function() (dynamic code execution is disallowed)")
    if EXTERNAL_JS_TARGET_PATTERN.search(text):
        errors.append(f"{path}: imports or fetches an external http(s) target")
    errors.extend(validate_local_references(path, text))
    return errors


def validate_local_references(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    for match in LOCAL_ASSET_REFERENCE_PATTERN.finditer(text):
        target = match.group(1) or match.group(2)
        if not target or target.startswith(("http://", "https://", "data:", "#")):
            continue
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(DASHBOARD_DIR.resolve())
        except ValueError:
            errors.append(f'{path}: local reference "{target}" escapes dashboard/')
    return errors


def main() -> int:
    if not DASHBOARD_DIR.is_dir():
        print(f"error: {DASHBOARD_DIR} does not exist", file=sys.stderr)
        return 1

    errors: list[str] = []

    for json_path in sorted((DASHBOARD_DIR / "data").glob("*.json")):
        errors.extend(validate_snapshot(json_path))

    for html_path in sorted(DASHBOARD_DIR.rglob("*.html")):
        errors.extend(validate_html(html_path))

    for script_path in sorted(
        list(DASHBOARD_DIR.rglob("*.mjs")) + list(DASHBOARD_DIR.rglob("*.js"))
    ):
        errors.extend(validate_script(script_path))

    if errors:
        print(f"Dashboard validation failed with {len(errors)} issue(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("Dashboard validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
