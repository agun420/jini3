# Project Daybreak v1.0.2 — Independent Audit

**Audit date:** 2026-08-02
**Audited ref:** `main` (offline `1.0.2` tree, no source changes made by this audit)
**Classification:** paper-only production-candidate software; target qualification pending
**Relationship to prior reports:** this audit re-examines the codebase after `docs/audit/Project_Daybreak_v1.0.2_Elite_Review.md` (findings `DB-01`–`DB-15`, all marked "Closed"). It does not take that disposition on faith — every closed finding relevant to this audit's scope was re-verified against the current code, and new finding IDs continue the same `DB-` ledger from `DB-16`.

## Executive conclusion

The offline engineering gates are genuinely green: 303 tests pass, branch coverage is 80.58% (≥80% required), `ruff format`/`ruff check` are clean, strict `mypy` reports zero issues across all eleven packages, Bandit reports zero medium/high findings, and `pip-audit` finds no known-vulnerable dependencies. The `DB-01`–`DB-15` findings from the prior review were independently re-verified in this audit and remain closed — SQL identifier composition, bracket-leg reconciliation *within `ExecutionService`*, partial-fill cancel/refetch sequencing, kill-switch restart persistence, leadership acquire/renew fencing, and the Compose/systemd hardening are all correctly implemented as claimed.

However, this audit found **two new Critical findings**, each in one of the two subsystems whose entire purpose is to guarantee no unprotected exposure survives a failure: the standalone broker-reconciliation entry point never inspects bracket legs at all (a bracket that has silently lost its stop-loss reports as `matched`), and the kill-switch exception handlers in the session orchestrator call an *unguarded* alert emission immediately before the emergency-flatten call — if the alerting sink itself throws, the flatten is skipped entirely. Five High-severity findings compound these: emergency-flatten's broker close call has no idempotency guard against an ambiguous failure, a malformed numeric field from the broker can crash uncaught at the exact moment a position is unprotected, the kill switch is consulted once at session start and never re-polled during a run that can span hours, the leadership fencing token is generated and threaded through internal protocols but has no consumer anywhere in the codebase (including the real order-submission path), and kill-switch state lookup depends on session-id continuity that a restarted process is not guaranteed to preserve.

The single most safety-critical claim in the product — that `live_capital_eligible`, `live_execution_enabled`, and `live_deployment_ready` can never become `True` — was audited adversarially and holds: every occurrence is a Pydantic `Literal[False]` inside a strict, frozen model, the one plain-`bool` settings field is guarded by a `model_validator` that raises on `True` with no bypass, and the broker client hardcodes the paper endpoint regardless of constructor input. No path to live-money enablement was found.

This is not a "ship it" audit. The Critical and High findings below sit directly in the failure paths the product exists to prevent (unprotected brackets going undetected, flatten silently skipped, duplicate/ambiguous closes, stale-leader writes). They should be remediated, with regression tests reproducing each scenario, before this offline candidate is treated as ready to enter target-environment paper qualification.

## Method

Five independent lenses were applied against the current tree, each required to cite exact `file:line` evidence rather than repeat prior-report claims:

1. **Evaluator trust boundary** — untrusted external text handling, prompt-injection defenses, schema closure, spec-hash pinning, fail-closed response parsing.
2. **Execution and broker reconciliation** — idempotency, bracket-leg verification, partial-fill handling, malformed-response containment, race conditions between fills and flatten.
3. **Orchestration safety** — kill-switch persistence and enforcement, leadership fencing, clock/cutoff coherence, emergency flatten, alerting, recovery planning.
4. **Persistence, SQL, secrets, deployment** — parameterization across every `persistence.py`, secret-scanner coverage, migration safety, container/systemd hardening.
5. **Risk engine and release-evidence chain** — hash-verified decisions, reservation atomicity, rounding direction, and rigorous adversarial testing of the live-capital gate specifically.

In addition, the full offline verification suite (`ruff`, `mypy --strict`, `pytest --cov --cov-fail-under=80`, `bandit`, `pip-audit`, `detect-secrets`) was executed against a clean virtualenv, and several Bandit low-severity signals were manually triaged rather than dismissed. Two findings below (`DB-29`, `DB-30`) came from that manual triage. No live Alpaca, OpenAI, SEC, NTP, or production PostgreSQL connectivity was used; nothing in this report substitutes for the target acceptance campaign described in `IMPLEMENTATION_STATUS.md`.

