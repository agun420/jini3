# Project Daybreak Paper Operations Guide

## Host setup

Recommended baseline:

- Small Linux VM with persistent SSD storage
- Python 3.12+
- PostgreSQL on the same host or a low-latency managed instance
- chrony enabled
- Host timezone set to `America/New_York`
- Dedicated `daybreak` Unix user
- Dedicated Alpaca paper account used only by Daybreak
- Secrets stored in `/etc/daybreak/daybreak.env` with mode `0600`

## Installation

```bash
sudo useradd --system --home /var/lib/daybreak --shell /usr/sbin/nologin daybreak
sudo mkdir -p /opt/project-daybreak /etc/daybreak /var/lib/daybreak /var/log/daybreak
sudo chown -R daybreak:daybreak /opt/project-daybreak /var/lib/daybreak /var/log/daybreak

cd /opt/project-daybreak
python3.12 -m venv .venv
.venv/bin/pip install -e '.[recorder,evaluator]'

sudo cp config/daybreak-recorder.env.example /etc/daybreak/daybreak.env
sudo chmod 600 /etc/daybreak/daybreak.env
sudo chown daybreak:daybreak /etc/daybreak/daybreak.env

set -a
source /etc/daybreak/daybreak.env
set +a
.venv/bin/alembic upgrade head
```

## systemd

```bash
sudo cp deploy/systemd/daybreak-recorder.service /etc/systemd/system/
sudo cp deploy/systemd/daybreak-recorder.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now daybreak-recorder.timer
```

Check:

```bash
systemctl list-timers daybreak-recorder.timer
journalctl -u daybreak-recorder.service -f
```

## Scanner (dynamic candidate discovery, signals, and outcome tracking)

`daybreak-scanner scan` reads Alpaca's market-data screener (gainers, current
per-ticker volume, historical bars) and writes two dated files: `candidates-
YYYY-MM-DD.json` (every scanned ticker with its qualification verdict) and
`signals-YYYY-MM-DD.json` (an ATR-based entry/stop/target_1/target_2 for every
qualifying candidate — stop = entry - 1x ATR, target_1 = entry + 2x ATR, the
same fixed rule `daybreak_risk` always uses, computed here straight from real
historical bars with no evaluator or float-data dependency. `target_2` = entry
+ 3x ATR has no daybreak_risk equivalent — it's a scanner-only stretch target
purely for outcome tracking below). It needs only `APCA_API_KEY_ID`/
`APCA_API_SECRET_KEY` — the same credentials as paper trading, against Alpaca's
separate `data.alpaca.markets` host.

`daybreak-scanner check-outcomes` resolves each day's signals against real
subsequent minute-bar prices: whichever of the stop, target_1, or target_2 is
touched first (chronologically) decides win/loss and, for a win, which target
resolved it; a signal that touches neither by the 16:00 America/New_York
session close is finalized as `expired` at the closing price. It writes
`outcomes-YYYY-MM-DD.json` and updates a cumulative `scorecard.json` (total
signals, win rate, target_1/target_2 hit rates, average return) recomputed
from every outcomes file on disk. It's idempotent — a signal already resolved
in `outcomes-YYYY-MM-DD.json` is never re-fetched or re-decided.

```bash
sudo cp deploy/systemd/daybreak-scanner.service /etc/systemd/system/
sudo cp deploy/systemd/daybreak-scanner.timer /etc/systemd/system/
sudo cp deploy/systemd/daybreak-scanner-check-outcomes.service /etc/systemd/system/
sudo cp deploy/systemd/daybreak-scanner-check-outcomes.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now daybreak-scanner.timer
sudo systemctl enable --now daybreak-scanner-check-outcomes.timer
```

