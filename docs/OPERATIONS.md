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
`signals-YYYY-MM-DD.json` (an ATR-based entry/stop/target for every qualifying
candidate — stop = entry - 1x ATR, target = entry + 2x ATR, the same fixed rule
`daybreak_risk` always uses, computed here straight from real historical bars with
no evaluator or float-data dependency). It needs only `APCA_API_KEY_ID`/
`APCA_API_SECRET_KEY` — the same credentials as paper trading, against Alpaca's
separate `data.alpaca.markets` host.

`daybreak-scanner check-outcomes` resolves each day's signals against real
subsequent minute-bar prices: whichever of the stop or target is touched first
(chronologically) decides win/loss; a signal that touches neither by the 16:00
America/New_York session close is finalized as `expired` at the closing price.
It writes `outcomes-YYYY-MM-DD.json` and updates a cumulative `scorecard.json`
(total signals, win rate, average return) recomputed from every outcomes file on
disk. It's idempotent — a signal already resolved in `outcomes-YYYY-MM-DD.json`
is never re-fetched or re-decided.

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
