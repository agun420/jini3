# Phase 6 — Integrated Session Orchestration and Operational Safety

## Purpose

Phase 6 coordinates the existing deterministic services without moving domain calculations into the coordinator. Numerical features remain in `daybreak_features`, catalyst judgment remains in `daybreak_evaluator`, capital decisions remain in `daybreak_risk`, and broker order state remains in `daybreak_execution`.

The coordinator owns:

- exchange-time scheduling;
- one-leader execution authority;
- health and configuration gates;
- phase cutoffs;
- kill-switch state;
- alerts;
- mandatory and emergency flattening;
- append-only operational audit records.

## Leadership

A session is identified by trading date, run ID, configuration hash, and policy version. Only one holder may own its lease.

PostgreSQL leases retain their row after release. Every reacquisition increments a fencing token, preventing a stale worker from regaining authority with a reused token. Audit events are append-only even though the current lease row is operational mutable state.

## Kill switch

The kill switch activates for conditions including:

- clock or NTP failure;
- database or market-data failure;
- trade-update stream loss;
- broker or account ineligibility;
- market circuit breaker;
- configuration mismatch;
- leadership loss;
- cutoff violation;
- reconciliation failure;
- incomplete mandatory flatten;
- manual operator activation.

It never resets automatically.

## Flatten ownership

The service must not liquidate an entire account. It establishes Daybreak ownership from two sources:

1. the current execution ledger's managed quantities;
2. filled broker orders carrying the `DB-YYYYMMDD-` namespace.

For nested bracket orders, filled entry quantity is reduced by filled exit-leg quantity. The resulting target is capped by the account's current quantity for that symbol. This leaves unrelated manual quantity in place when both strategies hold the same ticker.

Only Daybreak-prefixed open orders are canceled. The account-wide cancel-all and liquidate-all endpoints are not used.

## Acceptance levels

### Offline

Validates configuration, required environment-variable presence, paper endpoint, execution enablement, database enablement, and the prohibition on live execution.

An offline report always has:

```json
{"online_verified": false, "paper_ready": false}
```

### Online paper

Requires explicit `--confirm-paper` and verifies:

- paper account status and blocks;
- Alpaca market clock response;
- NTP synchronization;
- PostgreSQL connectivity;
- paper-only configuration.

Only a fully passing online report may set `paper_ready = true`.

## Remaining target integration

`SessionHooks` is the explicit boundary for target-specific orchestration of the recorder, feature snapshot, evaluator, risk engine, and execution engine. The generic coordinator and its safety states are complete, but a real full-day run cannot be certified without credentials, provider permissions, live streams, and a deployed PostgreSQL instance.
