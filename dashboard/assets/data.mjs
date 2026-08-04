const SUPPORTED_SCHEMA_VERSIONS = new Set(["1.0"]);

const objectOr = (value, fallback = {}) =>
  value && typeof value === "object" && !Array.isArray(value) ? value : fallback;

const arrayOr = (value) => (Array.isArray(value) ? value : []);

const numberOr = (value, fallback = null) => {
  if (value === null || value === undefined || value === "") return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const booleanOr = (value, fallback = false) =>
  typeof value === "boolean" ? value : fallback;

const stringOr = (value, fallback = "") =>
  typeof value === "string" && value.trim() ? value.trim() : fallback;

const normalizedStatus = (value, fallback = "unknown") =>
  stringOr(value, fallback).toLowerCase().replaceAll(" ", "_");

export function clamp(value, minimum = 0, maximum = 1) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return minimum;
  return Math.min(maximum, Math.max(minimum, numeric));
}

export function normalizeSnapshot(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new TypeError("Dashboard snapshot must be a JSON object.");
  }

  const schemaVersion = stringOr(raw.schema_version);
  if (!SUPPORTED_SCHEMA_VERSIONS.has(schemaVersion)) {
    throw new Error(
      `Unsupported dashboard schema version “${schemaVersion || "missing"}”. Expected 1.0.`,
    );
  }

  const generatedAt = stringOr(raw.generated_at);
  if (!generatedAt || Number.isNaN(Date.parse(generatedAt))) {
    throw new Error("Dashboard snapshot generated_at must be a valid ISO-8601 timestamp.");
  }

  const system = objectOr(raw.system);
  const safety = objectOr(raw.safety);
  const account = objectOr(raw.account);
  const session = objectOr(raw.session);
  const performance = objectOr(raw.performance);
  const summary = objectOr(performance.summary);
  const qualification = objectOr(raw.qualification);
  const release = objectOr(raw.release);

  return {
    schema_version: schemaVersion,
    generated_at: new Date(generatedAt).toISOString(),
    data_mode: normalizedStatus(raw.data_mode, "published"),
    environment: normalizedStatus(raw.environment, "paper"),
    public_safe: booleanOr(raw.public_safe, true),
    system: {
      name: stringOr(system.name, "Project Daybreak"),
      version: stringOr(system.version, "unknown"),
      specification_version: stringOr(system.specification_version, "unknown"),
      phase: normalizedStatus(system.phase),
      market_status: normalizedStatus(system.market_status),
      market_detail: stringOr(system.market_detail, "Status unavailable"),
      timezone: stringOr(system.timezone, "America/New_York"),
      freshness_threshold_seconds: Math.max(
        1,
        numberOr(system.freshness_threshold_seconds, 90),
      ),
    },
    safety: {
      paper_only: booleanOr(safety.paper_only, true),
      live_capital_eligible: booleanOr(safety.live_capital_eligible, false),
      kill_switch_active: booleanOr(safety.kill_switch_active),
      entries_enabled: booleanOr(safety.entries_enabled),
      all_positions_flat: booleanOr(safety.all_positions_flat, true),
      account_reconciled: booleanOr(safety.account_reconciled),
      leadership_valid: booleanOr(safety.leadership_valid),
      protective_orders_verified: booleanOr(safety.protective_orders_verified),
    },
    account: {
      currency: stringOr(account.currency, "USD"),
      equity: numberOr(account.equity),
      session_start_equity: numberOr(account.session_start_equity),
      buying_power: numberOr(account.buying_power),
      cash: numberOr(account.cash),
      gross_exposure: numberOr(account.gross_exposure),
      gross_exposure_limit: numberOr(account.gross_exposure_limit),
      open_risk: numberOr(account.open_risk),
      open_risk_limit: numberOr(account.open_risk_limit),
      daily_pnl: numberOr(account.daily_pnl),
      daily_pnl_pct: numberOr(account.daily_pnl_pct),
      realized_pnl: numberOr(account.realized_pnl),
      unrealized_pnl: numberOr(account.unrealized_pnl),
      hard_daily_loss_limit: numberOr(account.hard_daily_loss_limit),
    },
    session: {
      session_id: stringOr(session.session_id, "unavailable"),
      trading_date: stringOr(session.trading_date),
      state: normalizedStatus(session.state),
      state_detail: stringOr(session.state_detail, "State unavailable"),
      started_at: stringOr(session.started_at),
      next_transition_at: stringOr(session.next_transition_at),
      next_transition_label: stringOr(session.next_transition_label),
      raw_event_count: Math.max(0, numberOr(session.raw_event_count, 0)),
      evaluator_run_count: Math.max(0, numberOr(session.evaluator_run_count, 0)),
      approved_setup_count: Math.max(0, numberOr(session.approved_setup_count, 0)),
      qualified_setup_count: Math.max(0, numberOr(session.qualified_setup_count, 0)),
      excluded_ticker_count: Math.max(0, numberOr(session.excluded_ticker_count, 0)),
      orders_submitted: Math.max(0, numberOr(session.orders_submitted, 0)),
      orders_filled: Math.max(0, numberOr(session.orders_filled, 0)),
      invariant_violations: Math.max(0, numberOr(session.invariant_violations, 0)),
      unresolved_reconciliations: Math.max(
        0,
        numberOr(session.unresolved_reconciliations, 0),
      ),
      duplicate_order_count: Math.max(0, numberOr(session.duplicate_order_count, 0)),
    },
    performance: {
      summary: {
        session_count: Math.max(0, numberOr(summary.session_count, 0)),
        trade_count: Math.max(0, numberOr(summary.trade_count, 0)),
        winning_trade_count: Math.max(0, numberOr(summary.winning_trade_count, 0)),
        losing_trade_count: Math.max(0, numberOr(summary.losing_trade_count, 0)),
        breakeven_trade_count: Math.max(0, numberOr(summary.breakeven_trade_count, 0)),
        gross_pnl: numberOr(summary.gross_pnl),
        fees: numberOr(summary.fees),
        net_pnl: numberOr(summary.net_pnl),
        win_rate: numberOr(summary.win_rate),
        wins_target_1: Math.max(0, numberOr(summary.wins_target_1, 0)),
        wins_target_2: Math.max(0, numberOr(summary.wins_target_2, 0)),
        target_1_hit_rate: numberOr(summary.target_1_hit_rate),
        target_2_hit_rate: numberOr(summary.target_2_hit_rate),
        profit_factor: numberOr(summary.profit_factor),
        expectancy: numberOr(summary.expectancy),
        maximum_drawdown: numberOr(summary.maximum_drawdown),
        maximum_drawdown_pct: numberOr(summary.maximum_drawdown_pct),
        average_r_multiple: numberOr(summary.average_r_multiple),
        average_entry_slippage_bps: numberOr(summary.average_entry_slippage_bps),
      },
      equity_curve: arrayOr(performance.equity_curve).map((point) => ({
        timestamp: stringOr(objectOr(point).timestamp),
        equity: numberOr(objectOr(point).equity),
        drawdown: numberOr(objectOr(point).drawdown, 0),
      })),
      daily: arrayOr(performance.daily).map((day) => ({
        date: stringOr(objectOr(day).date),
        net_pnl: numberOr(objectOr(day).net_pnl, 0),
        trade_count: Math.max(0, numberOr(objectOr(day).trade_count, 0)),
        win_count: Math.max(0, numberOr(objectOr(day).win_count, 0)),
      })),
      attributions: arrayOr(performance.attributions).map((item) => ({
        dimension: stringOr(objectOr(item).dimension, "other"),
        key: stringOr(objectOr(item).key, "Unknown"),
        trade_count: Math.max(0, numberOr(objectOr(item).trade_count, 0)),
        net_pnl: numberOr(objectOr(item).net_pnl, 0),
        win_rate: numberOr(objectOr(item).win_rate, 0),
        average_r_multiple: numberOr(objectOr(item).average_r_multiple, 0),
      })),
      trades: arrayOr(performance.trades).map((trade) => normalizeTrade(trade)),
    },
    signals: arrayOr(raw.signals).map((signal) => normalizeSignal(signal)),
    positions: arrayOr(raw.positions).map((position) => normalizePosition(position)),
    orders: arrayOr(raw.orders).map((order) => normalizeOrder(order)),
    services: arrayOr(raw.services).map((service) => normalizeService(service)),
    qualification: {
      status: normalizedStatus(qualification.status, "incomplete"),
      items: arrayOr(qualification.items).map((item) => normalizeQualificationItem(item)),
      blockers: arrayOr(qualification.blockers).map((item) => stringOr(item)).filter(Boolean),
    },
    release: {
      status: normalizedStatus(release.status, "unknown"),
      release_version: stringOr(release.release_version, system.version || "unknown"),
      specification_version: stringOr(
        release.specification_version,
        system.specification_version || "unknown",
      ),
      tests_passed: numberOr(release.tests_passed),
      tests_collected: numberOr(release.tests_collected),
      branch_coverage_pct: numberOr(release.branch_coverage_pct),
      ruff_errors: numberOr(release.ruff_errors),
      mypy_errors: numberOr(release.mypy_errors),
      security_findings: numberOr(release.security_findings),
      dependency_vulnerabilities: numberOr(release.dependency_vulnerabilities),
      schema_count: numberOr(release.schema_count),
      invariant_count: numberOr(release.invariant_count),
      report_hash: stringOr(release.report_hash),
      generated_at: stringOr(release.generated_at),
      paper_release_candidate: booleanOr(release.paper_release_candidate),
      live_capital_eligible: booleanOr(release.live_capital_eligible),
    },
    alerts: arrayOr(raw.alerts).map((alert) => normalizeAlert(alert)),
  };
}

