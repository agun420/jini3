"""Build a deterministic GitHub-ready source archive."""

from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = "Project-Daybreak"
FIXED_TIMESTAMP = (2026, 8, 1, 0, 0, 0)
EXCLUDED_PARTS = {
    ".hypothesis",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "project_daybreak.egg-info",
}
EXCLUDED_NAMES = {".coverage", ".DS_Store"}


def _included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        path.is_file()
        and not path.is_symlink()
        and not (set(relative.parts) & EXCLUDED_PARTS)
        and path.name not in EXCLUDED_NAMES
        and path.suffix not in {".pyc", ".pyo"}
    )


def build_archive(destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (path for path in ROOT.rglob("*") if _included(path)),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for path in files:
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{relative}", FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = stat.S_IMODE(path.stat().st_mode)
            info.external_attr = mode << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return len(files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    count = build_archive(args.destination.resolve())
    print(f"Archived {count} files to {args.destination}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