## Finding summary

| ID | Severity | Area | Finding |
|---|---|---|---|
| DB-16 | Critical | Execution | `reconcile_command`, the only production broker-reconciliation entry point, never inspects bracket legs |
| DB-17 | Critical | Orchestration | Unguarded alert emission in kill-triggered exception handlers can skip the emergency flatten entirely |
| DB-18 | High | Execution | Emergency-flatten `close_position` has no idempotency guard against ambiguous broker failures |
| DB-19 | High | Execution | Malformed numeric fields from the broker crash uncaught, bypassing the typed-error boundary |
| DB-20 | High | Orchestration | Kill switch is consulted once at session start and never re-polled during a run |
| DB-21 | High | Orchestration | Leadership fencing token has no consumer anywhere in the codebase |
| DB-22 | High | Orchestration | Kill-switch lookup depends on session-id continuity a restart is not guaranteed to preserve |
| DB-23 | Medium | Evaluator | LLM-generated output text fields are unbounded and flow into risk contracts unbounded |
| DB-24 | Medium | Evaluator | "Execution-evidence" invariants are satisfied by hardcoded `True`, not real evidence |
| DB-25 | Medium | Orchestration | Sequential (non-`elif`) recovery-plan logic lets `FLATTEN_ONLY` silently overwrite `MANUAL_REVIEW` |
| DB-26 | Medium | Deployment | Secret scanner's scan scope excludes tests, migrations, fixtures, schemas, and the repo root |
| DB-27 | Medium | Risk | Postgres risk-reservation writes don't re-verify identity on conflict |
| DB-28 | Medium | Risk | No DB-level guard against concurrent non-batch risk-sizing calls jointly exceeding the risk budget |
| DB-29 | Medium | Deployment | Recorder settings default to a hardcoded weak DB credential, contradicting the module's own "no hidden defaults for secrets" docstring |
| DB-30 | Medium | Execution | `assert`-based `None`-narrowing on live broker responses is removed under `-O`/`PYTHONOPTIMIZE` |
| DB-31 | Low | Evaluator | `ValidationContext` is the one contract model not closed with `extra="forbid"` |
| DB-32 | Low | Deployment | `alembic.ini` carries a committed DSN with credentials, outside the secret scanner's reach |
| DB-33 | Low | Deployment | Backup/restore scripts pass a password-bearing DSN via argv, visible to local `ps` |
| DB-34 | Low | Deployment | Unredacted exception text to stderr on acceptance-report persistence failure |
| DB-35 | Low | Deployment | Postgres Compose service has no memory/CPU resource limits |
| DB-36 | Low | Risk | Release-evidence documents lack self-verifying hash validators (currently safe only because of a single call path) |
| DB-37 | Informational | Risk | `quantize_money` rounds half-even, not down (immaterial — final quantities are floored afterward) |

---

## Critical findings

### DB-16 — Broker reconciliation never validates bracket legs

**File:** `daybreak_execution/reconciliation.py:13-56`

`reconcile_command` is the module's only reconciliation function — the one backing `execution_reconciliation.schema.json` and `persistence.save_reconciliation`, and the only thing a periodic/offline reconciliation job in this repo can call. It checks the parent order's `symbol`/`side`/`quantity`/`client_order_id` (lines 31-39) but never reads `order.legs`, `order_class`, or leg count/type/price. The `DB-09`-style leg check does exist in the codebase — in `ExecutionService._matches` (`service.py:125-162`) — but that function is never called from `reconciliation.py`; grep confirms `reconcile_command`'s only caller in the whole repo is `tests/execution/test_reconciliation_persistence_schema.py`, and that test never asserts leg content.

Reproduced: a bracket command reconciled against a broker snapshot with the stop-loss leg deleted (only the take-profit leg present) returns `matched: True, mismatch_codes: ()`. A position that has silently lost its entire downside protection — the exact scenario `DB-09` was supposed to close — passes reconciliation clean.

**Impact:** anyone using the documented reconciliation feature to audit live bracket state (its only stated purpose) gets a false "matched" on an unprotected position.

