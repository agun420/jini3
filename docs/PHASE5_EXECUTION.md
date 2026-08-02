# Phase 5 — Alpaca Paper Execution and Reconciliation

## Purpose

Phase 5 is the first Daybreak layer capable of transmitting an order. It is intentionally limited to Alpaca paper trading. It accepts only a deterministic v0.4.0 risk decision with a positive whole-share reservation.

## Parent order policy

The parent command is:

- side: `buy`;
- type: `limit`;
- time in force: `day`;
- order class: `bracket`;
- extended hours: false;
- quantity: exactly the reserved whole-share quantity;
- limit, stop, and target: exactly the normalized v0.4.0 risk prices.

The command builder has no account access, no market-data access, and no ability to modify the risk decision.

## Idempotent submission

Before submission, the service persists the command and queries Alpaca using the deterministic `client_order_id`.

- A matching existing order is reconciled and is not resubmitted.
- A conflicting existing order produces `reconciliation_required`.
- A transient submission failure triggers one lookup by client ID.
- If that lookup cannot prove the order exists, the service records an ambiguous broker state and does not retry.

## Broker events

The normalized broker status set includes common and rare Alpaca states: accepted, pending new, new, partial fill, fill, pending cancel, canceled, expired, replaced, rejected, suspended, stopped, and done for day.

Every WebSocket event is assigned a deterministic event ID and claimed once before side effects occur. Duplicate delivery cannot cause another cancellation or protective order.

## Partial fills

Alpaca bracket exits do not become active until the parent is completely filled. For a partial parent fill, v0.5.0:

1. records the partial fill;
2. advances the risk reservation to `partially_filled`;
3. requests cancellation of the remaining parent quantity;
4. submits a standalone DAY sell stop for the known whole-share filled quantity;
5. marks the execution `reconciliation_required` even when protection is acknowledged.

This path is deliberately conservative and paper-only. It requires live paper-account acceptance testing because an additional fill can occur while cancellation is in flight.

## Unfilled-order cancellation

A regular-session entry with zero fills can be canceled after `cancel_unfilled_after_seconds`. Terminal or partially filled orders are not handled by this timer.

## Persistence

Migration `0005_phase5_execution` adds append-only tables for:

- execution requests;
- order commands;
- broker snapshots;
- claimed trade updates;
- execution events;
- execution results;
- reconciliation reports.

The execution service also appends risk-reservation lifecycle events.

## Deployment boundary

The release is offline-verified but not broker-accepted. The REST adapter, optional `alpaca-py` trade-update adapter, PostgreSQL repository, and system behavior under network interruption require target-environment testing.
