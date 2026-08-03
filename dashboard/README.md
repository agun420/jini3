# Daybreak Command Center

A read-only GitHub Pages dashboard for Project Daybreak. It tracks the paper-trading operating
picture across four views:

- **Overview** — session state, market status, account curve, risk gauge, today's setup board,
  system pulse, qualification progress, and the alert desk.
- **Trading** — searchable/filterable ranked setups with a decision-detail dialog, managed
  positions, and the broker order ledger.
- **Performance** — equity-and-drawdown chart, win/loss/breakeven distribution, daily P&L, outcome
  attribution, and trade history.
- **System** — all nine service layers, fail-closed safety interlocks, qualification evidence, and
  release/build evidence.

It has no third-party runtime dependencies, trackers, fonts, analytics, or order controls — static
HTML, CSS, two JavaScript modules, an SVG favicon, and JSON. `index.html` ships a strict
Content-Security-Policy (`default-src 'self'`, no inline scripts/styles/handlers), and
`app.mjs` builds every DOM node with `createElement`/`textContent` — never `innerHTML` — so
snapshot data can't inject markup. It cannot place an order, reset the kill switch, change a risk
limit, or connect to a broker.

## Data

`data/dashboard.json` (validated against `data/dashboard.schema.json`) is fictional, public-safe
demonstration data (`data_mode: "demo"`, `environment: "paper"`, `live_capital_eligible: false`) —
see its `generated_at`/`data_mode` fields. It ships with the repository and is what GitHub Pages
serves by default; the page re-fetches it every 30 seconds and shows a freshness chip (fresh /
aging / stale) so a stale publish is visible at a glance.

To look at your own paper-session evidence without publishing it anywhere, open the deployed page
and select **Load private snapshot** (or drag a JSON file onto the page), picking a file shaped
like `data/dashboard.json`. The file is read with `FileReader` and kept in that browser tab's
memory only — the page has no upload path, so nothing leaves your machine. Never commit a private
snapshot; `dashboard/data/private*.json` and `dashboard/data/local*.json` are gitignored as a
backstop.

### Generating a real private snapshot

The `daybreak dashboard-snapshot` CLI command builds a snapshot file from the actual system —
Postgres-backed session, risk, evaluator, analytics, operations, and release state, plus (with
`--include-broker`) live Alpaca paper positions, orders, and account data:

```bash
export DAYBREAK_DATABASE_URL=postgresql://...
export APCA_API_KEY_ID=...       # only needed with --include-broker
export APCA_API_SECRET_KEY=...   # only needed with --include-broker
daybreak dashboard-snapshot <session_id> <trading_date> \
    --include-broker \
    --output dashboard/data/private.json
```

`database.enabled` must be `true` in the config passed via `--config` (default
`config/daybreak.example.toml`). Coverage is intentionally honest, not complete: several
Daybreak packages are append-only event stores with no "current state" read path, so fields
without a real source (the equity curve, per-layer service health, several release-evidence
metrics) are emitted as null or empty rather than fabricated — see
`daybreak/dashboard_snapshot.py` for the exact mapping and its documented gaps. The output is
written outside the dashboard's published tree by convention (`dashboard/data/private*.json` is
gitignored) — load it through **Load private snapshot**, never commit it.

## Local verification

Requires Python 3.12+ and Node.js 22+:

```bash
python scripts/validate_dashboard.py
node --check dashboard/assets/data.mjs
node --check dashboard/assets/app.mjs
node --test tests/dashboard/*.test.mjs
```

`validate_dashboard.py` checks the HTML (required CSP directives, no inline scripts/styles/event
handlers, no duplicate ids, every local asset reference resolves inside `dashboard/`), the JSON
snapshot and its schema (required top-level keys, `environment: "paper"`, `public_safe: true`,
`live_capital_eligible: false`, no credential-shaped keys anywhere in the tree), and the JS/CSS
assets (no external `http(s)` URLs, no `eval`/`new Function`, no `innerHTML`, `data.mjs` performs
no network requests, the favicon SVG parses, every asset stays under 1&nbsp;MB).

## Local preview

```bash
python -m http.server 8000 --directory dashboard
```

Then open `http://localhost:8000/`.

## Publishing

The `Deploy Daybreak Dashboard` GitHub Actions workflow (`.github/workflows/deploy-dashboard.yml`)
runs the validator, checks module syntax, runs the data-layer tests, and — on push to `main` —
deploys only the `dashboard/` directory to GitHub Pages.

One-time repository setup: open **Settings → Pages** and set **Source** to **GitHub Actions**. After
that, every push to `main` that touches `dashboard/` redeploys automatically; you can also run the
workflow manually from **Actions → Deploy Daybreak Dashboard → Run workflow**.

See `SECURITY.md` for the public-data boundary this dashboard operates under.