**Recommended fix:** call the same leg-verification logic `ExecutionService._matches` already implements from `reconcile_command`, or factor it into a shared function both paths use, with a regression test asserting a missing/mismatched leg produces a non-empty `mismatch_codes`.

### DB-17 — Unguarded alert call can skip the emergency flatten

**File:** `daybreak_orchestration/service.py:212-233`

Both kill-triggered exception handlers call `self._emit_critical(...)` with no `try`/`except`, immediately before the (correctly guarded) flatten call:

```python
212:            self._emit_critical(plan, "PERSISTENT_KILL_SWITCH_ACTIVE", error_message, now)
213:            try:
214:                flatten_result = self._run_flatten(...)
```
```python
229:            self._emit_critical(plan, reason.value, error_message, now)
230:            outcome = SessionOutcome.KILLED
...
232:            try:
233:                flatten_result = self._run_flatten(...)
```

`_emit_critical` calls `AlertManager.emit` (`alerts.py:94`, `self._sink.send(alert)`, itself unguarded). If every sink in a `CompositeAlertSink` fails, `alerts.py:47-48` raises `RuntimeError("all alert sinks failed")`. That propagates straight out of the exception handler — skipping the flatten call and the `outcome = KILLED` assignment — instead of being caught anywhere. The kill-switch row is persisted first, so the *record* survives, but the *protective action* never runs, and `SessionOrchestrator.run()` raises rather than returning cleanly.

No test exercises this: every orchestration test uses `MemoryAlertSink`, which never raises (confirmed against `tests/orchestration/test_service.py` and `test_leadership_alerts_kill.py`).

**Concrete scenario:** the alerting webhook (Slack/PagerDuty) is unreachable at the exact moment a database-unhealthy or persistent-kill-switch condition fires. The kill switch is logged as active, but broker positions are never flattened.

**Recommended fix:** flatten first, alert second — or wrap the alert call so its failure can never suppress the flatten. Add a regression test with a sink that always raises.

---

## High findings

### DB-18 — Emergency-flatten close has no idempotency guard

**File:** `daybreak_orchestration/flatten.py:60-73` (`close_uncovered`)

```python
try:
    close_orders.append(self._broker.close_position(close_target))
    submitted_quantities[position.symbol] = already_submitted + uncovered
except Exception as exc:
    errors.append(...)
```

Alpaca's close-position endpoint takes no `client_order_id`, so an ambiguous (e.g. timed-out) `DELETE` cannot be reconciled by id the way order submission can. `submitted_quantities` only updates on success, so a subsequent poll iteration sees no progress and retries. Reproduced with a broker whose first `close_position` call raises while the position quantity hasn't yet dropped (order accepted but not yet filled): two close orders were submitted for the same 5-share position with no verification the first landed.

Also: `cancel_daybreak_orders` (`flatten.py:47`) is called exactly once before the poll loop, never again inside it (`flatten.py:82-93`), so any order Daybreak submits *after* that single pass is never cancelled by flatten.

**Recommended fix:** treat an ambiguous close failure the way order submission does — look up broker-side position/order state before retrying, and re-invoke `cancel_daybreak_orders` on each poll iteration, not just once.

### DB-19 — Malformed broker numeric fields crash uncaught

**File:** `daybreak_execution/alpaca.py:57-58, 74-75, 217`

`normalize_order` builds `Decimal(str(payload["qty"]))` and equivalents directly rather than through the safe `_decimal()` helper used for optional fields; `get_position` (line 217) has no surrounding `try`/`except` at all. `decimal.InvalidOperation` is not a subclass of `ValueError`/`KeyError`/`TypeError`, so it escapes every catch clause meant to convert malformed payloads into `BrokerTransportError` (`alpaca.py:179, 189, 203`). Reproduced against a mocked response with `"qty": "N/A"`: `decimal.InvalidOperation` propagates uncaught.

This matters specifically because `handle_trade_update` calls `get_order` right after cancelling a partially-filled parent (`service.py:530-531`), inside a block whose `except (BrokerNotFound, BrokerTransportError, ValueError)` (`service.py:586`) does not catch `InvalidOperation` either — i.e., exactly the window where the entry is cancelled but the protective stop is not yet placed.

