# Project Daybreak — Scanner Mode Effectiveness Audit

**Audit date:** 2026-08-03
**Audited ref:** `daybreak_scanner` package as merged through PR #9 (candidate discovery, RVOL, and the daily systemd automation), before this audit's fixes
**Classification:** research/signal-tracking mode — no paper or live order submission is part of this subsystem
**Scope:** this is not a re-run of the prior `DB-`-numbered independent audits of the core Daybreak trading engine. It is a focused, adversarial re-verification of the *scanner* subsystem added this session, asked for explicitly as "reverify each process for being the most effective way" rather than "does it pass its own tests." Findings use a new `SCAN-` ledger.

## Executive conclusion

The scanner's tests were all green and its own logic was internally consistent, but one design decision — cross-referencing Alpaca's `most-actives` screener to validate a gainer's volume — was **wrong for the domain it's applied to**, not just imprecise. `most-actives` is a global top-N ranking by raw share volume, which is unavoidably dominated by mega-cap, high-float names (large indices/ETFs and megacaps routinely trade tens of millions of shares a day). The scanner's actual targets — catalyst-driven small/mid-cap gap-and-go names clearing a 500,000-share floor — will almost never appear in a global top-50 (or even top-200) most-active list, because that list's bottom entries already require multiples of that volume. In practice this meant the scanner would very likely disqualify every real candidate, every day, with a misleading "not present in the most-actives snapshot" reason that reads like a data gap rather than a design defect. This is fixed in this audit (`SCAN-01`) by replacing the cross-reference with a per-symbol snapshot lookup scoped to exactly the gainers under consideration.

Two further issues were fixed as unambiguous correctness/robustness improvements (`SCAN-02` graceful degradation on a historical-bars fetch failure). The remaining findings (`SCAN-03` through `SCAN-07`) are judgment calls or reside in ambiguity that only a live Alpaca account can resolve — they are documented, not silently decided, because each one changes the scanner's actual behavior in a way the user should choose rather than have chosen for them.

## Finding summary

| ID | Severity | Area | Finding | Status |
|---|---|---|---|---|
| SCAN-01 | Critical | Discovery | Volume qualification cross-referenced a market-wide most-actives ranking that legitimate small-cap gainers would almost never appear in | **Fixed** |
| SCAN-02 | Medium | Resilience | A historical-bars fetch failure aborted the entire day's scan instead of degrading the (already-optional) RVOL check | **Fixed** |
| SCAN-03 | High | Timing | The daily scan runs at 09:35 ET, after regular-session open — later than the rest of the system's premarket-oriented `snapshot_time_et` (09:23 ET) — because Alpaca's movers endpoint documents unreliable data before market open | Open — needs a decision |
| SCAN-04 | High | Coverage | A single fixed-time daily scan sees one instant of a continuously-changing gainers list; a catalyst breaking later in the session is never seen that day | Open — needs a decision |
| SCAN-05 | Medium | Risk | No trading-halt check; a halt-resumption print can appear as an extreme "gainer" despite the feature contract having a dedicated `halted` field expecting this to be known | Open |
| SCAN-06 | Low | Verification | The screener's `top` parameter has an unconfirmed server-side maximum (SDK default is 10; the scanner requests 50) | Open — unverifiable without a live account |
| SCAN-07 | Low | Verification | Alpaca's own wording for the movers endpoint's "change" calculation ("previous closing price" vs "latest closing price") is ambiguous as to live-intraday freshness | Open — unverifiable without a live account |
| SCAN-08 | Informational | Design | `get_most_actives` no longer serves any purpose in the qualification path after `SCAN-01`; its future role (a secondary discovery signal, or removed) is undecided | Open |

---

## SCAN-01 (Critical, Fixed) — most-actives is the wrong volume source

**Before:** `qualify_candidates` looked up each gainer's volume from `AlpacaMarketDataClient.get_most_actives(top=50)` — the top 50 tickers **market-wide** ranked by raw volume. A ticker not in that list was treated as `None` (unknown volume) and disqualified with "ticker not present in the most-actives volume snapshot."

