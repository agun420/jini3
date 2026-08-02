"""Validate the dependency-free GitHub Pages dashboard artifact."""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
INDEX = DASHBOARD / "index.html"
DATA = DASHBOARD / "data" / "dashboard.json"
SCHEMA = DASHBOARD / "data" / "dashboard.schema.json"
CSS = DASHBOARD / "assets" / "styles.css"
APP = DASHBOARD / "assets" / "app.mjs"
DATA_MODULE = DASHBOARD / "assets" / "data.mjs"
FAVICON = DASHBOARD / "assets" / "favicon.svg"

REQUIRED_TOP_LEVEL = {
    "schema_version",
    "generated_at",
    "data_mode",
    "environment",
    "public_safe",
    "system",
    "safety",
    "account",
    "session",
    "performance",
    "signals",
    "positions",
    "orders",
    "services",
    "qualification",
    "release",
    "alerts",
}
REQUIRED_IDS = {
    "main-content",
    "freshness-chip",
    "source-banner",
    "view-overview",
    "view-trading",
    "view-performance",
    "view-system",
    "equity-chart",
    "signal-table-body",
    "service-grid",
    "signal-dialog",
}
REQUIRED_CSP = {
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
}
FORBIDDEN_KEY_PARTS = ("api_key", "apikey", "api_secret", "password", "access_token")


class DashboardHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.references: list[str] = []
        self.inline_script = False
        self.inline_style = False
        self.inline_handlers: list[str] = []
        self.csp = ""
        self.doctype = ""
        self.html_lang = ""
        self.generic_aria_labels: list[str] = []
        self.landmark_names: list[str] = []
        self.buttons_without_type = 0

    def handle_decl(self, decl: str) -> None:
        self.doctype = decl

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "html":
            self.html_lang = attributes.get("lang", "")
        if identifier := attributes.get("id"):
            self.ids.append(identifier)
        for name in ("href", "src"):
            if reference := attributes.get(name):
                self.references.append(reference)
        self.inline_handlers.extend(name for name in attributes if name.lower().startswith("on"))
        if tag == "script" and "src" not in attributes:
            self.inline_script = True
        if tag == "style":
            self.inline_style = True
        if tag in {"div", "span"} and attributes.get("aria-label") and not attributes.get("role"):
            self.generic_aria_labels.append(attributes["aria-label"] or tag)
        if tag == "section":
            landmark_name = attributes.get("aria-label") or attributes.get("aria-labelledby")
            if landmark_name:
                self.landmark_names.append(landmark_name)
        if tag == "button" and not attributes.get("type"):
            self.buttons_without_type += 1
        if tag == "meta" and attributes.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = attributes.get("content", "")