**Recommended fix:** catch `decimal.InvalidOperation` alongside the existing exception tuple at every broker-response parse boundary, or route all numeric parsing through the existing `_decimal()` helper with an explicit error type.

### DB-20 — Kill switch is checked once, not re-polled during a run

**File:** `daybreak_orchestration/service.py:74, 102-105`

`get_latest_kill_switch` is called exactly once, before `_preflight`, at session start. Neither `_wait_until` (`service.py:370-377`, which can block for hours during recorder warmup) nor `_run_phase` (`285-303`) nor `_preflight` (`264-273`, which checks live health but not the kill-switch table) re-reads persisted kill-switch state. An operator activating the kill switch mid-run (e.g. via the `paper-emergency-flatten` CLI) has no path to reach an already-running orchestrator process short of a coincidental health-probe failure or cutoff.

**Recommended fix:** re-check kill-switch state at each phase transition and at the top of any long `_wait_until` loop, not only at session start.

### DB-21 — Leadership fencing token has no consumer

**File:** `daybreak_orchestration/protocols.py:20-46`, `daybreak_execution/service.py`

`SessionHooks`/`SessionBrokerOperations` thread `fencing_token` through every hook signature, and `leadership.py` generates/increments it correctly. But the only implementation of `SessionHooks` in the repo is the test fake (`tests/orchestration/helpers.py:74-95`), which accepts and discards the token. The real order-submission path, `daybreak_execution/service.py`'s `submit()` (line 206), takes no `fencing_token` parameter at all (`grep -rln fencing daybreak_execution` returns nothing). The only protection against a stale/superseded leader taking a broker-facing action is the orchestrator's own pre-hook `_renew_leadership` check (`service.py:353-368`), which has a TOCTOU gap — the hook's network calls happen after the check, not atomically with it.

**Recommended fix:** either have `ExecutionService.submit`/`FlattenService.flatten` accept and validate the fencing token against the persisted lease immediately before the broker call, or document clearly that fencing is advisory-only pending that wiring — the current state (token generated, propagated, and silently dropped) is worse than either extreme because it reads as enforced.

### DB-22 — Kill-switch lookup depends on session-id continuity

**File:** `daybreak_orchestration/clock.py:24-27`, `persistence.py:62-64,160-173`

`session_id = uuid5(..., f"...:{trading_date}:{run_id}:{configuration_hash}:{policy_version}")`, and `get_latest_kill_switch` filters strictly by `session_id`, not `trading_date`. The one CLI that builds a plan, `daybreak/cli.py:952`, defaults `run_id` to `uuid4().hex` when not supplied. If a restart re-invokes plan-building for the same trading day without reusing the exact prior `run_id`, `get_latest_kill_switch(new_session_id)` returns `None` and the orchestrator falls back to an inactive kill switch, silently discarding an earlier same-day activation. `SessionOrchestrator` has no supervisor/restart driver in this repo, so this is flagged as a design gap in the public API rather than a confirmed production exploit — but it is exactly the kind of gap `DB-03` (persistent kill switch across restarts) was meant to close, one layer up.

**Recommended fix:** key kill-switch lookup by `trading_date` (plus a tie-breaker for same-day plan regeneration), not by a value that depends on a caller supplying the same `run_id` across process restarts.

---

## Medium findings

### DB-23 — Unbounded LLM output text flows into risk contracts

`ApprovedSetup.master_thesis`/`catalyst_source` and `ReasonObject.observed_value`/`required_condition`/`reason` (`daybreak_contracts/output_models.py:112-151`) are plain `str` with no `max_length`, unlike the 200-char-bounded `magnitude_evidence_excerpt`. `daybreak_evaluator/schema.py:9-31` never injects a length bound into the JSON Schema sent to the provider either — confirmed absent from `schemas/evaluator_output.schema.json`. These same fields are `required`, still unbounded, in `schemas/risk_sizing_request.schema.json`. The prior audit's cardinality/length fix (finding #8 in the v6.2 spec audit) covered *input* text only; it was never extended to output text, which is model-generated and persisted/forwarded unbounded.

### DB-24 — "Execution-evidence" invariants are hardcoded `True`

