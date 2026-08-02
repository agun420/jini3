# Phase 8 — Replay Analytics, Paper Acceptance, and Deployment Evidence

## Purpose

Phase 8 turns immutable Daybreak session artifacts into reproducible research and operational evidence. It does not alter selection, sizing, or execution decisions.

## Full-session replay

A replay is complete only when the following six components are present and hash-verified:

1. recorder,
2. features,
3. evaluator,
4. risk,
5. execution,
6. orchestration.

The report also requires exact raw-event counts, deterministic event ordering, and point-in-time integrity. Missing components, count differences, hash differences, or future-data leakage fail the replay.

## Performance attribution

Performance is calculated from completed paper trade outcomes, using actual average entry and exit prices and explicit fees. The engine reports:

- gross and net P&L,
- wins, losses, and breakeven trades,
- win rate,
- profit factor,
- expectancy,
- average win and loss,
- average realized R multiple,
- maximum sequential drawdown,
- entry slippage and slippage basis points,
- attribution by source type, chart structure, risk flag, and exit reason.

No market price or fill is inferred. Inputs are strict and immutable.

## Paper-acceptance ledger

The ledger evaluates operational evidence, not trading profitability. Its default requirements are:

- 30 sessions,
- 50 filled paper orders,
- 100% clean-session rate,
- zero invariant violations,
- zero unresolved reconciliations,
- zero duplicate orders,
- zero late primary responses,
- all positions flat,
- complete replay for every session,
- target-environment acceptance,
- restore validation,
- seven required drills.

A losing strategy can be operationally paper-qualified; that does not make it economically suitable for live capital.

## Deployment evidence

The deployment report binds the release, specification, configuration, source archive, wheel, migration head, test result, schema count, secret scan, paper ledger, and online operational checks.

It may return `paper_deployment_ready=true` only when all evidence passes. `live_deployment_ready` is fixed to `false` for this release.

## Persistence

Phase 8 adds four append-only tables:

- `analytics_session_performance`
- `analytics_replay_reports`
- `analytics_paper_acceptance_ledgers`
- `analytics_deployment_evidence`

Updates and deletes are rejected by PostgreSQL triggers.
