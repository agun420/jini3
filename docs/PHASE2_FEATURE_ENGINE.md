# Phase 2 Feature Engine

## Input contract

The engine accepts one immutable `FeatureContext`. No feature module reads a database, calls a network service, reads wall-clock time, or mutates global state.

The context separates economic time from knowledge time for float and catalyst records. A record can be selected only when it was effective and known by the frozen payload timestamp.

## Trade ledger

`TradeLedgerEvent` supports new trades, corrections, and cancellations. Events are applied in ingest-sequence order. Unknown originals, duplicate sequence numbers, and duplicate active trade identifiers fail closed.

Only active, eligible trades inside the 04:00 ET-to-snapshot window contribute to current price, low, volume, VWAP, volume profile, and RVOL.

## Core calculations

- Gap uses the latest eligible materialized trade and previous completed regular-session close.
- Premarket volume is the sum of active eligible SIP trade sizes.
- RVOL compares current volume with the mean of the same time window across twenty completed historical sessions.
- ATR uses Wilder smoothing over completed split-only daily bars.
- VWAP uses eligible trade price × size divided by eligible volume.
- Volume profile uses five-minute buckets with versioned concentration and coverage thresholds.

## Resistance

`daily_pivot_cluster_v1` implements:

- Minimum 30 completed bars
- Split-only history
- Five-left/five-right confirmed pivots
- Synthetic recent lookback high
- Fixed-anchor 0.5 ATR clustering
- Median zone center
- Minimum-touch and recency rules
- Zone-overlap handling
- Complete-history all-time-high fallback
- `99.0` blue-sky sentinel
- Six-decimal half-even quantization

## Prequalification

Candidates are removed before evaluator submission for deterministic conditions including halted status, insufficient gap, volume, RVOL, resistance room, capped structure, unconfirmed source, stale catalyst, disqualifying catalyst, missing float, invalid ATR, incomplete history, and other data-quality failures.

Candidates that survive are sorted by `prequal_rank_v1` and capped at the configured maximum, default 20 and hard maximum 25. Every removal and capacity omission is retained in the snapshot audit.

## Hashes

- `configuration_hash`: canonical feature configuration
- `feature_hash`: ordered selected feature records
- `payload_hash`: strict evaluator payload
- `context_hash`: complete normalized source context
- `audit_hash`: all prequalification decisions and capacity omissions
- `snapshot_id`: hash of context, audit, payload, feature, and configuration hashes

## Persistence

Migration `0002_phase2_features` adds append-only `feature_contexts` and `feature_snapshots` tables. Stored contexts can be replayed and compared byte-for-byte with their expected snapshots.
