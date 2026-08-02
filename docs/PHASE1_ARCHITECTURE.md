# Phase 1 Recorder Architecture

## Data flow

```text
Alpaca SIP stock stream ─────────┐
Alpaca news stream ──────────────┤
Alpaca trade-update stream ──────┤
SEC submissions API ─────────────┤
                                 ▼
                        Source-specific adapter
                                 │
                        Exact decoded provider-message preservation
                                 │
                    Strict RawEvent normalization
                                 │
                  SHA-256 + idempotency construction
                                 │
                    Bounded cross-loop event sink
                                 │
                      Single acknowledged async writer
                                 │
              PostgreSQL raw_events + ingest_seq
                                 │
                    Deterministic replay reader
```

## Knowledge-time ordering

Provider event time is preserved in `event_timestamp`. The local arrival time is preserved in `received_at`. PostgreSQL assigns a monotonic `ingest_seq` when an event is accepted into the audit store.

Historical replay uses `ingest_seq` because it represents Daybreak's observed event order. Provider timestamps may arrive out of order, be corrected later, or share the same timestamp.

## Event identity

Every event stores:

- `payload_sha256`: hash of the exact decoded-and-canonicalized provider payload
- `idempotency_key`: hash of ingest session, source, channel, event type, symbols, provider ID, provider timestamp, and payload hash
- `event_id`: deterministic UUIDv5 derived from the idempotency key

An exact event repeated after reconnect inside the same ingest session is ignored by the unique idempotency constraint. The same event observed in a later ingest session is retained for that session’s independent knowledge-state replay. A correction or changed payload remains a separate event.

## Cross-loop stream bridge

`alpaca-py` stream clients own their event loops when `run()` is called. Daybreak runs each blocking stream in a worker thread. Handlers use `CrossLoopEventSink` to submit into the recorder's main-loop queue with `asyncio.run_coroutine_threadsafe`.

The bridge awaits persistence-queue acceptance. Low-rate checkpointed sources, including SEC polling, can additionally await database durability before advancing source state. All raw events share one writer, so database sequence reflects one process-wide acceptance order.

## Subscription scale boundary

Wildcard SIP quotes and trades are prohibited in the initial small-VM design. Wildcard minute bars and statuses are recorded for discovery, while tick data is limited to an explicit bounded symbol list.

A future dynamic-subscription controller should:

1. Discover candidates from wildcard minute bars.
2. Persist a new subscription-manifest version.
3. Subscribe trades and quotes for promoted candidates.
4. Backfill pre-promotion trades and quotes from the historical API.
5. Reconcile backfill and live overlap through deterministic idempotency keys.

## SEC behavior

The poller fetches company submissions JSON, first persists the complete decoded response snapshot, then emits one derived event per unseen accession ordered by acceptance timestamp.

A separate append-only `sec_seen_accessions` table limits repeated enqueueing. The raw-event idempotency constraint remains the final duplicate defense.

## Failure boundary

The recorder treats each stock, news, trade-update, and configured SEC service as required. Unexpected termination, readiness timeout, or bounded shutdown failure fails the session. The recorder does not continue with a silently incomplete source set.


## Alpaca SDK readiness boundary

The pinned `alpaca-py==0.43.5` clients run their own event loops in worker threads. The recorder does not label a stream connected merely because `run()` was invoked. It waits for the pinned SDK’s `_running` readiness flag, which is set after authentication and subscription setup, before persisting `stream_connected`. This compatibility boundary is isolated in the adapter and covered by fake-SDK tests.


## Capture completeness

The service warms up connections before the 04:00 ET feature boundary. A session whose process starts after `scheduled_start` may still record recovery data, but it is finalized as `completed_partial`. Downstream feature code must not treat that session as independently complete. Events received during preconnection remain in the raw store; later feature calculations are responsible for enforcing the exact 04:00-to-snapshot interval.