`daybreak-scanner.timer` fires once per weekday at 09:35 America/New_York — five
minutes after the regular session opens. This is deliberate: Alpaca's movers/gainers
endpoint documents that its leaderboard resets at market open and shows the
*previous* session's movers until then, so a premarket run risks scanning stale
data. `daybreak-scanner-check-outcomes.timer` fires every 15 minutes from 09:00
through 16:45 America/New_York; firings before the day's scan has produced a
signals file exit non-zero with a logged "no signals file" message — harmless,
but visible in `journalctl`/`systemctl status` as a failed run.

### Optional: TimesFM trend forecast

`daybreak-scanner scan --with-forecast` additionally feeds each qualifying
candidate's daily closes (already-fetched, no new API calls) to Google's
[TimesFM](https://github.com/google-research/timesfm) and records the
forecasted short-horizon trend on the `Signal` as `forecast_trend_pct`. This
is purely informational: it never affects which candidates qualify or what
the mechanical entry/stop/target are (`daybreak_scanner/signals.py`'s fixed
1x/2x ATR rule is unchanged), and a forecast failure only skips the field —
it never fails the scan.

This needs the opt-in `forecast` extra (`pip install '.[forecast]'`, pulling
in `timesfm[torch]`) and, on first use, downloads the pretrained checkpoint
from Hugging Face Hub. **Neither of those was reachable from this project's
own development sandbox** (its network policy blocks both Hugging Face Hub
and the lean CPU-only PyTorch wheel index), so `TimesFMForecaster` in
`daybreak_scanner/forecast.py` is written from the published API surface but
has not been exercised against the real model or real weights. Verify it
actually works the first time you run `--with-forecast` on this VM (which
has normal internet access): check for a `forecast unavailable` line in
stderr, and if absent, confirm `forecast_trend_pct` is populated (not `null`)
in the day's `signals-YYYY-MM-DD.json`. If it fails, the scan itself is
unaffected — only that field stays empty.

```bash
sudo -u daybreak /opt/project-daybreak/.venv/bin/pip install '.[forecast]'
# then add --with-forecast to daybreak-scanner.service's ExecStart line
```

### GitHub Actions automation (no VM required)

Instead of the systemd timers above, `.github/workflows/scanner-scan.yml` and
`scanner-check-outcomes.yml` run the scanner directly on GitHub-hosted
runners on a schedule, commit its real output to the repository, and publish
it live on the GitHub Pages dashboard -- no host to provision, no manual
`--load private snapshot` step. This is the current default deployment path;
the VM/systemd path above still works if you'd rather self-host.

**Setup (one manual step only you can do):** add two repository secrets --
Settings → Secrets and variables → Actions → New repository secret -- named
exactly `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`, using the same Alpaca
paper credentials as everywhere else in this project. There is no API to set
these programmatically; they must be entered through the GitHub web UI, and
that's deliberate -- the values then never pass through anything but GitHub's
own secret store.

**What it does, each run:**

1. `scanner-scan.yml` (weekdays, ~09:35 America/New_York) runs `daybreak-scanner
   scan`, and `scanner-check-outcomes.yml` (weekdays, every 15 minutes from
   09:00 to 16:45 America/New_York) runs `daybreak-scanner check-outcomes` --
   both against real Alpaca market data, same as the systemd version.
2. Their output (`candidates-*.json`, `signals-*.json`, `outcomes-*.json`,
   `scorecard.json`) is committed to a dedicated **`scanner-data`** branch,
   not `main` -- GitHub Actions runners have no persistent disk between
   separate scheduled invocations, so this branch is the only state that
   survives from one run to the next. It's created automatically on first
   run.
3. Each run then regenerates `dashboard/data/dashboard.json` via
   `daybreak-scanner dashboard-snapshot --public`, validates it with
   `scripts/validate_dashboard.py`, and commits it straight to `main` if it
   changed. A push made with the default `GITHUB_TOKEN` doesn't fire other
   workflows' `push` triggers (GitHub's own loop-prevention), so
   `deploy-dashboard.yml` wouldn't otherwise notice that commit -- the workflow
   dispatches it explicitly (`gh workflow run deploy-dashboard.yml`) right
   after a successful push, which redeploys GitHub Pages with the fresh data.

