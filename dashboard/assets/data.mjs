// Pure data-layer functions for the Daybreak dashboard.
// No DOM access here so this module can be unit-tested with `node --test`.

const REQUIRED_TOP_LEVEL_KEYS = [
  "meta",
  "session",
  "account",
  "risk",
  "positions",
  "setups",
  "orders",
  "performance",
  "system",
];

export class SnapshotError extends Error {}

/**
 * Validate the shape of a parsed snapshot object and return it unchanged.
 * Throws SnapshotError with a human-readable reason on any structural problem.
 */
export function normalizeSnapshot(raw) {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new SnapshotError("snapshot must be a JSON object");
  }
  for (const key of REQUIRED_TOP_LEVEL_KEYS) {
    if (!(key in raw)) {
      throw new SnapshotError(`snapshot is missing required section "${key}"`);
    }
  }
  if (typeof raw.meta.environment !== "string") {
    throw new SnapshotError('snapshot.meta.environment must be a string');
  }
  if (typeof raw.meta.live_capital_eligible !== "boolean") {
    throw new SnapshotError("snapshot.meta.live_capital_eligible must be a boolean");
  }
  if (!Array.isArray(raw.positions)) {
    throw new SnapshotError("snapshot.positions must be an array");
  }
  if (!Array.isArray(raw.setups)) {
    throw new SnapshotError("snapshot.setups must be an array");
  }
  if (!Array.isArray(raw.orders)) {
    throw new SnapshotError("snapshot.orders must be an array");
  }
  if (!Array.isArray(raw.account.equity_curve)) {
    throw new SnapshotError("snapshot.account.equity_curve must be an array");
  }
  return raw;
}

/** True only for a snapshot explicitly marked safe to publish and paper-only. */
export function isPublicSafe(snapshot) {
  return (
    snapshot?.meta?.public_safe === true &&
    snapshot?.meta?.environment === "paper" &&
    snapshot?.meta?.live_capital_eligible === false
  );
}

export function computeRiskUsage(risk) {
  const max = Number(risk.max_open_risk_pct) || 0;
  const current = Number(risk.current_open_risk_pct) || 0;
  const remaining = Math.max(max - current, 0);
  const ratio = max > 0 ? Math.min(current / max, 1) : 0;
  return {
    maxPct: max,
    currentPct: round2(current),
    remainingPct: round2(remaining),
    ratio,
  };
}

export function computeDailyLossUsage(risk) {
  const max = Number(risk.max_daily_loss_pct) || 0;
  const current = Number(risk.current_daily_loss_pct) || 0;
  const ratio = max > 0 ? Math.min(current / max, 1) : 0;
  return { maxPct: max, currentPct: round2(current), ratio };
}

export function sortSetups(setups) {
  return [...setups].sort((a, b) => a.rank - b.rank);
}

export function filterSetupsByStatus(setups, status) {
  return setups.filter((setup) => setup.status === status);
}

export function groupExitReasons(trades) {
  const counts = new Map();
  for (const trade of trades) {
    const reason = trade.exit_reason ?? "unknown";
    counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }
  const total = trades.length;
  return [...counts.entries()]
    .map(([reason, count]) => ({
      reason,
      count,
      pct: total > 0 ? round1((count / total) * 100) : 0,
    }))
    .sort((a, b) => b.count - a.count);
}

export function summarizeTrades(trades) {
  const total = trades.length;
  const wins = trades.filter((trade) => trade.pnl > 0).length;
  const totalPnl = trades.reduce((sum, trade) => sum + trade.pnl, 0);
  const avgR =
    total > 0
      ? trades.reduce((sum, trade) => sum + (trade.r_multiple ?? 0), 0) / total
      : 0;
  return {
    totalTrades: total,
    wins,
    losses: total - wins,
    winRatePct: total > 0 ? round1((wins / total) * 100) : 0,
    totalPnl: round2(totalPnl),
    avgRMultiple: round2(avgR),
  };
}

export function equityCurveBounds(points) {
  if (!points.length) return { min: 0, max: 0 };
  let min = points[0].equity;
  let max = points[0].equity;
  for (const point of points) {
    if (point.equity < min) min = point.equity;
    if (point.equity > max) max = point.equity;
  }
  return { min, max };
}

/** Map an equity curve to normalized [0,1] SVG-space points for a given width/height. */
export function equityCurveToPath(points, width, height, padding = 4) {
  if (!points.length) return "";
  const { min, max } = equityCurveBounds(points);
  const span = max - min || 1;
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;
  const step = points.length > 1 ? usableWidth / (points.length - 1) : 0;
  return points
    .map((point, index) => {
      const x = padding + step * index;
      const y = padding + usableHeight * (1 - (point.equity - min) / span);
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

export function statusRank(status) {
  const order = { critical: 0, serious: 1, warning: 2, good: 3 };
  return order[status] ?? 4;
}

export function worstSystemStatus(layers) {
  if (!layers.length) return "good";
  return layers.reduce(
    (worst, layer) => (statusRank(layer.status) < statusRank(worst) ? layer.status : worst),
    "good",
  );
}

export function formatCurrency(value) {
  const n = Number(value) || 0;
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function formatPercent(value, digits = 2) {
  const n = Number(value) || 0;
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

export function formatCompactNumber(value) {
  const n = Number(value) || 0;
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(
    n,
  );
}

function round2(value) {
  return Math.round(value * 100) / 100;
}

function round1(value) {
  return Math.round(value * 10) / 10;
}
