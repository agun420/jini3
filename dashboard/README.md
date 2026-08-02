# Daybreak Command Center

A read-only GitHub Pages dashboard for Project Daybreak. It tracks the paper-trading operating
picture across four views:

- **Overview** — session state, market status, account curve, risk budget, positions, and alerts.
- **Trading** — ranked setups, managed positions, broker orders.
- **Performance** — trade history, exit-reason breakdown, and rank attribution.
- **System** — all nine service layers, fail-closed safety controls, qualification progress, and
  release evidence.

It has no third-party runtime dependencies, trackers, fonts, analytics, or order controls — static
HTML, CSS, a JavaScript module pair, and JSON. It cannot place an order, reset the kill switch,
change a risk limit, or connect to a broker.

## Data

`data/dashboard.json` is fictional, public-safe demonstration data (see `meta.note` in the file
itself). It ships with the repository and is what GitHub Pages serves by default.

To look at your own paper-session evidence without publishing it anywhere, open the deployed page
and select **Load private snapshot**, then pick a JSON file shaped like `data/dashboard.json`. The
file is read with `FileReader` and kept in that browser tab's memory only — the page has no upload
path, so nothing leaves your machine. Never commit a private snapshot; `dashboard/data/private*.json`
and `dashboard/data/local*.json` are gitignored as a backstop.

## Local verification

Requires Python 3.12+ and Node.js 22+:

```bash
python scripts/validate_dashboard.py
node --check dashboard/assets/data.mjs
node --check dashboard/assets/app.mjs
node --test tests/dashboard/*.test.mjs
```

`validate_dashboard.py` rejects credential-shaped JSON keys, inline `<script>` bodies, inline event
handlers, references to external `http(s)` assets, dynamic code execution (`eval`, `new Function`),
and any local reference that would escape `dashboard/`. It also requires every committed snapshot
under `dashboard/data/` to declare `environment: "paper"`, `live_capital_eligible: false`, and
`public_safe: true`.

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
