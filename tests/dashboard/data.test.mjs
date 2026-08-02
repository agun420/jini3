import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import {
  normalizeSnapshot,
  SnapshotError,
  isPublicSafe,
  computeRiskUsage,
  computeDailyLossUsage,
  sortSetups,
  filterSetupsByStatus,
  groupExitReasons,
  summarizeTrades,
  equityCurveBounds,
  equityCurveToPath,
  worstSystemStatus,
  formatCurrency,
  formatPercent,
  formatCompactNumber,
} from "../../dashboard/assets/data.mjs";

const DASHBOARD_JSON_URL = new URL("../../dashboard/data/dashboard.json", import.meta.url);

async function loadDemoSnapshot() {
  const text = await readFile(fileURLToPath(DASHBOARD_JSON_URL), "utf8");
  return JSON.parse(text);
}

test("normalizeSnapshot accepts the shipped demo snapshot", async () => {
  const raw = await loadDemoSnapshot();
  const normalized = normalizeSnapshot(raw);
  assert.equal(normalized, raw);
});

test("normalizeSnapshot rejects a non-object", () => {
  assert.throws(() => normalizeSnapshot(null), SnapshotError);
  assert.throws(() => normalizeSnapshot([1, 2, 3]), SnapshotError);
  assert.throws(() => normalizeSnapshot("nope"), SnapshotError);
});

test("normalizeSnapshot rejects a missing top-level section", () => {
  assert.throws(() => normalizeSnapshot({ meta: {} }), /missing required section/);
});

test("normalizeSnapshot rejects a non-boolean live_capital_eligible", () => {
  const bad = {
    meta: { environment: "paper", live_capital_eligible: "false" },
    session: {},
    account: { equity_curve: [] },
    risk: {},
    positions: [],
    setups: [],
    orders: [],
    performance: {},
    system: {},
  };
  assert.throws(() => normalizeSnapshot(bad), /live_capital_eligible/);
});

test("isPublicSafe requires public_safe, paper environment, and ineligible live capital", async () => {
  const raw = await loadDemoSnapshot();
  assert.equal(isPublicSafe(raw), true);
  assert.equal(isPublicSafe({ meta: { public_safe: true, environment: "live", live_capital_eligible: false } }), false);
  assert.equal(isPublicSafe({ meta: { public_safe: true, environment: "paper", live_capital_eligible: true } }), false);
  assert.equal(isPublicSafe({ meta: { public_safe: false, environment: "paper", live_capital_eligible: false } }), false);
});

test("computeRiskUsage derives remaining budget and ratio", () => {
  const usage = computeRiskUsage({ max_open_risk_pct: 2, current_open_risk_pct: 0.5 });
  assert.equal(usage.remainingPct, 1.5);
  assert.equal(usage.ratio, 0.25);
});

test("computeRiskUsage clamps ratio at 1 when current exceeds max", () => {
  const usage = computeRiskUsage({ max_open_risk_pct: 2, current_open_risk_pct: 5 });
  assert.equal(usage.ratio, 1);
  assert.equal(usage.remainingPct, 0);
});

test("computeDailyLossUsage handles a zero max without dividing by zero", () => {
  const usage = computeDailyLossUsage({ max_daily_loss_pct: 0, current_daily_loss_pct: 0 });
  assert.equal(usage.ratio, 0);
});

test("sortSetups orders by rank without mutating the input", () => {
  const setups = [
    { rank: 3, ticker: "C" },
    { rank: 1, ticker: "A" },
    { rank: 2, ticker: "B" },
  ];
  const sorted = sortSetups(setups);
  assert.deepEqual(
    sorted.map((s) => s.ticker),
    ["A", "B", "C"],
  );
  assert.equal(setups[0].ticker, "C", "original array must not be mutated");
});

test("filterSetupsByStatus filters by exact status", () => {
  const setups = [
    { ticker: "A", status: "approved" },
    { ticker: "B", status: "qualified_not_selected" },
    { ticker: "C", status: "approved" },
  ];
  assert.deepEqual(
    filterSetupsByStatus(setups, "approved").map((s) => s.ticker),
    ["A", "C"],
  );
});

test("groupExitReasons counts and computes percentages", () => {
  const trades = [
    { exit_reason: "target" },
    { exit_reason: "target" },
    { exit_reason: "stop" },
    { exit_reason: "stop" },
  ];
  const grouped = groupExitReasons(trades);
  assert.deepEqual(grouped, [
    { reason: "target", count: 2, pct: 50 },
    { reason: "stop", count: 2, pct: 50 },
  ]);
});

test("groupExitReasons handles an empty trade list", () => {
  assert.deepEqual(groupExitReasons([]), []);
});

test("summarizeTrades computes win rate and totals", () => {
  const trades = [
    { pnl: 100, r_multiple: 1 },
    { pnl: -50, r_multiple: -0.5 },
    { pnl: 25, r_multiple: 0.25 },
  ];
  const summary = summarizeTrades(trades);
  assert.equal(summary.totalTrades, 3);
  assert.equal(summary.wins, 2);
  assert.equal(summary.losses, 1);
  assert.equal(summary.winRatePct, 66.7);
  assert.equal(summary.totalPnl, 75);
});

test("equityCurveBounds finds the min and max across points", () => {
  const bounds = equityCurveBounds([{ equity: 10 }, { equity: 4 }, { equity: 7 }]);
  assert.deepEqual(bounds, { min: 4, max: 10 });
});

test("equityCurveBounds handles an empty series", () => {
  assert.deepEqual(equityCurveBounds([]), { min: 0, max: 0 });
});

test("equityCurveToPath produces an SVG path string starting with M", () => {
  const path = equityCurveToPath([{ equity: 1 }, { equity: 2 }, { equity: 1.5 }], 100, 50);
  assert.match(path, /^M/);
  assert.equal(path.split(" ").length, 3);
});

test("equityCurveToPath returns an empty string for no points", () => {
  assert.equal(equityCurveToPath([], 100, 50), "");
});

test("worstSystemStatus prefers the most severe status present", () => {
  const layers = [{ status: "good" }, { status: "warning" }, { status: "good" }];
  assert.equal(worstSystemStatus(layers), "warning");
});

test("worstSystemStatus defaults to good for an empty layer list", () => {
  assert.equal(worstSystemStatus([]), "good");
});

test("formatCurrency formats negative values with a leading minus", () => {
  assert.equal(formatCurrency(1234.5), "$1,234.50");
  assert.equal(formatCurrency(-42), "-$42.00");
});

test("formatPercent signs positive values and rounds to the given precision", () => {
  assert.equal(formatPercent(1.856), "+1.86%");
  assert.equal(formatPercent(-0.5, 1), "-0.5%");
  assert.equal(formatPercent(0), "0.00%");
});

test("formatCompactNumber compacts large magnitudes", () => {
  assert.equal(formatCompactNumber(1500), "1.5K");
});