**This is a deliberate, user-authorized exception** to this project's normal
"never commit real data" rule -- see the "Explicit, scoped exception" bullet
in `SECURITY.md`. It is scoped exactly to scanner signals (tickers, ATR
entry/stop/target, win/loss); no credential, account balance, position, or
broker order id is ever in scope, because scanner mode places no real order.

**DST and the trading window:** `cron:` schedules are UTC-only and can't
express an America/New_York time precisely across the DST boundary, so both
workflows deliberately over-fire (at both possible UTC offsets for `scan`,
and across the full 13:00-21:45 UTC union window every 15 minutes for
`check-outcomes`) and `daybreak_scanner/trading_window.py` checks the *real*
current America/New_York wall-clock time before doing anything, exiting
cleanly on every tick outside the intended window or on a weekend. Exactly
one `scan` tick and up to ~31 `check-outcomes` ticks actually do real work on
any given trading day, regardless of which DST regime is in effect -- more
precise than the UTC-only cron alone would allow, and self-correcting across
the DST transition with no manual schedule change needed.

**To test without waiting for market hours:** trigger either workflow
manually from the Actions tab ("Run workflow") with the `force` input
checked, which bypasses the trading-window check entirely.

**Not included:** `--with-forecast` (TimesFM) is intentionally left out of
both workflows. It's unverified against the real model in any environment so
far (see the "Optional: TimesFM trend forecast" section above) and its
`[forecast]` extra pulls in a multi-GB PyTorch dependency that would need
installing on every single scheduled run. Verify it manually first (on a VM
or locally) before considering wiring it into this automation.

**Branch protection caveat:** both workflows push directly to `main` using
the default `GITHUB_TOKEN` (via `permissions: contents: write`). If `main`
has branch-protection rules that block direct pushes, add an exception for
the `github-actions[bot]` actor, or switch these workflows to open a PR
instead -- this hasn't been tested against a protected `main` since this
repository's own protection settings aren't visible to Claude Code.

### Viewing it on the dashboard

`daybreak-scanner dashboard-snapshot` reads the local files above (no Alpaca
credentials needed — it never makes a network call) and writes a
`dashboard.schema.json`-shaped snapshot: the most recent day's signals (ranked,
each tagged `win`/`loss`/`expired`/`pending`) in the Trading view, and the
cumulative scorecard (win rate, trade counts, session count) in the Performance
view. Genuinely-unavailable fields — technical grade, catalyst thesis, dollar
P&L, position sizing — render as empty/null rather than fabricated, and
`system.name` says "mechanical, no evaluator, no orders" so it can never be
mistaken for the audited system's real paper-trading output.

By default (no `--public`) the snapshot is private (`data_mode: "local"`,
`public_safe: false`) -- never commit it; load it only via the dashboard's
"Load private snapshot" control, as below. With `--public`, the same command
instead marks it `data_mode: "published"`, `public_safe: true`, fit to commit
as the live `dashboard/data/dashboard.json` -- this is what the GitHub Actions
automation above uses on every run.

```bash
daybreak-scanner dashboard-snapshot \
  --scanner-dir /var/lib/daybreak/scanner \
  --outcomes-dir /var/lib/daybreak/scanner/outcomes \
  --output dashboard/data/private.json
```

Load the resulting file through the dashboard's **Load private snapshot**
control (never commit it — see the "Dashboard" section of `SECURITY.md`).
Verified by hand with Playwright against the real dashboard UI: no console
errors, no leaked literal `"undefined"` text. One known cosmetic gap from that
check — the Trading view's Approved/Qualified/Excluded/Average-score summary
cards only recognize the evaluator's own status taxonomy, so they read 0 for
scanner-mode signals even though the setup ledger table below them is
populated; the setup ledger table itself, the detail dialog, and the
Performance view all render correctly.