def _assert(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _validate_html(errors: list[str]) -> None:
    parser = DashboardHtmlParser()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    _assert(parser.doctype == "DOCTYPE html", "doctype must be uppercase HTML5", errors)
    _assert(parser.html_lang == "en", "html lang must be en", errors)
    _assert(
        not parser.generic_aria_labels,
        f"aria-label on generic element without role: {parser.generic_aria_labels}",
        errors,
    )
    duplicate_landmarks = sorted(
        name for name in set(parser.landmark_names) if parser.landmark_names.count(name) > 1
    )
    _assert(not duplicate_landmarks, f"duplicate landmark names: {duplicate_landmarks}", errors)
    _assert(
        parser.buttons_without_type == 0,
        "every button must declare its type",
        errors,
    )
    duplicates = sorted(
        identifier for identifier in set(parser.ids) if parser.ids.count(identifier) > 1
    )
    _assert(not duplicates, f"duplicate HTML ids: {duplicates}", errors)
    missing_ids = sorted(REQUIRED_IDS - set(parser.ids))
    _assert(not missing_ids, f"required HTML ids missing: {missing_ids}", errors)
    _assert(not parser.inline_script, "inline script violates the dashboard CSP", errors)
    _assert(not parser.inline_style, "inline style element violates the dashboard CSP", errors)
    _assert(not parser.inline_handlers, "inline event handlers are forbidden", errors)
    for directive in REQUIRED_CSP:
        _assert(directive in parser.csp, f"CSP directive missing: {directive}", errors)
    for reference in parser.references:
        parsed = urlsplit(reference)
        if parsed.scheme or reference.startswith(("#", "data:")):
            continue
        target = (DASHBOARD / parsed.path).resolve()
        _assert(
            target.is_relative_to(DASHBOARD),
            f"reference escapes dashboard: {reference}",
            errors,
        )
        _assert(target.is_file(), f"missing local asset: {reference}", errors)


def _validate_json(errors: list[str]) -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    _assert(isinstance(data, dict), "dashboard.json must be an object", errors)
    _assert(isinstance(schema, dict), "dashboard.schema.json must be an object", errors)
    if not isinstance(data, dict):
        return
    missing = sorted(REQUIRED_TOP_LEVEL - set(data))
    _assert(not missing, f"dashboard.json top-level keys missing: {missing}", errors)
    _assert(data.get("schema_version") == "1.0", "schema_version must be 1.0", errors)
    _assert(data.get("environment") == "paper", "dashboard environment must be paper", errors)
    _assert(
        data.get("public_safe") is True,
        "committed dashboard snapshot must be public-safe",
        errors,
    )
    safety = data.get("safety")
    _assert(isinstance(safety, dict), "safety must be an object", errors)
    if isinstance(safety, dict):
        _assert(safety.get("paper_only") is True, "paper_only must be true", errors)
        _assert(
            safety.get("live_capital_eligible") is False,
            "live_capital_eligible must be false",
            errors,
        )
    timestamp = data.get("generated_at")
    parsed = None
    if isinstance(timestamp, str):
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    _assert(
        parsed is not None and parsed.utcoffset() is not None,
        "generated_at must be aware",
        errors,
    )
    for key in ("signals", "positions", "orders", "services", "alerts"):
        _assert(isinstance(data.get(key), list), f"{key} must be an array", errors)
    _scan_sensitive_keys(data, "$", errors)


def _scan_sensitive_keys(value: object, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = key.lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                errors.append(f"sensitive key forbidden at {path}.{key}")
            _scan_sensitive_keys(child, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_sensitive_keys(child, f"{path}[{index}]", errors)


def _validate_assets(errors: list[str]) -> None:
    css = CSS.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    data_module = DATA_MODULE.read_text(encoding="utf-8")
    _assert("http://" not in css and "https://" not in css, "CSS contains an external URL", errors)
    _assert("innerHTML" not in app, "app must not use innerHTML with snapshot data", errors)
    _assert(
        "eval(" not in app and "Function(" not in app,
        "dynamic code execution is forbidden",
        errors,
    )
    app_without_svg_namespace = app.replace("http://www.w3.org/2000/svg", "")
    _assert(
        "http://" not in app_without_svg_namespace and "https://" not in app_without_svg_namespace,
        "app contains an external URL",
        errors,
    )
    _assert(
        "fetch(" not in data_module,
        "pure data module must not perform network requests",
        errors,
    )
    _assert(css.count("{") == css.count("}"), "CSS braces are unbalanced", errors)
    try:
        ET.parse(FAVICON)
    except ET.ParseError as exc:
        errors.append(f"favicon SVG is invalid: {exc}")
    for path in (INDEX, CSS, APP, DATA_MODULE, DATA, SCHEMA, FAVICON):
        _assert(path.stat().st_size < 1_000_000, f"asset exceeds 1 MB: {path.name}", errors)
    css_references = re.findall(r"url\((?:['\"])?([^)'\"]+)", css)
    for reference in css_references:
        if reference.startswith(("data:", "#")):
            continue
        _assert(
            (CSS.parent / reference).resolve().is_file(),
            f"missing CSS asset: {reference}",
            errors,
        )


def main() -> int:
    errors: list[str] = []
    required_files = (
        INDEX,
        DATA,
        SCHEMA,
        CSS,
        APP,
        DATA_MODULE,
        FAVICON,
        DASHBOARD / ".nojekyll",
    )
    for path in required_files:
        _assert(
            path.is_file(),
            f"required dashboard file missing: {path.relative_to(ROOT)}",
            errors,
        )
    if not errors:
        _validate_html(errors)
        _validate_json(errors)
        _validate_assets(errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Dashboard artifact validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