**Why this is wrong, not just imprecise:** the two lists are drawn from populations that barely overlap. Gainers-by-percent-change skews toward lower-float names because it takes comparatively little dollar volume to move a small float 10%+. Most-actives-by-raw-volume skews toward the largest, most liquid names in the market (broad ETFs, megacaps) precisely because their absolute share turnover dwarfs everything else — a stock can trade 2 million shares (4x the scanner's floor) and still be nowhere near a market-wide top-50/100 cut dominated by names trading 20-50x that. The practical result: on a typical day, the intersection of "today's top gainers" and "today's top-50 most-active" is likely to be empty or near-empty, meaning the scanner would report zero or near-zero qualifying candidates regardless of how many genuine catalyst setups existed that day — a silent, misleadingly-labeled failure mode rather than an honest "no candidates today."

**Fix:** added `AlpacaMarketDataClient.get_current_volumes(symbols)`, which calls Alpaca's `/v2/stocks/snapshots?symbols=...` endpoint and reads each requested symbol's `dailyBar.v` (today's cumulative volume) directly — scoped to exactly the gainers being evaluated, with no market-wide ranking or cutoff involved. `qualify_candidates` now takes a plain `volume_by_ticker: Mapping[str, int]` rather than a list of `ActiveStock` rows drawn from the wrong endpoint. `daybreak_scanner/cli.py`'s `scan` command was updated to call `get_current_volumes` instead of `get_most_actives`.

Files: `daybreak_scanner/alpaca_data.py`, `daybreak_scanner/discovery.py`, `daybreak_scanner/cli.py`, plus updated tests in `tests/scanner/`.

## SCAN-02 (Medium, Fixed) — a transient bars failure discarded an entire day's scan

**Before:** `_run_scan` fetched gainers, most-actives (now current volumes), and historical bars inside one `try` block; any `ScannerError` from *any* of the three — including a historical-bars fetch, whose only purpose is the already-optional RVOL check — aborted the whole run with no output file written.

**Why this matters:** `qualify_candidates` was explicitly designed to skip the RVOL check gracefully when no baseline is available (its own docstring says so), so it's inconsistent for the CLI wrapping it to treat a bars-fetch hiccup as fatal to gap/volume qualification too. On a real deployment this means a transient network blip on one of three calls silently produces *no scan output at all* for the day, rather than a scan that's simply missing its RVOL filter.

**Fix:** the historical-bars fetch is now wrapped in its own `try/except ScannerError`, logs a clear "historical bars unavailable, skipping RVOL" warning to stderr, and continues with an empty baseline — matching how `qualify_candidates` already treats a missing baseline. The gainers and current-volume fetches remain fatal on failure, correctly: current-session volume is a hard qualification input, and a failure there can't be distinguished from "every candidate genuinely has zero volume," so silently continuing would produce a misleadingly-empty result.

Files: `daybreak_scanner/cli.py`, plus a new test asserting the degraded-but-present output.

## SCAN-03 (High, Open) — scan timing conflicts with the system's own premarket design

The systemd timer (added in PR #9) fires at **09:35 America/New_York**, five minutes after the regular session opens. That choice was deliberate given `movers`'s documented behavior (its leaderboard "resets at market open" and shows the *previous* session's data until then), so scanning before 9:30 risked stale results.

But the rest of Project Daybreak is built around a **premarket** catalyst thesis: `daybreak_features.FeatureEngineConfig` defaults `premarket_start_et` to `04:00:00` and `snapshot_time_et` to `09:23:00` — i.e. the intended design freezes features and locks in a thesis *before* the open, using premarket price action as the primary signal. By 09:35, five minutes of regular-session trading have already happened; whatever premarket gap prompted a name to qualify may already be partially or fully priced in, and momentum/volume patterns from the open itself (which is a very different market microstructure than premarket) are now mixed into the gap % being measured.

This is a genuine, currently-unresolved tension between two things that both matter: data-source reliability (Alpaca's screener) and strategy fidelity (a premarket-gap thesis). Two ways to resolve it, not chosen unilaterally here:

1. **Accept post-open timing** as the practical cost of using Alpaca's screener for discovery, and treat the strategy as "early regular-session momentum" rather than strictly "premarket gap." Lowest engineering cost.
2. **Build a true premarket scan** using the snapshot endpoint's `latestTrade`/`prevDailyBar` fields (which do reflect live premarket prints, per Alpaca's SIP-data framing) against a broader static or semi-static ticker universe queried directly — not the `movers` screener at all. Materially more engineering work (a universe needs to come from somewhere; querying thousands of symbols via snapshots is heavier than one screener call) but faithful to the spec's actual premarket thesis.

## SCAN-04 (High, Open) — one scan per day is a thin sample of a continuously-changing list

The gainers/most-actives rankings change minute to minute. A single fixed-time run captures one instant of that; a real catalyst breaking at, say, 10:15 ET is invisible to the automated pipeline for the rest of the day. This wasn't a request in the original "make it automatic daily" ask, so it was deliberately not changed here, but it's worth surfacing: a scanner that polls periodically through the session (e.g. every 5–15 minutes, similar in spirit to how `daybreak_orchestration`'s policy has a `flatten_poll_interval_seconds`) would see substantially more of the day's real opportunity set than one snapshot at 09:35. This is a strategic choice (single daily discovery vs. continuous intraday monitoring), not a bug — flagging it for a decision rather than changing the timer's cadence unasked.

## SCAN-05 (Medium, Open) — no trading-halt check

`daybreak_features.models.CandidateSourceData.halted: bool = False` exists specifically because the feature engine's contract expects halt status to be known per candidate. The scanner doesn't check it at all right now. A halt-and-resume print can produce an extreme, qualifying-looking `percent_change` that is a materially different (and generally riskier) situation than an organic gap — the feature engine will eventually need real halt data to populate that field correctly regardless, so this is really the leading edge of the same gap task #3 is already blocked on (float data), not a new one, but worth naming explicitly since it's a risk-relevant omission in the scanner's own qualification logic today.

## SCAN-06 / SCAN-07 (Low, Open) — unverifiable without a live Alpaca account

- The screener's `top` parameter has a documented SDK default of 10; no confirmed server-side maximum was found for the value of 50 the scanner requests. If Alpaca silently clamps it lower, the scanner would see fewer gainers than intended without any error.
- Alpaca's own prose for the movers endpoint ("the change...is calculated from the previous closing price and the latest closing price") is ambiguous about whether "latest closing price" means a continuously-updating live price (consistent with the same doc's "real time SIP data" framing) or something that only updates once a symbol's regular session actually closes. The scanner's design assumes the former; this can't be confirmed from documentation alone.

Both should be spot-checked against a real account during market hours before this is trusted for anything beyond development.

## SCAN-08 (Informational, Open) — `get_most_actives`'s remaining role

After `SCAN-01`, `get_most_actives` is fully built, tested, and no longer called anywhere in the qualification path. Two reasonable futures for it: (a) repurpose it as a *secondary* discovery input — e.g. surface highly-active tickers that didn't make the percent-change-ranked gainers cut but are seeing unusual volume for another reason — or (b) remove it as dead weight. Left in place for now since it's harmless and already covered by tests, but its purpose should be decided rather than left implicitly "just in case."

## Verification

- `ruff format --check .` / `ruff check .` — clean (repo-wide)
- `mypy daybreak daybreak_*` (strict, CI scope) — 0 issues
- Full `pytest` suite — all passing, including updated/new tests for `SCAN-01` and `SCAN-02`
- `bandit -r ... --severity-level medium --confidence-level medium` — no issues
- `scripts/check_secrets.py` — 0 candidates
- No live Alpaca connectivity was available to this audit; `SCAN-06`/`SCAN-07` remain unverified for that reason, and every other finding was reached by static reading of the code, the merged PRs, and Alpaca's public documentation/SDK source — not by exercising a real account.