function normalizeSignal(value) {
  const signal = objectOr(value);
  return {
    ticker: stringOr(signal.ticker, "—").toUpperCase(),
    rank: Math.max(0, numberOr(signal.rank, 0)),
    status: normalizedStatus(signal.status, "unknown"),
    execution_status: normalizedStatus(signal.execution_status, "not_submitted"),
    conviction_score: clamp(numberOr(signal.conviction_score, 0), 0, 100),
    technical_grade: stringOr(signal.technical_grade, "—"),
    catalyst_source: stringOr(signal.catalyst_source, "Unavailable"),
    catalyst_age_hours: numberOr(signal.catalyst_age_hours),
    source_type: normalizedStatus(signal.source_type, "unknown"),
    corroborated: booleanOr(signal.corroborated),
    catalyst: stringOr(signal.catalyst, "Catalyst details unavailable."),
    thesis: stringOr(signal.thesis, "Thesis unavailable."),
    reference_price: numberOr(signal.reference_price),
    entry_price: numberOr(signal.entry_price),
    stop_price: numberOr(signal.stop_price),
    // "target_price" is target_price_1 -- the one target field this schema
    // shares with the full evaluator pipeline's own signals (daybreak_risk
    // only ever sizes one target). target_price_2/target_hit are new and
    // scanner-only: null/absent for every other signal source.
    target_price: numberOr(signal.target_price),
    target_price_2: numberOr(signal.target_price_2),
    target_hit: signal.target_hit === "target_1" || signal.target_hit === "target_2" ? signal.target_hit : null,
    quantity: numberOr(signal.quantity),
    modeled_risk: numberOr(signal.modeled_risk),
    risk_flags: arrayOr(signal.risk_flags).map((item) => stringOr(item)).filter(Boolean),
    rejection_reason: stringOr(signal.rejection_reason),
    updated_at: stringOr(signal.updated_at),
  };
}

