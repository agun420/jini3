# Changelog

## 1.0.2 — 2026-08-01

### Trust-boundary and release-evidence hardening

- Bound deployment evidence to the exact v1.0.2 source archive, wheel, migration, schema, specification, verification report, paper ledger, test count, schema count, and secret-finding count.
- Recomputed nested ledger and deployment hashes and revalidated the entire artifact/approval chain during final production review.
- Added identity-collision detection to in-memory and PostgreSQL persistence boundaries.
- Pinned and hash-verified the bundled v6.3 evaluator specification and evaluator input payload.
- Made evaluator status/count parsing and recorder-health handling fail closed.
- Preserved active kill switches across orchestrator restarts and prevented leadership re-entry with the same holder before release or expiry.
- Propagated fencing tokens to integration hooks and renewed leadership after every hook.
- Verified risk decision hashes, deterministic IDs, terminal shape, and reservation linkage at execution trust boundaries.
- Reconciled both bracket legs, contained malformed broker JSON, confirmed partial-fill cancellation, and recovered ambiguous submissions by client order ID.
- Discovered and canceled broker-generated bracket children and closed newly uncovered late fills during flattening.
- Replaced dynamic SQL identifier interpolation with `psycopg.sql.Identifier` composition.

### Engineering quality and delivery

- Expanded the regression suite to 303 tests, including fixture reproducibility checks.
- Made repository-wide Ruff formatting/lint and strict mypy checks pass.
- Added branch-coverage, Bandit, dependency-audit, CodeQL, package-validation, and clean-wheel smoke gates.
- Removed the default PostgreSQL password and hardened/normalized systemd deployment units.
- Documented the dedicated Alpaca paper-account requirement and the remaining external qualification boundary.

## 1.0.1 — 2026-08-01

### Specification remediation

- Replaced the bundled v6.2 evaluator specification with Project Daybreak v6.3.
- Corrected the §6.3 contradiction: `volume_profile` affects `volume_points` and therefore can affect `conviction_score`.
- Added an explicit anti-injection rule for externally sourced catalyst and source text.
- Closed every input and output object recursively; unknown properties now fail validation.
- Defined the freshness tie-group boundary as inclusive: `anchor_score - candidate_score <= 2`.
- Added mandatory `evidence_purpose` to disambiguate magnitude, disqualifier, and no-evidence excerpts.
- Corrected the worked conviction scores from 79 to 80 and from 78 to 83.
- Added evaluator payload and text bounds: at most 25 tickers, 4,000 catalyst-text code points, 256 source-name code points, and five unique disqualifier flags.
- Added the relational ticker rule `premarket_low <= current_price`.
- Expanded the machine-testable invariant registry from 72 to 77.

### Executable contract and release chain

- Updated strict Pydantic input/output models, truth replay, ranking, provider schema, fixtures, and CLI schemas.
- Added nine traceable regression groups under `tests/v63/`.
- Added the v6.2 audit report and canonical v6.3 Markdown and Word specifications.
- Regenerated all schemas, hashes, configuration freeze, build attestation, evidence manifest, wheel, source archive, and checksums.
- Kept paper deployment blocked pending target-environment acceptance; live-capital eligibility remains permanently false.

## 1.0.0 — 2026-08-01

- Added `production_candidate_policy_v1` and deterministic paper-release-candidate review.
- Added cryptographic artifact manifests, build attestations, and paper configuration freezes.
- Added rollback, emergency-flatten, forward-recovery, findings, and role-approval evidence.
- Added append-only Phase 9 release evidence persistence and Alembic migration.
- Added production review CLI commands, strict JSON Schemas, golden fixtures, tests, and documentation.
- Kept live-money certification and endpoint enablement permanently disabled.

## 0.8.0 — 2026-08-01

- Added deterministic trade-level P&L, slippage, drawdown, R-multiple, and performance attribution.
- Added six-component full-session replay reports with raw-event, ordering, hash, and point-in-time checks.
- Added an immutable paper-acceptance ledger with operational—not profitability—gates.
- Added paper deployment-evidence reports with live certification permanently disabled.

## 0.7.0 — 2026-08-01

- Added deterministic operational health, restart recovery, backup/restore evidence, failure drills, and target-VM acceptance.

## 0.6.0 — 2026-08-01

- Added integrated paper-session orchestration, fenced leadership, kill switch, and Daybreak-scoped flattening.

## 0.5.0 — 2026-08-01

- Added paper-only Alpaca execution and broker reconciliation.

## 0.4.0 — 2026-08-01

- Added deterministic `position_risk_policy_v1` and append-only risk reservations.

## 0.3.0 — 2026-08-01

- Added OpenAI Structured Outputs evaluator and shadow comparison.

## 0.2.0 — 2026-08-01

- Added deterministic Phase 2 feature engine and immutable snapshots.

## 0.1.0 — 2026-08-01

- Added unified repository foundation, contracts, and Phase 1 recorder.
