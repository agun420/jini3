# Phase 7 — Operational resilience and target acceptance

## Safety boundary

Phase 7 remains paper-only. A restart can resume capture or reconciliation only. It can never resume new entries automatically. Any kill switch remains active until an explicit human reset under a separately audited procedure.

## Components

- **Observability snapshots:** canonical health metrics with deterministic hashes and failure codes.
- **Recovery planner:** evaluates database consistency, leadership, open Daybreak orders, managed positions, recorder checkpoints, configuration identity, and kill-switch state.
- **Backup manifests:** SHA-256, schema revision, row counts, encryption state, and completeness evidence.
- **Restore validation:** requires artifact integrity, matching schema, matching table counts, and deterministic replay verification.
- **Failure drills:** database, market-data, trade-update, broker-timeout, clock-skew, process-restart, and disk-pressure scenarios.
- **Target acceptance:** combines host checks, authenticated paper probes, migration head, backup/restore evidence, recovery safety, and required drill results.

## Target acceptance rule

`paper_ready` is true only when online target probes have actually run and every required check passes. Offline configuration review is useful but must always return `target_verified=false` and `paper_ready=false`.

## Restart rule

No recovery plan produced by v0.7.0 sets `may_resume_new_entries=true`. Open strategy positions force `flatten_only`; open strategy orders force `reconcile_only`; active kill switches require manual review; configuration/database/leadership conflicts block recovery.

## Backup rule

A backup cannot pass restore validation merely because `pg_restore` exits successfully. The artifact hash, Alembic revision, selected table counts, and a deterministic replay probe must all agree.

## Failure-drill rule

Drills are acceptance evidence only when failure detection, new-entry blocking, and recovery verification all pass. Simulation results are marked and should not be confused with target-VM network drills.