function normalizePosition(value) {
  const position = objectOr(value);
  return {
    ticker: stringOr(position.ticker, "—").toUpperCase(),
    side: normalizedStatus(position.side, "long"),
    quantity: numberOr(position.quantity, 0),
    average_entry_price: numberOr(position.average_entry_price),
    last_price: numberOr(position.last_price),
    market_value: numberOr(position.market_value),
    unrealized_pnl: numberOr(position.unrealized_pnl),
    unrealized_pnl_pct: numberOr(position.unrealized_pnl_pct),
    stop_price: numberOr(position.stop_price),
    target_price: numberOr(position.target_price),
    protective_status: normalizedStatus(position.protective_status, "unknown"),
    updated_at: stringOr(position.updated_at),
  };
}

function normalizeOrder(value) {
  const order = objectOr(value);
  return {
    submitted_at: stringOr(order.submitted_at),
    ticker: stringOr(order.ticker, "—").toUpperCase(),
    side: normalizedStatus(order.side),
    type: normalizedStatus(order.type),
    order_class: normalizedStatus(order.order_class),
    quantity: numberOr(order.quantity, 0),
    filled_quantity: numberOr(order.filled_quantity, 0),
    price: numberOr(order.price),
    status: normalizedStatus(order.status),
    client_order_id: stringOr(order.client_order_id, "Unavailable"),
  };
}

