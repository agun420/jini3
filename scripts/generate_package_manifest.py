"""Generate deterministic checksums for files shipped in the GitHub-ready archive."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_NAME = "GITHUB_PACKAGE_MANIFEST.csv"
SUMS_NAME = "GITHUB_PACKAGE_SHA256SUMS.txt"
EXCLUDED_PARTS = {
    ".git",
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "project_daybreak.egg-info",
}
EXCLUDED_NAMES = {".coverage", CSV_NAME, SUMS_NAME}


def _included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        path.is_file()
        and not (set(relative.parts) & EXCLUDED_PARTS)
        and path.name not in EXCLUDED_NAMES
        and path.suffix not in {".pyc", ".pyo"}
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    files = sorted(
        (path for path in ROOT.rglob("*") if _included(path)),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    records = [
        (path.relative_to(ROOT).as_posix(), path.stat().st_size, _sha256(path)) for path in files
    ]
    with (ROOT / CSV_NAME).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("path", "bytes", "sha256"))
        writer.writerows(records)
    (ROOT / SUMS_NAME).write_text(
        "".join(f"{digest}  {path}\n" for path, _, digest in records),
        encoding="utf-8",
    )
    print(f"Recorded {len(records)} package files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
