# Security and privacy

The Daybreak Command Center is a read-only static site. It intentionally contains no broker client, order action, credential store, remote analytics, third-party script, or live-capital control.

## Publishing rules

- Treat every file below `dashboard/` as public.
- Keep `dashboard/data/dashboard.json` marked `public_safe: true`.
- Never commit credentials, private account identifiers, exact private balances, exact private positions, or order identifiers.
- Keep `environment` set to `paper` and `live_capital_eligible` set to `false`.
- Review every data change before publishing it.

The validator rejects known credential-shaped keys, external runtime assets, inline scripts, inline event handlers, dynamic code execution, path escapes, and a snapshot that is not public-safe and paper-only. It cannot determine whether arbitrary business text is confidential, so human review remains required.

Report a suspected exposure by making the Pages site unavailable, rotating affected credentials, removing the data from Git history, and following the incident process for the source trading platform.