See `docs/audit/Project_Daybreak_Scanner_Mode_Audit_2026-08-03.md` for what this
mode deliberately does and doesn't do (no float data, no LLM evaluator, no paper
or live order submission — a mechanical backtest-style signal, not the audited
system's own risk-sized, catalyst-scored setup) and for open effectiveness
findings (scan timing, single-scan-per-day coverage, no halt-status check).

Check:

```bash
systemctl list-timers daybreak-scanner.timer daybreak-scanner-check-outcomes.timer
journalctl -u daybreak-scanner.service -u daybreak-scanner-check-outcomes.service -f
ls /var/lib/daybreak/scanner/
cat /var/lib/daybreak/scanner/outcomes/scorecard.json
```

## Preflight checks

Before enabling the timer:

```bash
sudo -u daybreak /opt/project-daybreak/.venv/bin/daybreak-recorder validate-config
chronyc tracking
pg_isready
```

Confirm:

- Configuration hash is stable
- Alpaca credentials are present
- Feed is `sip`
- Database is reachable
- SEC user agent contains a real contact address
- Paper account contains no manual or non-Daybreak orders or positions
- Tick-symbol count is within the configured cap
- Preconnection lead is 300 seconds unless a tested configuration says otherwise

## Database health queries

Recent sessions:

```sql
SELECT ingest_session_id, trading_date, status, started_at, ended_at, error_message
FROM ingest_sessions
ORDER BY started_at DESC
LIMIT 20;
```

Event counts by source:

```sql
SELECT source, event_type, COUNT(*)
FROM raw_events
WHERE ingest_session_id = :session_id
GROUP BY source, event_type
ORDER BY source, event_type;
```

Arrival lag:

```sql
SELECT event_type,
       percentile_cont(0.50) WITHIN GROUP (
           ORDER BY EXTRACT(EPOCH FROM (received_at - event_timestamp))
       ) AS p50_seconds,
       percentile_cont(0.99) WITHIN GROUP (
           ORDER BY EXTRACT(EPOCH FROM (received_at - event_timestamp))
       ) AS p99_seconds
FROM raw_events
WHERE ingest_session_id = :session_id
GROUP BY event_type;
```

Normalization failures:

```sql
SELECT source, channel, error_type, COUNT(*)
FROM raw_ingest_failures
WHERE ingest_session_id = :session_id
GROUP BY source, channel, error_type;
```

## Backup and retention

Do not delete raw rows in place. Retention must be implemented through immutable archive/export workflows and, in a later schema version, date partition detachment.

At minimum:

- Daily PostgreSQL backup
- Weekly restore test
- JSONL replay export for completed acceptance-test sessions
- Hash verification after export
- Disk-use alert at 70%, 80%, and 90%

## Acceptance tests required before production designation

1. Apply migration to target PostgreSQL.
2. Record a full paper session.
3. Restart each stream during capture and verify exact duplicate handling.
4. Disconnect the database and verify session failure.
5. Saturate a test queue and verify fail-closed behavior.
6. Compare database event counts with provider subscription telemetry.
7. Export and replay a session twice; compare byte-identical JSONL hashes.
8. Validate early-close behavior on a synthetic calendar fixture and the next real early-close session.
9. Measure storage growth and WAL volume.
10. Confirm no secret value appears in logs or configuration hashes.
11. Start the service after the configured stop time and verify it records `missed_capture_window` without entering a restart loop.
12. Force a stream readiness timeout and a stuck shutdown; verify the session fails and systemd respects its start-rate limits.
13. Start after 04:00 ET but before the stop time and verify the session ends as `completed_partial`, not `completed`.
14. Submit and partially fill a bracket order; confirm parent cancellation before placing a separate protective stop.
15. Create broker-generated bracket children and a fill during cancellation propagation; verify all owned children are canceled and only newly uncovered quantity is closed.
16. Restart with an active persistent kill switch; verify no integration hook runs and emergency flatten is attempted.
17. Attempt leadership re-entry with the same holder before release or lease expiry; verify acquisition fails.
18. Exercise each downstream hook with a stale fencing token and verify its write boundary rejects it.
