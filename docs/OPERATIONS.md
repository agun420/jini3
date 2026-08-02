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
