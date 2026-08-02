# Daybreak Command Center

A polished, read-only GitHub Pages dashboard for Project Daybreak. It makes the paper-trading operating picture easy to track across four focused views:

- **Overview** — session state, market status, account curve, risk budget, positions, and alerts.
- **Trading** — ranked setups, managed positions, broker orders, filters, and setup details.
- **Performance** — equity, drawdown, outcomes, rank attribution, exit reasons, and trade history.
- **System** — all nine service layers, fail-closed safety controls, qualification progress, alerts, and release evidence.

The site has no third-party runtime dependencies, trackers, fonts, analytics, or order controls. It is static HTML, CSS, JavaScript modules, SVG, and JSON.

## Publish with GitHub Desktop

1. Extract the supplied ZIP.
2. Open GitHub Desktop and choose **File → Add local repository**.
3. Select the extracted `Project-Daybreak-Dashboard` folder.
4. Commit all files to `main`, then choose **Publish repository**.
5. On GitHub, open **Settings → Pages** and select **GitHub Actions** as the source.
6. Open **Actions → Deploy Daybreak Dashboard** and run the workflow.
7. Open the URL shown after the deployment completes.

The workflow validates the static artifact, checks JavaScript syntax, runs the data-layer tests, and deploys only `dashboard/`.

## Public-data boundary

GitHub Pages sites are public, even when their source repository is private. The supplied snapshot is explicitly fictional demonstration data. Never replace it with credentials, private identifiers, exact account values, or live positions.

For private detail, open the deployed page and select **Load private snapshot**. The selected JSON file stays in browser memory and is not uploaded or retained by the page.

## Local verification

Requires Python 3.12+ and Node.js 22+:

```bash
python scripts/validate_dashboard.py
node --check dashboard/assets/data.mjs
node --check dashboard/assets/app.mjs
node --test tests/dashboard/data.test.mjs
```

For a local preview:

```bash
python -m http.server 8000 --directory dashboard
```

Then open `http://localhost:8000/`.

## Operating boundary

This dashboard is informational only. It cannot place orders, reset a kill switch, change risk limits, connect to Alpaca, or enable live capital. The demonstration snapshot is paper-only and permanently live-capital-ineligible.