function normalizeService(value) {
  const service = objectOr(value);
  return {
    name: stringOr(service.name, "Unknown service"),
    status: normalizedStatus(service.status),
    detail: stringOr(service.detail, "No health detail supplied."),
    latency_ms: numberOr(service.latency_ms),
    updated_at: stringOr(service.updated_at),
  };
}

function normalizeQualificationItem(value) {
  const item = objectOr(value);
  return {
    key: stringOr(item.key, "unknown"),
    label: stringOr(item.label, "Unnamed requirement"),
    detail: stringOr(item.detail),
    current: Math.max(0, numberOr(item.current, 0)),
    target: Math.max(0, numberOr(item.target, 1)),
    status: normalizedStatus(item.status, "pending"),
  };
}

function normalizeAlert(value) {
  const alert = objectOr(value);
  return {
    severity: normalizedStatus(alert.severity, "info"),
    title: stringOr(alert.title, "Operating event"),
    message: stringOr(alert.message, "No detail supplied."),
    timestamp: stringOr(alert.timestamp),
    source: stringOr(alert.source, "Daybreak"),
  };
}

function normalizeTrade(value) {
  const trade = objectOr(value);
  return {
    date: stringOr(trade.date),
    ticker: stringOr(trade.ticker, "—").toUpperCase(),
    rank: Math.max(0, numberOr(trade.rank, 0)),
    entry_price: numberOr(trade.entry_price),
    exit_price: numberOr(trade.exit_price),
    net_pnl: numberOr(trade.net_pnl),
    r_multiple: numberOr(trade.r_multiple),
    exit_reason: normalizedStatus(trade.exit_reason, "unknown"),
  };
}

export function freshnessState(snapshot, now = Date.now()) {
  if (snapshot.data_mode === "demo") {
    return { status: "demo", ageSeconds: null, label: "Sample data" };
  }

  const generated = Date.parse(snapshot.generated_at);
  if (!Number.isFinite(generated)) {
    return { status: "error", ageSeconds: null, label: "Invalid timestamp" };
  }

  const ageSeconds = Math.max(0, Math.floor((now - generated) / 1000));
  const threshold = Math.max(1, snapshot.system.freshness_threshold_seconds || 90);
  if (ageSeconds <= threshold) {
    return { status: "fresh", ageSeconds, label: `Fresh · ${formatAge(ageSeconds)}` };
  }
  if (ageSeconds <= threshold * 3) {
    return { status: "aging", ageSeconds, label: `Aging · ${formatAge(ageSeconds)}` };
  }
  return { status: "stale", ageSeconds, label: `Stale · ${formatAge(ageSeconds)}` };
}

export function formatAge(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "unknown";
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function formatMoney(value, currency = "USD", options = {}) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const compact = Boolean(options.compact);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    notation: compact ? "compact" : "standard",
    minimumFractionDigits: compact ? 0 : 2,
    maximumFractionDigits: compact ? 1 : 2,
  }).format(Number(value));
}

export function formatSignedMoney(value, currency = "USD") {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const formatted = formatMoney(Math.abs(Number(value)), currency);
  if (Number(value) > 0) return `+${formatted}`;
  if (Number(value) < 0) return `−${formatted}`;
  return formatted;
}

