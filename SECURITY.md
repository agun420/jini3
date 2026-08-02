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
  "paper"`, and `live_capital_eligible: false`.
- Never commit a real account snapshot, credential, exact private balance, exact private position,
  or broker order identifier under `dashboard/data/`.
- `scripts/validate_dashboard.py` rejects credential-shaped JSON keys, inline scripts, inline event
  handlers, external runtime assets, dynamic code execution, path escapes, and a committed snapshot
  that is not public-safe and paper-only. It cannot judge whether arbitrary business text is
  confidential, so human review remains required before publishing new demo data.
- The page's "Load private snapshot" control reads a local JSON file with `FileReader` entirely in
  browser memory; it is never uploaded, persisted, or sent to any endpoint by the page itself.
