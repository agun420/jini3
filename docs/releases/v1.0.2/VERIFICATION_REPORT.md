# Project Daybreak v1.0.2 — Offline Verification Report

**Generated:** 2026-08-01  
**Python:** 3.12.13  
**Release:** 1.0.2  
**Specification:** 6.3  
**Migration head:** `0009_phase9_release`

## Source provenance

| Item | Result |
|---|---|
| Supplied v1.0.1 ZIP SHA-256 | `5da22076c2f9332f66892937d8585c6bb25f9ddb2121e887084be32f25b956a5` |
| Supplied SHA sidecar | Exact match |
| ZIP entries inspected | 469 |
| Unsafe absolute/traversal paths | 0 |
| Symlink entries | 0 |
| Embedded package checksums | Passed |

## Quality and behavioral gates

| Gate | Command/scope | Observed result |
|---|---|---|
| Formatting | `ruff format --check .` | Passed |
| Lint | `ruff check .` | Passed; zero violations |
| Static typing | `mypy daybreak daybreak_*` with strict mode | Passed; zero errors |
| Behavioral tests | Full repository suite | 303 passed |
| Branch coverage | All runtime logic in configured coverage scope | 80.58% |
| Covered statements | Coverage JSON | 7,176 / 8,435 |
| Covered branches | Coverage JSON | 1,471 / 2,296 |
| Evaluator invariants | Registry inspection and tests | Exactly 77 |
| Generated schemas | `scripts/generate_schemas.py` | 57 |
| Fixture reproducibility | Analytics and release fixture tests | Passed |
| Python compilation | `python -m compileall -q ...` | Passed |

Coverage excludes command routers, `__main__` wrappers, schema-only emitters, package-level persistence modules, and recorder logging utilities from the threshold. Broker transports, recorder adapters, orchestration, risk, evaluator, execution, release logic, and the recorder PostgreSQL repository remain in scope. Exclusions are declared in `pyproject.toml` and are intended to keep the metric focused on executable domain and integration logic rather than inflate it with branch-heavy CLI dispatch.

## Security and supply-chain gates

| Gate | Observed result |
|---|---|
| Bandit, medium/high severity and medium/high confidence | 0 findings across 16,910 source lines |
| Bandit informational low severity | 17 findings; no medium/high escalation |
| `detect-secrets` distributable-source scan | 0 candidate secrets |
| `pip-audit --skip-editable` | No known vulnerabilities in resolved third-party dependencies; local editable project intentionally skipped |
| Dynamic SQL review | Identifier interpolation replaced with `psycopg.sql.Identifier` composition |
| Compose secret review | Default PostgreSQL password removed; explicit secret required |
| Release evidence substitution tests | Passed |

## Packaging gates

| Gate | Observed result |
|---|---|
| PEP 517 source distribution build | Passed |
| PEP 517 wheel build | Passed |
| `twine check` | Source distribution and wheel passed |
| Extracted-source test | 303 passed from generated sdist |
| Isolated wheel installation | Passed in a fresh Python 3.12 virtual environment |
| Installed CLI version check | `1.0.2` / specification `6.3` |
| Installed schema export | Passed |
| Installed import smoke | All 11 runtime packages imported |

## Artifact hashes

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `project_daybreak-1.0.2-py3-none-any.whl` | 227,105 | `6f3cad85e26876a225b3522e30e1ae2a747cb1f1579c0c2f1d3178d390cb7a1f` |
| `project_daybreak-1.0.2.tar.gz` | 406,929 | `cea4d9d9f2bebdfd666bf95a55725859c6b4a551f09fdc9d4c17ad658a9b0809` |
| v6.3 Markdown specification | — | `0872a5c3e168d4698819b2a4470d02566173a61caeecd4bacaa401e5f6a0fbf2` |
| Migration tree (`sha256sum` manifest hash) | 9 Python files | `fed28ff378cee1c9ff0fc3bb9ea4c8411dace227f1652a49664fd760ecbf37c1` |
| Schema tree (`sha256sum` manifest hash) | 57 JSON files | `f83956cb8c08ddadec10aad2cea0a59335762099f9a55bd556a8ee24bdec55a9` |

The final GitHub-ready ZIP hash is intentionally recorded in the external `.sha256` sidecar because an archive cannot contain its own stable digest.

## Acceptance boundary

This report proves only the stated offline gates. It does not prove target-host or vendor behavior. Target qualification still requires a dedicated Alpaca paper account, real paper sessions and fills, vendor and database connectivity, NTP evidence, backup/restore, failure drills, replay proof, downstream stale-fencing-token rejection, and authenticated human approvals over the exact final evidence package. Live-capital eligibility remains permanently false.