`daybreak_evaluator/service.py:94-101` sets `scoring_completed_before_gates`, `duplicate_detection_after_ticker_validation`, `duplicate_detection_valid_only`, and `operational_blockers_after_schema_validation` to literal `True` rather than deriving them from anything measured about the run. `daybreak_contracts/validation/runner.py:18-19` names these `EXECUTION_EVIDENCE_INVARIANTS` (`{15, 41, 44, 62, 66}`), explicitly designed to fail closed (`not_evaluated(...)`) when real evidence is `None`. Hardcoding `True` forces an unconditional pass instead. This mechanism is not currently wired into any live execution-authorization code, so it is dormant rather than actively dangerous today — but the fabrication means it would be silently ineffective the moment it is wired up, and the comment above it ("This is the external proof available to the orchestrator") asserts a guarantee that no code currently backs.

### DB-25 — Recovery-plan action can silently overwrite `MANUAL_REVIEW`

`daybreak_operations/recovery.py:28-39` uses sequential `if` statements, not `elif`, so when both `kill_switch_active` and open positions/orders are true, the `action` field ends up `FLATTEN_ONLY`, overwriting the `MANUAL_REVIEW` value set two lines earlier. `reasons` still lists `KILL_SWITCH_ACTIVE` and `manual_acknowledgement_required` stays hardcoded `True`, which mitigates but doesn't eliminate the risk that automation keying off `action` alone misses the human-review signal. Not covered by `tests/operations/test_recovery.py`, which only tests each condition in isolation.

### DB-26 — Secret scanner has real blind spots

`scripts/check_secrets.py`'s `SCAN_PATHS` lists 14 package/config directories; `detect-secrets scan` only walks paths it's given, so `tests/`, `fixtures/`, `migrations/`, `schemas/`, `apps/`, `docs/`, and every repo-root file (`alembic.ini`, `docker-compose.yml`, `pyproject.toml`) are never scanned regardless of exclude rules. This isn't hypothetical: `tests/evaluator/test_persistence.py:69` already has `postgresql+psycopg://daybreak:secret@localhost/daybreak`, and `tests/recorder/test_settings_and_migration.py:26,29` have `first-secret`/`second-secret` — the pattern of putting credential-shaped strings in test fixtures is already present. A real key pasted into a new test fixture would pass CI's secret-scan step undetected (Bandit's scan is scoped to the same package list, so it wouldn't catch it either).

### DB-27 — Risk reservation writes don't re-verify identity on conflict

`PostgresRiskRepository.reserve()` (`daybreak_risk/persistence.py:119-129`) inserts with `ON CONFLICT (reservation_id) DO NOTHING` and never re-selects/compares content on conflict, unlike `_insert_decision` and `save_request` in the same file (which raise on identity collision) and unlike `MemoryRiskRepository.reserve()` (which does check). In the normal `RiskService.evaluate()` flow this is masked because `save_request()` runs first and independently rejects a reused `request_id` with different content — but `reserve()` is a public `RiskRepository` protocol method a caller (or future retry/replay path) could invoke directly without that upstream guard, and a reused id with a different `reserved_quantity` would silently no-op rather than fail loudly.

### DB-28 — No DB-level guard against concurrent risk-budget overrun

`size_position()` computes remaining risk capacity purely from the caller-supplied `SessionRiskState` snapshot; only `size_approved_batch()` protects against double-counting, and only by threading state sequentially within one in-process call. `migrations/versions/0004_phase4_risk.py` enforces per-row constraints only — no trigger sums reserved risk per run. The CLI exposes a non-batch `risk-size` command alongside `risk-size-batch`; two independent `evaluate()` calls sharing an identical/stale `SessionRiskState` could each be approved and reserved, jointly exceeding `max_open_risk_pct`, since nothing at the persistence layer locks or re-derives aggregate exposure before granting a reservation.

### DB-29 — Hidden default weak DB credential

`daybreak_recorder/settings.py:22` defaults `database_url` to `postgresql+psycopg://daybreak:daybreak@localhost:5432/daybreak` when `DAYBREAK_DATABASE_URL` is unset (`settings.py:183-186`), and `alembic.ini:4` carries the same literal DSN as its fallback. The module's own docstring (`settings.py:1`) claims "Environment-backed recorder settings **without hidden defaults for secrets**," which this default contradicts in spirit even though the credential is trivial and localhost-scoped. There is no validator tying `environment != "development"` to requiring an explicit, non-default `database_url` — a misconfigured non-dev deployment would silently connect (or silently fail to connect, masking the real misconfiguration) rather than failing closed with a clear error.

