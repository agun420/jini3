"""Guard for the GitHub Actions scanner workflows.

`cron:` schedules are always UTC and cannot express "09:35 America/New_York":
that offset moves by an hour across the DST transition. Rather than accept
that imprecision (as the systemd timer plan did), the workflows over-fire in
UTC across both possible offsets and this guard checks the *real* current
America/New_York wall-clock time before doing any real work, skipping
cleanly (exit 1, not an error) outside the intended window or on a weekend.
Exactly one of the over-fired ticks ends up inside the real window on any
given day, regardless of which DST regime is in effect.
"""

from __future__ import annotations

import sys
from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def in_trading_window(now: datetime, *, start: time, end: time) -> bool:
    """True if `now` (any tzinfo) falls on an America/New_York weekday
    between `start` and `end` inclusive, both given in America/New_York
    local time."""
    local = now.astimezone(ET)
    if local.weekday() >= 5:
        return False
    return start <= local.time() <= end


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m daybreak_scanner.trading_window HH:MM HH:MM", file=sys.stderr)
        return 64
    start, end = time.fromisoformat(args[0]), time.fromisoformat(args[1])
    now = datetime.now(ET)
    if in_trading_window(now, start=start, end=end):
        print(f"daybreak-scanner: {now.isoformat()} is within {args[0]}-{args[1]} ET")
        return 0
    print(
        f"daybreak-scanner: {now.isoformat()} is outside {args[0]}-{args[1]} ET "
        "(or a weekend), skipping",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
