# Project Daybreak v1.0.2

Project Daybreak is a fail-closed, paper-only trading research and execution platform built around the audited v6.3 evaluator contract. It records immutable market evidence, produces deterministic features, validates structured model output, sizes risk, submits Alpaca paper orders, reconciles broker state, flattens owned exposure, and builds a tamper-evident release-evidence chain.

> Live-money execution is intentionally unavailable. `live_execution_enabled` must remain `false`, only the Alpaca paper endpoint is accepted, and every release report permanently sets `live_capital_eligible` to `false`.

## Why v1.0.2

This hardening release closes trust-boundary and recovery defects that could previously allow stale, substituted, malformed, or incompletely reconciled evidence to pass too far through the system. The material changes include:

- end-to-end binding of source, wheel, migration, schema, specification, verification, paper-ledger, and deployment hashes;
- recomputation of nested ledger, deployment, approval, and release hashes at the final review boundary;
- persistent kill-switch recovery and non-reentrant fenced leadership;
- strict evaluator payload hashing, pinned specification integrity, UTC/coherence validation, and fail-closed status parsing;
- risk-decision hash and reservation linkage validation with identity-collision detection;
- bracket-leg reconciliation, partial-fill cancellation confirmation, ambiguous-submit recovery, and malformed-response containment;
- bracket-child discovery plus late-fill closure during emergency flattening;
- parameter-safe PostgreSQL identifier composition;
- repository-wide formatting, linting, and strict static typing; and
- CI gates for branch coverage, security analysis, dependency audit, package validation, and clean-wheel smoke tests.

The detailed independent-style engineering review is in `docs/audit/Project_Daybreak_v1.0.2_Elite_Review.md`.

A follow-up independent audit (`docs/audit/Project_Daybreak_v1.0.2_Independent_Audit_2026-08-02.md`) re-verified that review's findings against the current tree and found two new Critical gaps — reconciliation not checking bracket legs, and an unguarded alert call able to skip the emergency flatten — plus several related High findings. Read it before treating this tree as ready for target-environment paper qualification.

## Architecture

| Layer | Responsibility | Primary safety property |
|---|---|---|
| Recorder | SIP, news, trade-update, SEC, and calendar evidence | Immutable ordered raw events |
| Features | Point-in-time joins and deterministic calculations | Reproducible snapshot hashes |
| Evaluator | v6.3 Structured Outputs contract and shadow comparison | Closed schema and fail-closed validation |
| Risk | Deterministic sizing and append-only reservations | Bound, hash-verified decisions |
| Execution | Paper bracket submission and broker reconciliation | Idempotency and ambiguity containment |
| Orchestration | Timed phases, fenced leadership, kill switch, flatten | One active leader and durable stop state |
| Operations | Health, backup/restore, recovery, and drills | Evidence-backed restart readiness |
| Analytics | Replay, P&L, attribution, and paper acceptance | Operational—not profitability—gates |
| Release | Artifact manifest, freeze, approvals, and review | End-to-end evidence-chain integrity |

## Quick start

Requires Python 3.12 or 3.13.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[recorder,evaluator,test,dev]'

daybreak version
pytest
```

For a wheel install:

```bash
python -m pip install project_daybreak-1.0.2-py3-none-any.whl
```

## Verification

The local release-equivalent gate is:

```bash
make verify
```

Individual checks:

```bash
ruff format --check .
ruff check .
mypy daybreak daybreak_*
pytest
make coverage
make security
python -m build
python -m twine check dist/*
```

The evaluator invariant registry contains exactly 77 checks. Generated JSON Schemas live under `schemas/`; regenerate them after any model change with `python scripts/generate_schemas.py`.

## Paper deployment

Use a dedicated Alpaca paper account for Daybreak. Alpaca positions are account-level aggregates, so a shared account cannot provide a provable ownership boundary when flattening a symbol also traded by another strategy.

PostgreSQL via Compose requires an explicit password:

```bash
export DAYBREAK_POSTGRES_PASSWORD='replace-with-a-secret-manager-value'
docker compose up -d postgres
```

Then follow `docs/OPERATIONS.md`. The supplied systemd units use `/opt/project-daybreak`, `/opt/project-daybreak/.venv`, and `/etc/daybreak/daybreak.env` consistently.

## Release evidence

```bash
daybreak production-evidence-manifest \
  --file source_archive=Project_Daybreak_GitHub_Ready_v1_0_2.zip \
  --file wheel=project_daybreak-1.0.2-py3-none-any.whl

daybreak production-freeze \
  --config config/daybreak.paper.toml \
  --output configuration_freeze.json

daybreak production-review \
  production_candidate_request.json \
  --output production_candidate_report.json
```

Exit code `0` from `production-review` means only that the supplied paper-release evidence passed its deterministic policy. Approval records identify claimed reviewers but are not digital identity signatures; the organization must authenticate reviewers and preserve the signed or access-controlled approval record externally.

## Qualification boundary

The repository is offline-verified software, not proof of target-environment readiness. No automated test in this package contacts Alpaca, OpenAI, SEC, or a production PostgreSQL instance. Paper qualification still requires the target-VM campaign: 30 complete sessions, at least 50 fully reconciled paper fills, authenticated paper-account and database checks, replay hashes, restore validation, NTP evidence, required failure drills, and final human approvals over the exact v1.0.2 evidence package.

See `IMPLEMENTATION_STATUS.md`, `SECURITY.md`, and `docs/OPERATIONS.md` before deployment.