export function formatPercent(value, options = {}) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const digits = Number.isInteger(options.digits) ? options.digits : 1;
  const numeric = Number(value) * (options.alreadyPercent ? 1 : 100);
  const prefix = options.signed && numeric > 0 ? "+" : "";
  return `${prefix}${numeric.toFixed(digits)}%`;
}

export function formatNumber(value, options = {}) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("en-US", {
    notation: options.compact ? "compact" : "standard",
    maximumFractionDigits: Number.isInteger(options.digits) ? options.digits : 0,
  }).format(Number(value));
}

export function formatPrice(value, currency = "USD") {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(Number(value));
}

export function formatDateTime(value, options = {}) {
  if (!value || Number.isNaN(Date.parse(value))) return "—";
  const timeZone = options.timeZone || "America/New_York";
  return new Intl.DateTimeFormat("en-US", {
    timeZone,
    month: options.includeDate === false ? undefined : "short",
    day: options.includeDate === false ? undefined : "numeric",
    year: options.includeYear ? "numeric" : undefined,
    hour: "numeric",
    minute: "2-digit",
    second: options.seconds ? "2-digit" : undefined,
    timeZoneName: options.zone ? "short" : undefined,
  }).format(new Date(value));
}

export function humanize(value) {
  const text = stringOr(value, "Unknown").replaceAll("_", " ");
  return text.replace(/\b\w/g, (character) => character.toUpperCase());
}

export function qualificationProgress(items) {
  const values = arrayOr(items);
  if (!values.length) return 0;
  const total = values.reduce((sum, item) => sum + Math.max(1, numberOr(item.target, 1)), 0);
  const completed = values.reduce(
    (sum, item) =>
      sum + Math.min(Math.max(0, numberOr(item.current, 0)), Math.max(1, numberOr(item.target, 1))),
    0,
  );
  return total ? clamp(completed / total) : 0;
}

export function riskUtilization(account) {
  const openRisk = numberOr(objectOr(account).open_risk);
  const limit = numberOr(objectOr(account).open_risk_limit);
  if (openRisk === null || limit === null || limit <= 0) return null;
  return clamp(openRisk / limit, 0, 10);
}

export function outcomeCounts(summary, trades = []) {
  const normalized = objectOr(summary);
  let wins = numberOr(normalized.winning_trade_count);
  let losses = numberOr(normalized.losing_trade_count);
  let breakeven = numberOr(normalized.breakeven_trade_count);

  if (wins === null || losses === null || breakeven === null) {
    wins = 0;
    losses = 0;
    breakeven = 0;
    for (const trade of arrayOr(trades)) {
      const pnl = numberOr(objectOr(trade).net_pnl, 0);
      if (pnl > 0) wins += 1;
      else if (pnl < 0) losses += 1;
      else breakeven += 1;
    }
  }
  return { wins, losses, breakeven, total: wins + losses + breakeven };
}

export function statusTone(status) {
  const normalized = normalizedStatus(status);
  if (["healthy", "verified", "passed", "approved", "filled", "protected", "active", "win"].includes(normalized)) {
    return "positive";
  }
  if (["warning", "degraded", "pending", "incomplete", "qualified", "partially_filled"].includes(normalized)) {
    return "warning";
  }
  if (["critical", "offline", "failed", "blocked", "rejected", "canceled", "active_kill", "loss"].includes(normalized)) {
    return "danger";
  }
  if (["normal", "paper_release_candidate", "paper_qualified", "submitted", "accepted"].includes(normalized)) {
    return "blue";
  }
  return "neutral";
}

// True for a snapshot published by daybreak_scanner (mechanical entry/stop/
// target signals, no evaluator/account/order data) rather than the full
// evaluator-risk-execution pipeline -- see daybreak_scanner/dashboard_export.py,
// which is the only exporter that ever sets system.phase to "scanning".
export function isScannerMode(snapshot) {
  return snapshot.system.phase === "scanning";
}

export function truncateHash(value, size = 12) {
  const text = stringOr(value);
  if (!text) return "Unavailable";
  if (text.length <= size * 2 + 1) return text;
  return `${text.slice(0, size)}…${text.slice(-size)}`;
}