### DB-30 — `assert`-based None-narrowing is stripped under `-O`

`daybreak_execution/alpaca.py:176, 186, 200, 213` use `assert data is not None` to narrow the return of `_request()`, which genuinely can return `None` on a 204/empty-body Alpaca response (`alpaca.py:155-156`). Under `python -O` / `PYTHONOPTIMIZE=1`, `assert` statements are compiled out entirely, so `normalize_order(None)` would be called and raise an unhandled `AttributeError`/`TypeError` instead of the intended `BrokerTransportError(transient=True)` — changing a well-typed, caught failure mode into an unhandled one for no functional benefit (this isn't a performance-sensitive path). Bandit correctly flags this pattern (`B101`) for exactly this reason.

---

## Low / informational findings

- **DB-31** — `ValidationContext` (`daybreak_contracts/validation/models.py:62-63`) is the one contract model without `extra="forbid"`; low impact since it's an internal container, not a parser of raw external JSON.
- **DB-32** — `alembic.ini:4` commits a DSN with embedded credentials (trivial password) outside the secret scanner's reach and without an `.example` suffix.
- **DB-33** — `scripts/backup_postgres.sh:7` and `scripts/restore_postgres_test.sh:5-6` pass a password-bearing DSN as a CLI argument, visible via `ps`/`/proc/<pid>/cmdline` to other local users on hosts without `hidepid=2`.
- **DB-34** — `daybreak/cli.py:1057-1061` prints exception text from a persistence failure to stderr with no redaction layer, unlike the recorder's purpose-built `redacted_database_url`; a malformed-DSN parse error could in principle echo fragments of the connection string into a systemd-journaled stream. Not confirmed against a live psycopg failure in this sandbox (psycopg unavailable offline) — flagged as a plausible gap.
- **DB-35** — `docker-compose.yml`'s `postgres` service has no `mem_limit`/`cpus`/`deploy.resources` ceiling.
- **DB-36** — Release-evidence documents (`ProductionCandidateReport`, `ConfigurationFreeze`, `BuildAttestation`, etc.) have no self-verifying hash validator the way `RiskDecision.validate_terminal_shape` does; today's only load path (`review_production_candidate()` building fresh from a raw request) is safe, but a future path loading a persisted report directly would trust it without recomputation. `live_capital_eligible` staying `Literal[False]` regardless bounds the blast radius.
- **DB-37 (informational)** — `daybreak_risk/rounding.py:31-32`'s `quantize_money` uses `ROUND_HALF_EVEN`, not floor, for intermediate per-share/dollar figures. Immaterial in practice since final share quantities are always subsequently floored (`floor_to_int`), but is not literally "round down" if read as a standalone guarantee.

---

## Verified correctly implemented

The following claims — from the current code, not from prior report text — were independently confirmed and are **not** re-reported as findings:

- **Prompt-injection defense is real**: untrusted `catalyst_text`/`source_name` are sent via the Responses API's separate untrusted-input field, never concatenated into the system directive, and the bundled spec explicitly instructs the model to treat them as inert data (`daybreak_evaluator/transport.py:93-105`, spec §governing rules).
- **Evaluator spec hash pinning is enforced at runtime**, not documentation-only — `prompt.py:32-46` computes and compares SHA-256, raising on any mismatch; a dedicated test proves tampering is rejected.
- Evaluator input bounds (`catalyst_text` ≤4000 chars, `source_name` ≤256, ≤25 tickers, ≤5 disqualifier flags) and the `premarket_low <= current_price` relation are real, enforced Pydantic/invariant constraints.
- All input/output contract models are recursively closed (`extra="forbid"`, `additionalProperties:false` at every JSON Schema node).
- The evaluator fails closed on every terminal status (deadline, transport error, refusal, incomplete output, invalid JSON, schema-invalid, invariant-invalid).
- SQL parameterization is clean across every `persistence.py` in the repo — no f-string/`.format`/`%`-interpolated SQL text found anywhere; table/column identifiers use `psycopg.sql.Identifier` with hardcoded call-site literals only (`DB-13` re-verified closed).
- All nine Alembic migrations use static, non-interpolated DDL and remain atomic within Alembic's transaction wrapper.
- Compose requires an explicit Postgres password with no default (`:?Set DAYBREAK_POSTGRES_PASSWORD`), binds Postgres to loopback only, and both systemd units run as an unprivileged user with a full sandboxing directive set (`DB-15` re-verified closed).
- Deterministic `client_order_id` with idempotent lookup-before-submit is correctly implemented for the synchronous order-submission path (`DB-10` pattern present).
- The partial-fill cancel → refetch final quantity → revalidate protection sequence is correctly implemented (`DB-11` re-verified closed) — distinct from the ambiguous-close gap in `DB-18` above, which is in the flatten path, not the submit path.
- Trade-update deduplication via `claim_trade_update` is solid; risk and execution reservation event logs are genuinely append-only in both memory and Postgres backends.
- **The live-capital gate was adversarially re-verified and holds with no bypass found**: `live_capital_eligible`, `live_execution_enabled` (on `ConfigurationFreeze`), and `live_deployment_ready` are all `Literal[False]` inside strict, frozen Pydantic models — not defaults, type-level constants Pydantic's strict validation rejects overriding. The one plain-`bool` field, `SafetySettings.live_execution_enabled`, is guarded by a `model_validator` that raises on construction if `True`, with no `model_construct` bypass anywhere in the settings path. `AlpacaPaperBroker` additionally hardcodes its HTTP client to the literal paper base URL regardless of what a caller passes to its constructor.
- Risk-decision hashes are recomputed and compared (raise-on-mismatch), not merely stored; `review_production_candidate()` independently recomputes every nested manifest/attestation/freeze/ledger/deployment/rollback hash rather than trusting the input; request/decision identity collisions are correctly rejected in both backends; all quantity caps are floored; money math is `Decimal` throughout with no float creep.
- Flatten correctly scopes closes to Daybreak-owned orders/positions via client-order-id prefix and bracket-child graph walking, and repeated flatten invocations are idempotent because each re-derives live broker state — the double-submit risk in `DB-18` is specifically about an *ambiguous single-call failure*, not repeated invocation.
- All timestamped orchestration/leadership models reject naive datetimes and use DST-safe `ZoneInfo` conversion; `OrchestrationPolicy` enforces `allow_live_execution: Literal[False]` and the paper-only Alpaca base URL independently of the release-layer gate above.

## Verification standard observed

All of the following were executed offline during this audit and are green:

- `pytest`: 303 passed
- `pytest --cov ... --cov-branch --cov-fail-under=80`: 80.58% branch coverage
- `ruff format --check .` / `ruff check .`: clean
- `mypy --strict` across `daybreak` and every `daybreak_*` package: 0 issues
- `bandit --severity-level medium --confidence-level medium`: 0 findings (17 Low findings triaged by hand; two were genuine and are `DB-29`/`DB-30` above, the rest are internal-invariant assertions or a `subprocess` NTP probe with a fixed, non-attacker-controlled argument list)
- `pip-audit --skip-editable`: no known vulnerabilities
- `detect-secrets scan` over the tool's configured scope: 4 candidates, all false positives (an env-var *name*, a pinned spec SHA-256, and the `DB-29` default-credential pattern) — see `DB-26` for why this result should not be read as "no secrets in the repo"

## Release recommendation

Do not advance this offline candidate into target-environment paper qualification until `DB-16` and `DB-17` are fixed with regression tests reproducing the exact scenarios above (missing bracket leg reported as matched; alert-sink failure suppressing flatten). The High findings (`DB-18`–`DB-22`) sit in the same failure class — ambiguous-outcome handling and kill-switch reach during a live run — and should be closed in the same remediation pass rather than deferred, consistent with how `DB-01`–`DB-15` were treated as a single hardening release rather than triaged individually. The Medium and Low findings are real but lower-urgency; several (`DB-23`, `DB-24`) are about a mechanism that is not yet wired into any live authorization path and should be fixed before it is, not after.

None of these findings weaken the live-capital boundary itself, which was this audit's most rigorously tested claim and which holds.
