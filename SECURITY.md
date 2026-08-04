# Security Policy

- Store Alpaca, OpenAI, database, and vendor credentials only in environment variables or an external secret manager.
- Never commit `.env` files.
- Use a dedicated Alpaca paper account for Daybreak; do not share its positions with another strategy or manual trading.
- Treat all broker timeouts as indeterminate until reconciled.
- Live execution is unavailable in v1.0.2. Do not weaken endpoint, environment, or `live_execution_enabled` guards.
- Treat fencing tokens as mandatory write preconditions in every concrete downstream hook.
- Authenticate human approvers outside the JSON evidence record; reviewer IDs alone are not digital signatures.
- Report suspected credential exposure by rotating the credential immediately before investigating logs.

## Dashboard (`dashboard/`)

The GitHub Pages dashboard under `dashboard/` is a read-only static site with no broker client,
order action, credential store, remote analytics, or third-party script — see `dashboard/README.md`.

- Treat every file below `dashboard/` as public; GitHub Pages is public even when the source
  repository is private.
- Keep `dashboard/data/dashboard.json` fictional and marked `public_safe: true`, `environment:
  "paper"`, and `safety.live_capital_eligible: false`.
- Never commit a real account snapshot, credential, exact private balance, exact private position,
  or broker order identifier under `dashboard/data/`.
- **Explicit, scoped exception:** `dashboard/data/dashboard.json` may instead carry real
  `daybreak_scanner` output (tickers, ATR-derived entry/stop/target prices, win/loss outcomes)
  committed automatically by `.github/workflows/scanner-scan.yml` and
  `scanner-check-outcomes.yml`, marked `data_mode: "published"` and `public_safe: true`
  (`daybreak_scanner/dashboard_export.py`'s `public=True` path). This is safe under the rule
  above because scanner mode never places a real order, sizes no position with real capital, and
  holds no account balance to leak — see `docs/audit/Project_Daybreak_Scanner_Mode_Audit_2026-08-03.md`.
  This exception is scoped exactly to that mechanical scanner data; every other rule in this
  section (no credential, no real account/broker data) still applies without exception.
- `index.html` ships a strict Content-Security-Policy (`default-src 'self'`; no inline
  scripts/styles/handlers; no third-party origin anywhere), and `app.mjs` renders every element with
  `createElement`/`textContent` — never `innerHTML` — so a malicious or malformed snapshot (published
  or privately loaded) cannot inject markup or execute script.
- `scripts/validate_dashboard.py` enforces the CSP, the no-inline/no-`innerHTML`/no-`eval` rules
  above, rejects credential-shaped JSON keys anywhere in the snapshot tree, external runtime assets,
  path escapes, and a committed snapshot that is not public-safe and paper-only against
  `dashboard/data/dashboard.schema.json`. It cannot judge whether arbitrary business text is
  confidential, so human review remains required before publishing new demo data.
- The page's "Load private snapshot" control (click or drag-and-drop) reads a local JSON file with
  `FileReader` entirely in browser memory; it is never uploaded, persisted, or sent to any endpoint
  by the page itself.
- `daybreak dashboard-snapshot` (`daybreak/dashboard_snapshot.py`) generates a real, private
  snapshot file for that control from Postgres and (optionally, with `--include-broker`) live
  Alpaca paper account data. It only ever writes a local file for manual loading — it never
  publishes, uploads, or touches anything under the deployed `dashboard/data/` tree.
