import assert from "node:assert/strict";
import test from "node:test";

import {
  clamp,
  formatAge,
  formatMoney,
  formatPercent,
  formatSignedMoney,
  freshnessState,
  isScannerMode,
  normalizeSnapshot,
  outcomeCounts,
  qualificationProgress,
  riskUtilization,
  statusTone,
  truncateHash,
} from "../../dashboard/assets/data.mjs";

function rawSnapshot(overrides = {}) {
  return {
    schema_version: "1.0",
    generated_at: "2026-08-02T14:00:00Z",
    data_mode: "published",
    environment: "paper",
    public_safe: true,
    ...overrides,
  };
}

test("normalizes a minimal valid snapshot with fail-closed defaults", () => {
  const value = normalizeSnapshot(rawSnapshot());
  assert.equal(value.safety.paper_only, true);
  assert.equal(value.safety.live_capital_eligible, false);
  assert.equal(value.safety.entries_enabled, false);
  assert.equal(value.system.timezone, "America/New_York");
  assert.deepEqual(value.signals, []);
});

test("normalizes numeric strings and status spelling", () => {
  const value = normalizeSnapshot(
    rawSnapshot({
      account: { equity: "50000.25", open_risk: "125", open_risk_limit: "500" },
      system: { phase: "Regular Session", freshness_threshold_seconds: "60" },
    }),
  );
  assert.equal(value.account.equity, 50000.25);
  assert.equal(value.system.phase, "regular_session");
  assert.equal(value.system.freshness_threshold_seconds, 60);
});

test("rejects unsupported schema versions", () => {
  assert.throws(() => normalizeSnapshot(rawSnapshot({ schema_version: "2.0" })), /Unsupported/);
});

test("rejects a malformed timestamp", () => {
  assert.throws(() => normalizeSnapshot(rawSnapshot({ generated_at: "yesterday" })), /generated_at/);
});

test("rejects non-object snapshots", () => {
  assert.throws(() => normalizeSnapshot([]), /JSON object/);
});

test("demo snapshots never claim freshness", () => {
  const snapshot = normalizeSnapshot(rawSnapshot({ data_mode: "demo" }));
  assert.deepEqual(freshnessState(snapshot, Date.parse("2026-08-02T14:00:10Z")), {
    status: "demo",
    ageSeconds: null,
    label: "Sample data",
  });
});

test("freshness uses fresh, aging, and stale thresholds", () => {
  const snapshot = normalizeSnapshot(
    rawSnapshot({ system: { freshness_threshold_seconds: 30 } }),
  );
  assert.equal(freshnessState(snapshot, Date.parse("2026-08-02T14:00:20Z")).status, "fresh");
  assert.equal(freshnessState(snapshot, Date.parse("2026-08-02T14:01:00Z")).status, "aging");
  assert.equal(freshnessState(snapshot, Date.parse("2026-08-02T14:02:00Z")).status, "stale");
});

test("formatters preserve sign and missing-value semantics", () => {
  assert.equal(formatMoney(null), "—");
  assert.equal(formatSignedMoney(12.5), "+$12.50");
  assert.equal(formatSignedMoney(-12.5), "−$12.50");
  assert.equal(formatPercent(0.125), "12.5%");
  assert.equal(formatAge(90), "1m ago");
});

test("qualification progress is target weighted and clamped", () => {
  const progress = qualificationProgress([
    { current: 15, target: 30 },
    { current: 50, target: 50 },
  ]);
  assert.equal(progress, 65 / 80);
  assert.equal(qualificationProgress([{ current: 3, target: 1 }]), 1);
});

test("risk utilization handles missing limits", () => {
  assert.equal(riskUtilization({ open_risk: 125, open_risk_limit: 500 }), 0.25);
  assert.equal(riskUtilization({ open_risk: 125, open_risk_limit: 0 }), null);
  assert.equal(riskUtilization({ open_risk: null, open_risk_limit: 500 }), null);
});

test("outcome counts derive from trade P&L when summary counts are absent", () => {
  assert.deepEqual(
    outcomeCounts({}, [{ net_pnl: 10 }, { net_pnl: -4 }, { net_pnl: 0 }]),
    { wins: 1, losses: 1, breakeven: 1, total: 3 },
  );
});

test("status tones remain deterministic", () => {
  assert.equal(statusTone("healthy"), "positive");
  assert.equal(statusTone("incomplete"), "warning");
  assert.equal(statusTone("failed"), "danger");
  assert.equal(statusTone("submitted"), "blue");
  assert.equal(statusTone("custom"), "neutral");
  assert.equal(statusTone("win"), "positive");
  assert.equal(statusTone("loss"), "danger");
});

test("scanner mode is detected from system.phase alone", () => {
  const scanner = normalizeSnapshot(rawSnapshot({ system: { phase: "scanning" } }));
  assert.equal(isScannerMode(scanner), true);
  const full = normalizeSnapshot(rawSnapshot({ system: { phase: "regular_session" } }));
  assert.equal(isScannerMode(full), false);
});

test("signals normalize target_price_2 and target_hit, defaulting to null", () => {
  const value = normalizeSnapshot(
    rawSnapshot({
      signals: [
        { ticker: "aaaa", rank: 1, status: "scanner_signal", conviction_score: 0, target_price: 24, target_price_2: 26, target_hit: "target_2" },
        { ticker: "bbbb", rank: 2, status: "scanner_signal", conviction_score: 0, target_price: 12 },
      ],
    }),
  );
  assert.equal(value.signals[0].target_price_2, 26);
  assert.equal(value.signals[0].target_hit, "target_2");
  assert.equal(value.signals[1].target_price_2, null);
  assert.equal(value.signals[1].target_hit, null);
});

test("performance summary normalizes target hit-rate fields", () => {
  const value = normalizeSnapshot(
    rawSnapshot({
      performance: {
        summary: { win_rate: 0.6, target_1_hit_rate: 0.4, target_2_hit_rate: 0.2, wins_target_1: 2, wins_target_2: 1 },
      },
    }),
  );
  assert.equal(value.performance.summary.target_1_hit_rate, 0.4);
  assert.equal(value.performance.summary.target_2_hit_rate, 0.2);
  assert.equal(value.performance.summary.wins_target_1, 2);
  assert.equal(value.performance.summary.wins_target_2, 1);
});

test("utility functions clamp values and truncate hashes", () => {
  assert.equal(clamp(4), 1);
  assert.equal(clamp(-1), 0);
  assert.equal(truncateHash("abcdefghij", 3), "abc…hij");
});
