import {
  clamp,
  formatAge,
  formatDateTime,
  formatMoney,
  formatNumber,
  formatPercent,
  formatPrice,
  formatSignedMoney,
  freshnessState,
  humanize,
  isScannerMode,
  normalizeSnapshot,
  outcomeCounts,
  qualificationProgress,
  riskUtilization,
  statusTone,
  truncateHash,
} from "./data.mjs";

const DATA_URL = "data/dashboard.json";
const SVG_NS = "http://www.w3.org/2000/svg";
const VIEW_META = {
  overview: ["Live operating picture", "Command Center"],
  trading: ["Evaluator, risk, and execution", "Trading Desk"],
  performance: ["Paper outcomes and attribution", "Performance"],
  system: ["Health, qualification, and evidence", "System & Safety"],
};

const state = {
  snapshot: null,
  source: "published",
  sourceLabel: "Published snapshot",
  currentView: "overview",
  currentTradingTab: "signals",
  refreshTimer: null,
  clockTimer: null,
  toastTimer: null,
};

const byId = (id) => document.getElementById(id);
const all = (selector, root = document) => [...root.querySelectorAll(selector)];

function element(tag, options = {}) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = String(options.text);
  if (options.attrs) {
    for (const [name, value] of Object.entries(options.attrs)) {
      if (value !== null && value !== undefined) node.setAttribute(name, String(value));
    }
  }
  return node;
}

function svgElement(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
  return node;
}

function clear(node) {
  node.replaceChildren();
}

function setText(id, value) {
  const node = byId(id);
  if (node) node.textContent = value ?? "—";
}

function setTone(node, tone) {
  node.classList.remove("pill-positive", "pill-warning", "pill-danger", "pill-blue", "pill-neutral");
  node.classList.add(`pill-${tone || "neutral"}`);
}

function toneForNumber(value) {
  if (value === null || value === undefined) return "neutral";
  if (Number(value) > 0) return "positive";
  if (Number(value) < 0) return "negative";
  return "neutral";
}

function showToast(message) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(state.toastTimer);
  state.toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, 3500);
}

async function loadPublished({ announce = false } = {}) {
  const refreshButton = byId("refresh-button");
  refreshButton.disabled = true;
  refreshButton.classList.add("is-spinning");
  try {
    const response = await fetch(`${DATA_URL}?v=${Date.now()}`, {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`Snapshot request failed with status ${response.status}.`);
    const raw = await response.json();
    state.snapshot = normalizeSnapshot(raw);
    state.source = "published";
    state.sourceLabel = "Published dashboard.json";
    renderAll();
    schedulePublishedRefresh();
    if (announce) showToast("Published snapshot refreshed.");
  } catch (error) {
    renderLoadError(error instanceof Error ? error.message : "Snapshot could not be loaded.");
  } finally {
    refreshButton.disabled = false;
    refreshButton.classList.remove("is-spinning");
  }
}

function schedulePublishedRefresh() {
  window.clearInterval(state.refreshTimer);
  if (state.source !== "published") return;
  state.refreshTimer = window.setInterval(() => loadPublished(), 30_000);
}

async function loadLocalFile(file) {
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    showToast("Snapshot rejected: the file is larger than 5 MB.");
    return;
  }
  try {
    const raw = JSON.parse(await file.text());
    state.snapshot = normalizeSnapshot(raw);
    state.source = "local";
    state.sourceLabel = `Local file · ${file.name}`;
    window.clearInterval(state.refreshTimer);
    renderAll();
    showToast("Private snapshot loaded in this browser only.");
  } catch (error) {
    showToast(error instanceof Error ? error.message : "The selected JSON file is invalid.");
  }
}

function renderLoadError(message) {
  const banner = byId("source-banner");
  banner.dataset.mode = "error";
  setText("source-banner-title", "Published snapshot unavailable");
  setText("source-banner-message", `${message} Load a private snapshot or retry.`);
  setText("freshness-text", "Data unavailable");
  byId("freshness-chip").dataset.status = "error";
}

function renderAll() {
  if (!state.snapshot) return;
  renderShell();
  renderOverview();
  renderTrading();
  renderPerformance();
  renderSystem();
  updateFreshness();
}

function renderShell() {
  const snapshot = state.snapshot;
  const releaseVersion = snapshot.release.release_version || snapshot.system.version;
  setText("sidebar-version", `v${releaseVersion}`);
  setText("sidebar-mode", snapshot.safety.paper_only ? "Paper only" : humanize(snapshot.environment));
  setText("nav-signal-count", snapshot.signals.length);

  const hasHighAlert = snapshot.alerts.some((alert) => ["critical", "error"].includes(alert.severity));
  byId("nav-alert-dot").hidden = !hasHighAlert;

  const banner = byId("source-banner");
  const restore = byId("restore-published-button");
  if (state.source === "local") {
    banner.dataset.mode = "local";
    setText("source-banner-title", "Private local snapshot");
    setText(
      "source-banner-message",
      "Rendered in browser memory only. This file was not uploaded or saved by the dashboard.",
    );
    restore.hidden = false;
  } else if (snapshot.data_mode === "demo") {
    banner.dataset.mode = "demo";
    setText("source-banner-title", "Demonstration snapshot");
    setText(
      "source-banner-message",
      "All tickers, trades, balances, and operating values shown here are fictional examples.",
    );
    restore.hidden = true;
  } else if (snapshot.public_safe) {
    banner.dataset.mode = "published";
    setText("source-banner-title", "Public-safe published snapshot");
    setText(
      "source-banner-message",
      "Sensitive tickers, positions, balances, and private identifiers are redacted for GitHub Pages.",
    );
    restore.hidden = true;
  } else {
    banner.dataset.mode = "published";
    setText("source-banner-title", "Published snapshot contains sensitive fields");
    setText(
      "source-banner-message",
      "GitHub Pages is public. Replace this file with a public-safe export immediately.",
    );
    restore.hidden = true;
  }
  setText("footer-source", `Source: ${state.sourceLabel}`);

  const scannerMode = isScannerMode(snapshot);
  byId("scanner-mode-banner").hidden = !scannerMode;
  byId("overview-primary-grid").hidden = scannerMode;
}

function updateFreshness() {
  if (!state.snapshot) return;
  const freshness = freshnessState(state.snapshot);
  const chip = byId("freshness-chip");
  chip.dataset.status = freshness.status;
  setText("freshness-text", state.source === "local" && freshness.status !== "demo" ? `Local · ${freshness.label}` : freshness.label);

  const observed = new Date(state.snapshot.generated_at);
  const timezone = state.snapshot.system.timezone;
  setText(
    "observed-time",
    observed.toLocaleTimeString("en-US", {
      timeZone: timezone,
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
    }),
  );
  setText(
    "observed-date",
    observed.toLocaleDateString("en-US", {
      timeZone: timezone,
      weekday: "short",
      month: "short",
      day: "numeric",
    }),
  );
  byId("status-strip").children[3].dataset.tone =
    freshness.status === "fresh"
      ? "positive"
      : ["demo", "aging"].includes(freshness.status)
        ? "warning"
        : "danger";
}

function renderOverview() {
  const { account, safety, session, system } = state.snapshot;
  const currency = account.currency;
  setText("session-state", humanize(session.state));
  setText("session-clock", session.state_detail);
  setText("market-status", humanize(system.market_status));
  setText("market-detail", system.market_detail);
  setText("safety-state", safety.kill_switch_active ? "Kill switch active" : "Controls normal");
  setText(
    "safety-detail",
    safety.paper_only
      ? safety.entries_enabled
        ? "Paper entries enabled"
        : "Paper entries paused"
      : "Mode requires review",
  );
  byId("status-strip").children[0].dataset.tone = safety.kill_switch_active ? "danger" : "positive";
  byId("status-strip").children[1].dataset.tone = system.market_status.includes("closed") ? "neutral" : "positive";
  byId("status-strip").children[2].dataset.tone = safety.kill_switch_active ? "danger" : safety.entries_enabled ? "positive" : "warning";

  const scannerMode = isScannerMode(state.snapshot);
  if (scannerMode) {
    // Scanner mode never sizes a real dollar position, so paper P&L/equity/
    // positions/orders/risk are all meaningless here -- lead with what the
    // engine actually produced: setups found and how they've resolved so far.
    const summary = state.snapshot.performance.summary;
    const decided = summary.winning_trade_count + summary.losing_trade_count;
    renderKpis(byId("overview-kpis"), [
      {
        label: "Approved setups",
        value: formatNumber(session.approved_setup_count),
        footer: "Signals today",
        footerValue: formatNumber(state.snapshot.signals.length),
        icon: "✓",
        tone: "blue",
      },
      {
        label: "Win rate",
        value: formatPercent(summary.win_rate),
        footer: "Wins / decided",
        footerValue: `${formatNumber(summary.winning_trade_count)} / ${formatNumber(decided)}`,
        icon: "◎",
        tone: "positive",
      },
      {
        label: "Target 1 hit rate",
        value: formatPercent(summary.target_1_hit_rate),
        footer: "2x ATR",
        footerValue: formatNumber(summary.wins_target_1),
        icon: "→",
        tone: "positive",
      },
      {
        label: "Target 2 hit rate",
        value: formatPercent(summary.target_2_hit_rate),
        footer: "3x ATR stretch",
        footerValue: formatNumber(summary.wins_target_2),
        icon: "⇒",
        tone: "positive",
      },
    ]);
  } else {
    const dailyTone = toneForNumber(account.daily_pnl);
    renderKpis(byId("overview-kpis"), [
      {
        label: "Today’s paper P&L",
        value: formatSignedMoney(account.daily_pnl, currency),
        footer: "Realized",
        footerValue: formatSignedMoney(account.realized_pnl, currency),
        icon: "$",
        tone: dailyTone,
        valueClass: dailyTone,
      },
      {
        label: "Paper equity",
        value: formatMoney(account.equity, currency),
        footer: "Session start",
        footerValue: formatMoney(account.session_start_equity, currency),
        icon: "◫",
        tone: "blue",
      },
      {
        label: "Managed positions",
        value: formatNumber(state.snapshot.positions.length),
        footer: "Gross exposure",
        footerValue: formatMoney(account.gross_exposure, currency, { compact: true }),
        icon: "↗",
        tone: safety.all_positions_flat ? "positive" : "warning",
      },
      {
        label: "Orders filled",
        value: `${formatNumber(session.orders_filled)} / ${formatNumber(session.orders_submitted)}`,
        footer: "Approved setups",
        footerValue: formatNumber(session.approved_setup_count),
        icon: "✓",
        tone: session.unresolved_reconciliations ? "warning" : "positive",
      },
    ]);

    const curve = state.snapshot.performance.equity_curve;
    renderLineChart(byId("equity-chart"), curve, {
      valueKey: "equity",
      labelKey: "timestamp",
      formatter: (value) => formatMoney(value, currency, { compact: true }),
      title: "Paper equity",
    });
    const firstEquity = curve.find((point) => point.equity !== null)?.equity ?? null;
    const lastEquity = [...curve].reverse().find((point) => point.equity !== null)?.equity ?? null;
    const equityChange = firstEquity !== null && lastEquity !== null ? lastEquity - firstEquity : null;
    setText("equity-period-label", `${formatNumber(curve.length)} observations`);
    setText("equity-change", formatSignedMoney(equityChange, currency));
    byId("equity-change").className = toneForNumber(equityChange);
    renderEquityFooter(curve, currency);

    const utilization = riskUtilization(account);
    const riskPercent = utilization === null ? null : utilization * 100;
    byId("risk-gauge").style.setProperty("--value", `${clamp(utilization ?? 0) * 360}deg`);
    setText("risk-gauge-value", riskPercent === null ? "—" : `${riskPercent.toFixed(0)}%`);
    const riskTone = utilization === null ? "neutral" : utilization >= 0.85 ? "danger" : utilization >= 0.65 ? "warning" : "positive";
    setText("risk-state-pill", utilization === null ? "Unavailable" : utilization >= 0.85 ? "Near limit" : utilization >= 0.65 ? "Elevated" : "Within limit");
    setTone(byId("risk-state-pill"), riskTone);
    renderMetricList(byId("risk-metrics"), [
      ["Open modeled risk", formatMoney(account.open_risk, currency)],
      ["Risk ceiling", formatMoney(account.open_risk_limit, currency)],
      ["Buying power", formatMoney(account.buying_power, currency)],
      ["Hard daily loss", formatMoney(account.hard_daily_loss_limit, currency)],
    ]);
  }

  renderSetupBoard();
  renderCompactServices();
  renderQualificationPreview();
  renderAlertPreview();
}

function renderKpis(container, values) {
  clear(container);
  for (const item of values) {
    const card = element("article", { className: "kpi-card" });
    card.dataset.tone = item.tone || "neutral";
    const top = element("div", { className: "kpi-topline" });
    top.append(element("span", { text: item.label }), element("span", { className: "kpi-icon", text: item.icon || "•", attrs: { "aria-hidden": "true" } }));
    const value = element("strong", { className: `kpi-value ${item.valueClass || ""}`.trim(), text: item.value });
    const footer = element("div", { className: "kpi-footer" });
    footer.append(element("span", { text: item.footer || "" }), element("strong", { text: item.footerValue || "" }));
    card.append(top, value, footer);
    container.append(card);
  }
}

function renderMetricList(container, values) {
  clear(container);
  for (const [label, value, className = ""] of values) {
    const row = element("div");
    const term = element("dt", { text: label });
    const detail = element("dd", { className, text: value });
    row.append(term, detail);
    container.append(row);
  }
}

function renderEquityFooter(curve, currency) {
  const footer = byId("equity-chart-footer");
  clear(footer);
  const values = curve.map((point) => point.equity).filter(Number.isFinite);
  const items = [
    ["Low", values.length ? formatMoney(Math.min(...values), currency) : "—"],
    ["High", values.length ? formatMoney(Math.max(...values), currency) : "—"],
    ["Last", values.length ? formatMoney(values.at(-1), currency) : "—"],
  ];
  for (const [label, value] of items) {
    const item = element("span");
    item.append(`${label} `, element("strong", { text: value }));
    footer.append(item);
  }
}

function renderSetupBoard() {
  const container = byId("setup-board");
  clear(container);
  const signals = state.snapshot.signals.slice(0, 4);
  if (!signals.length) {
    container.append(emptyInline("No setup detail published in this snapshot."));
    return;
  }
  for (const signal of signals) {
    const row = element("div", { className: "setup-row" });
    const rank = element("span", { className: "rank-badge", text: signal.rank ? `#${signal.rank}` : "—" });
    const ticker = element("div", { className: "ticker-block" });
    ticker.append(element("strong", { text: signal.ticker }), element("span", { text: humanize(signal.status) }));
    const source = element("div", { className: "setup-data" });
    source.append(element("span", { text: "Catalyst source" }), element("strong", { text: signal.catalyst_source }));
    const execution = element("div", { className: "setup-data" });
    execution.append(element("span", { text: "Execution" }), element("strong", { text: humanize(signal.execution_status) }));
    const score = element("div", { className: "score-block" });
    score.append(element("span", { className: "score-ring", text: Math.round(signal.conviction_score) }));
    row.append(rank, ticker, source, execution, score);
    container.append(row);
  }
}

function renderCompactServices() {
  const container = byId("service-compact-list");
  clear(container);
  const services = state.snapshot.services.slice(0, 6);
  if (!services.length) {
    container.append(emptyInline("No service health supplied."));
    return;
  }
  for (const service of services) {
    const row = element("div", { className: "service-compact-row" });
    row.append(
      healthDot(service.status),
      element("strong", { text: service.name }),
      element("span", { text: service.latency_ms === null ? humanize(service.status) : `${service.latency_ms.toFixed(0)} ms` }),
    );
    container.append(row);
  }
}

function renderQualificationPreview() {
  const { qualification } = state.snapshot;
  const progress = qualificationProgress(qualification.items);
  setText("qualification-score", `${Math.round(progress * 100)}%`);
  byId("qualification-progress").style.width = `${progress * 100}%`;
  setText(
    "qualification-summary-text",
    qualification.status === "passed"
      ? "All published qualification requirements are complete."
      : `${qualification.blockers.length} blocker${qualification.blockers.length === 1 ? "" : "s"} remain before operational paper designation.`,
  );
  const container = byId("qualification-preview");
  clear(container);
  for (const item of qualification.items.slice(0, 3)) {
    const card = element("div", { className: "milestone-card" });
    card.append(
      element("span", { text: item.label }),
      element("strong", { text: `${formatNumber(item.current)} / ${formatNumber(item.target)}` }),
      element("small", { className: statusTone(item.status) === "positive" ? "positive" : "", text: humanize(item.status) }),
    );
    container.append(card);
  }
}

function renderAlertPreview() {
  const alerts = state.snapshot.alerts.slice(0, 3);
  const container = byId("alert-preview");
  clear(container);
  setText("alert-count-pill", `${state.snapshot.alerts.length} open`);
  setTone(byId("alert-count-pill"), alerts.some((item) => item.severity === "critical") ? "danger" : alerts.length ? "warning" : "positive");
  if (!alerts.length) {
    container.append(emptyInline("No operating alerts in this snapshot."));
    return;
  }
  for (const alert of alerts) {
    const card = element("div", { className: "alert-card" });
    const content = element("div");
    content.append(element("strong", { text: alert.title }), element("p", { text: alert.message }));
    card.append(healthDot(alert.severity), content, element("time", { text: formatDateTime(alert.timestamp, { includeDate: false }) }));
    container.append(card);
  }
}

function renderTrading() {
  const { account, positions, orders, signals } = state.snapshot;
  const approved = signals.filter((item) => item.status === "approved").length;
  const qualified = signals.filter((item) => item.status === "qualified").length;
  const excluded = signals.filter((item) => item.status === "excluded").length;
  const averageScore = signals.length
    ? signals.reduce((sum, item) => sum + item.conviction_score, 0) / signals.length
    : null;
  renderKpis(byId("trading-kpis"), [
    { label: "Approved", value: approved, footer: "Top-three cap", footerValue: "Max 3", icon: "✓", tone: "positive" },
    { label: "Qualified", value: qualified, footer: "Below cutoff", footerValue: "Tracked", icon: "＋", tone: "warning" },
    { label: "Excluded", value: excluded, footer: "Failed hard gate", footerValue: "No trade", icon: "×", tone: excluded ? "warning" : "positive" },
    { label: "Average score", value: averageScore === null ? "—" : averageScore.toFixed(1), footer: "Published setups", footerValue: signals.length, icon: "◎", tone: "blue" },
    { label: "Reserved risk", value: formatMoney(account.open_risk, account.currency), footer: "Risk limit", footerValue: formatMoney(account.open_risk_limit, account.currency), icon: "◇", tone: "warning" },
  ]);
  renderSignalTable();

  const positionPnl = positions.reduce((sum, item) => sum + (item.unrealized_pnl || 0), 0);
  renderKpis(byId("position-kpis"), [
    { label: "Open positions", value: positions.length, footer: "Managed only", footerValue: state.snapshot.safety.all_positions_flat ? "Flat" : "Open", icon: "↗", tone: positions.length ? "warning" : "positive" },
    { label: "Market value", value: formatMoney(positions.reduce((sum, item) => sum + (item.market_value || 0), 0), account.currency), footer: "Gross exposure", footerValue: formatMoney(account.gross_exposure, account.currency), icon: "$", tone: "blue" },
    { label: "Unrealized P&L", value: formatSignedMoney(positionPnl, account.currency), footer: "Broker snapshot", footerValue: formatDateTime(state.snapshot.generated_at, { includeDate: false }), icon: "⌁", tone: toneForNumber(positionPnl), valueClass: toneForNumber(positionPnl) },
    { label: "Protected", value: positions.filter((item) => item.protective_status === "protected").length, footer: "Bracket legs", footerValue: `${positions.length} expected`, icon: "◇", tone: positions.every((item) => item.protective_status === "protected") ? "positive" : "danger" },
    { label: "Buying power", value: formatMoney(account.buying_power, account.currency), footer: "Paper account", footerValue: "No margin", icon: "◫", tone: "blue" },
  ]);
  renderPositions();

  const filledOrders = orders.filter((item) => item.status === "filled").length;
  renderKpis(byId("order-kpis"), [
    { label: "Total orders", value: orders.length, footer: "Snapshot scope", footerValue: "Daybreak-owned", icon: "≡", tone: "blue" },
    { label: "Filled", value: filledOrders, footer: "Fill rate", footerValue: orders.length ? formatPercent(filledOrders / orders.length) : "—", icon: "✓", tone: "positive" },
    { label: "Working", value: orders.filter((item) => ["accepted", "new", "partially_filled"].includes(item.status)).length, footer: "Broker active", footerValue: "Reconciled", icon: "↻", tone: "warning" },
    { label: "Canceled", value: orders.filter((item) => item.status === "canceled").length, footer: "Contained", footerValue: "Expected", icon: "×", tone: "neutral" },
    { label: "Unresolved", value: state.snapshot.session.unresolved_reconciliations, footer: "Required", footerValue: "0", icon: "!", tone: state.snapshot.session.unresolved_reconciliations ? "danger" : "positive" },
  ]);
  renderOrders();
}

function renderSignalTable() {
  const body = byId("signal-table-body");
  clear(body);
  const query = byId("signal-search").value.trim().toLowerCase();
  const status = byId("signal-status-filter").value;
  const filtered = state.snapshot.signals.filter((signal) => {
    const matchesStatus = status === "all" || signal.status === status;
    const haystack = `${signal.ticker} ${signal.catalyst_source} ${signal.catalyst} ${signal.thesis}`.toLowerCase();
    return matchesStatus && (!query || haystack.includes(query));
  });

  setText("signal-table-count", `${filtered.length} setup${filtered.length === 1 ? "" : "s"}`);
  byId("signal-empty").hidden = filtered.length > 0;
  for (const signal of filtered) {
    const row = element("tr");
    const tickerCell = element("td");
    const ticker = element("div", { className: "table-ticker" });
    ticker.append(
      element("span", { className: "rank-badge", text: signal.rank ? `#${signal.rank}` : "—" }),
      (() => {
        const copy = element("span");
        copy.append(element("strong", { text: signal.ticker }), element("small", { text: signal.catalyst_source }));
        return copy;
      })(),
    );
    tickerCell.append(ticker);
    const actionCell = element("td");
    const action = element("button", { className: "row-action", text: "→", attrs: { type: "button", "aria-label": `View ${signal.ticker} setup details` } });
    action.addEventListener("click", () => openSignalDialog(signal));
    actionCell.append(action);
    row.append(
      tickerCell,
      cellWithPill(humanize(signal.status), statusTone(signal.status)),
      cellWithPill(humanize(signal.execution_status), statusTone(signal.execution_status)),
      element("td", { className: "table-score", text: Math.round(signal.conviction_score) }),
      element("td", { text: signal.technical_grade }),
      element("td", { text: formatPrice(signal.entry_price, state.snapshot.account.currency) }),
      element("td", { text: formatPrice(signal.stop_price, state.snapshot.account.currency) }),
      element("td", { text: formatPrice(signal.target_price, state.snapshot.account.currency) }),
      element("td", { text: formatPrice(signal.target_price_2, state.snapshot.account.currency) }),
      element("td", { text: formatMoney(signal.modeled_risk, state.snapshot.account.currency) }),
      actionCell,
    );
    body.append(row);
  }
}

function renderPositions() {
  const container = byId("position-grid");
  clear(container);
  const flatPill = byId("positions-flat-pill");
  setText("positions-flat-pill", state.snapshot.safety.all_positions_flat ? "All positions flat" : `${state.snapshot.positions.length} open`);
  setTone(flatPill, state.snapshot.safety.all_positions_flat ? "positive" : "warning");
  if (!state.snapshot.positions.length) {
    container.append(emptyInline("No managed positions in this snapshot."));
    return;
  }
  for (const position of state.snapshot.positions) {
    const card = element("article", { className: "position-card" });
    const header = element("div", { className: "position-card-header" });
    const ticker = element("div");
    ticker.append(element("strong", { text: position.ticker }), element("span", { text: `${humanize(position.side)} · ${formatNumber(position.quantity)} shares` }));
    const pnl = element("span", { className: `position-pnl ${toneForNumber(position.unrealized_pnl)}`, text: formatSignedMoney(position.unrealized_pnl, state.snapshot.account.currency) });
    header.append(ticker, pnl);

    const prices = element("div", { className: "position-price-row" });
    for (const [label, value] of [
      ["Average entry", position.average_entry_price],
      ["Last price", position.last_price],
      ["Market value", position.market_value],
    ]) {
      const item = element("div");
      item.append(element("span", { text: label }), element("strong", { text: label === "Market value" ? formatMoney(value, state.snapshot.account.currency) : formatPrice(value, state.snapshot.account.currency) }));
      prices.append(item);
    }

    const range = element("div", { className: "position-range" });
    const marker = element("span");
    const totalRange = (position.target_price ?? 0) - (position.stop_price ?? 0);
    const markerPosition = totalRange > 0 ? clamp(((position.last_price ?? 0) - position.stop_price) / totalRange) * 100 : 50;
    marker.style.left = `${markerPosition}%`;
    range.append(marker);
    const labels = element("div", { className: "position-range-labels" });
    labels.append(element("span", { text: `Stop ${formatPrice(position.stop_price)}` }), element("span", { text: `Target ${formatPrice(position.target_price)}` }));
    const protection = element("div", { className: "position-price-row" });
    const protectionItem = element("div");
    protectionItem.append(element("span", { text: "Protection" }), element("strong", { className: statusTone(position.protective_status) === "positive" ? "positive" : "warning", text: humanize(position.protective_status) }));
    protection.append(protectionItem);
    card.append(header, prices, range, labels, protection);
    container.append(card);
  }
}

function renderOrders() {
  const body = byId("order-table-body");
  clear(body);
  setText("order-table-count", `${state.snapshot.orders.length} order${state.snapshot.orders.length === 1 ? "" : "s"}`);
  byId("order-empty").hidden = state.snapshot.orders.length > 0;
  for (const order of state.snapshot.orders) {
    const row = element("tr");
    row.append(
      element("td", { text: formatDateTime(order.submitted_at, { includeDate: false, seconds: true }) }),
      element("td", { text: order.ticker }),
      element("td", { text: humanize(order.side) }),
      element("td", { text: `${humanize(order.type)} · ${humanize(order.order_class)}` }),
      element("td", { text: `${formatNumber(order.filled_quantity)} / ${formatNumber(order.quantity)}` }),
      element("td", { text: formatPrice(order.price, state.snapshot.account.currency) }),
      cellWithPill(humanize(order.status), statusTone(order.status)),
      element("td", { text: truncateHash(order.client_order_id, 8), attrs: { title: order.client_order_id } }),
    );
    body.append(row);
  }
}

function renderPerformance() {
  const { performance, account } = state.snapshot;
  const summary = performance.summary;
  renderKpis(byId("performance-kpis"), [
    { label: "Net paper P&L", value: formatSignedMoney(summary.net_pnl, account.currency), footer: "Gross", footerValue: formatSignedMoney(summary.gross_pnl, account.currency), icon: "$", tone: toneForNumber(summary.net_pnl), valueClass: toneForNumber(summary.net_pnl) },
    { label: "Win rate", value: formatPercent(summary.win_rate), footer: "Trades", footerValue: formatNumber(summary.trade_count), icon: "%", tone: (summary.win_rate ?? 0) >= 0.5 ? "positive" : "warning" },
    { label: "Profit factor", value: summary.profit_factor === null ? "—" : summary.profit_factor.toFixed(2), footer: "Expectancy", footerValue: formatSignedMoney(summary.expectancy, account.currency), icon: "×", tone: (summary.profit_factor ?? 0) >= 1 ? "positive" : "warning" },
    { label: "Average R", value: summary.average_r_multiple === null ? "—" : `${summary.average_r_multiple > 0 ? "+" : ""}${summary.average_r_multiple.toFixed(2)}R`, footer: "Max drawdown", footerValue: formatMoney(summary.maximum_drawdown, account.currency), icon: "R", tone: toneForNumber(summary.average_r_multiple), valueClass: toneForNumber(summary.average_r_multiple) },
  ]);
  renderPerformanceChart();
  renderOutcomeDonut();
  renderDailyPnl();
  renderAttribution();
  renderTrades();
}

function renderPerformanceChart() {
  const curve = state.snapshot.performance.equity_curve;
  renderLineChart(byId("performance-chart"), curve, {
    valueKey: "equity",
    secondaryKey: "drawdown",
    labelKey: "timestamp",
    formatter: (value) => formatMoney(value, state.snapshot.account.currency, { compact: true }),
    secondaryFormatter: (value) => formatMoney(value, state.snapshot.account.currency),
    title: "Paper equity and drawdown",
  });
}

function renderOutcomeDonut() {
  const summary = state.snapshot.performance.summary;
  const counts = outcomeCounts(summary, state.snapshot.performance.trades);
  const total = Math.max(1, counts.total);
  const winsEnd = (counts.wins / total) * 360;
  const lossesEnd = winsEnd + (counts.losses / total) * 360;
  const donut = byId("outcome-donut");
  donut.style.setProperty("--wins", `${winsEnd}deg`);
  donut.style.setProperty("--losses", `${lossesEnd}deg`);
  setText("donut-win-rate", formatPercent(summary.win_rate));
  const legend = byId("outcome-legend");
  clear(legend);
  for (const [label, value, color] of [
    ["Wins", counts.wins, "var(--primary)"],
    ["Losses", counts.losses, "var(--danger)"],
    ["Breakeven", counts.breakeven, "var(--muted)"],
  ]) {
    const row = element("div");
    const dot = element("i");
    dot.style.background = color;
    row.append(dot, element("dt", { text: label }), element("dd", { text: value }));
    legend.append(row);
  }
  renderMetricList(byId("performance-metric-list"), [
    ["Session count", formatNumber(summary.session_count)],
    ["Target 1 hit rate", `${formatPercent(summary.target_1_hit_rate)} (${formatNumber(summary.wins_target_1)})`],
    ["Target 2 hit rate", `${formatPercent(summary.target_2_hit_rate)} (${formatNumber(summary.wins_target_2)})`],
    ["Fees", formatMoney(summary.fees, state.snapshot.account.currency)],
    ["Average slippage", summary.average_entry_slippage_bps === null ? "—" : `${summary.average_entry_slippage_bps.toFixed(1)} bps`],
  ]);
}

function renderDailyPnl() {
  renderBarChart(byId("daily-pnl-chart"), state.snapshot.performance.daily, {
    valueKey: "net_pnl",
    labelKey: "date",
    formatter: (value) => formatMoney(value, state.snapshot.account.currency, { compact: true }),
    title: "Daily paper profit and loss",
  });
}

function renderAttribution() {
  const container = byId("attribution-list");
  clear(container);
  const values = state.snapshot.performance.attributions.slice(0, 7);
  if (!values.length) {
    container.append(emptyInline("No attribution buckets published."));
    return;
  }
  const maxAbsolute = Math.max(1, ...values.map((item) => Math.abs(item.net_pnl || 0)));
  for (const item of values) {
    const row = element("div", { className: "attribution-row" });
    const label = element("div", { className: "attribution-label" });
    label.append(element("strong", { text: humanize(item.key) }), element("span", { text: `${humanize(item.dimension)} · ${item.trade_count} trades` }));
    const bar = element("div", { className: "attribution-bar" });
    const fill = element("span");
    fill.style.width = `${(Math.abs(item.net_pnl || 0) / maxAbsolute) * 100}%`;
    if ((item.net_pnl || 0) < 0) fill.classList.add("negative-bar");
    bar.append(fill);
    const value = element("span", { className: `attribution-value ${toneForNumber(item.net_pnl)}`, text: `${item.average_r_multiple > 0 ? "+" : ""}${item.average_r_multiple.toFixed(2)}R` });
    row.append(label, bar, value);
    container.append(row);
  }
}

function renderTrades() {
  const body = byId("trade-table-body");
  clear(body);
  const trades = state.snapshot.performance.trades;
  setText("trade-table-count", `${trades.length} trade${trades.length === 1 ? "" : "s"}`);
  for (const trade of trades) {
    const row = element("tr");
    row.append(
      element("td", { text: trade.date || "—" }),
      element("td", { text: trade.ticker }),
      element("td", { text: trade.rank ? `#${trade.rank}` : "—" }),
      element("td", { text: formatPrice(trade.entry_price, state.snapshot.account.currency) }),
      element("td", { text: formatPrice(trade.exit_price, state.snapshot.account.currency) }),
      element("td", { className: toneForNumber(trade.net_pnl), text: formatSignedMoney(trade.net_pnl, state.snapshot.account.currency) }),
      element("td", { className: toneForNumber(trade.r_multiple), text: trade.r_multiple === null ? "—" : `${trade.r_multiple > 0 ? "+" : ""}${trade.r_multiple.toFixed(2)}R` }),
      cellWithPill(humanize(trade.exit_reason), trade.exit_reason === "target" ? "positive" : trade.exit_reason === "stop" ? "danger" : "neutral"),
    );
    body.append(row);
  }
}

function renderSystem() {
  const { release, safety, services, qualification, session, system } = state.snapshot;
  const healthyServices = services.filter((item) => ["healthy", "verified"].includes(item.status)).length;
  const qualificationScore = qualificationProgress(qualification.items);
  const summary = byId("system-summary");
  clear(summary);
  for (const item of [
    { label: "Runtime state", value: safety.kill_switch_active ? "Stopped" : humanize(system.phase), detail: safety.kill_switch_active ? "Kill switch requires reset" : `${healthyServices}/${services.length} services healthy`, icon: safety.kill_switch_active ? "!" : "◎", tone: safety.kill_switch_active ? "danger" : "positive" },
    { label: "Qualification", value: humanize(qualification.status), detail: `${Math.round(qualificationScore * 100)}% of published targets`, icon: "◫", tone: qualification.status === "passed" ? "positive" : "warning" },
    { label: "Release evidence", value: `v${release.release_version}`, detail: humanize(release.status), icon: "◇", tone: release.paper_release_candidate ? "positive" : "warning" },
  ]) {
    const card = element("article", { className: "summary-card" });
    const icon = element("span", { className: `summary-icon ${item.tone === "danger" ? "negative" : item.tone === "warning" ? "warning" : "positive"}`, text: item.icon, attrs: { "aria-hidden": "true" } });
    const copy = element("div");
    copy.append(element("span", { text: item.label }), element("strong", { text: item.value }), element("small", { text: item.detail }));
    card.append(icon, copy);
    summary.append(card);
  }

  renderServices();
  renderControls();
  renderQualificationDetail();
  renderEvidence();
  renderAlertTimeline();
  setText("system-alert-count", `${state.snapshot.alerts.length} event${state.snapshot.alerts.length === 1 ? "" : "s"}`);
  setText("service-health-pill", `${healthyServices} / ${services.length} healthy`);
  setTone(byId("service-health-pill"), healthyServices === services.length ? "positive" : services.some((item) => ["critical", "offline"].includes(item.status)) ? "danger" : "warning");
  void session;
}

function renderServices() {
  const container = byId("service-grid");
  clear(container);
  if (!state.snapshot.services.length) {
    container.append(emptyInline("No runtime service data was published."));
    return;
  }
  for (const service of state.snapshot.services) {
    const card = element("article", { className: "service-card" });
    const header = element("div", { className: "service-card-header" });
    const name = element("span", { className: "table-ticker" });
    name.append(healthDot(service.status), element("strong", { text: service.name }));
    header.append(name, element("span", { className: `pill pill-${statusTone(service.status)}`, text: humanize(service.status) }));
    const footer = element("footer");
    footer.append(
      element("span", { text: service.latency_ms === null ? "Latency —" : `${service.latency_ms.toFixed(0)} ms` }),
      element("span", { text: formatDateTime(service.updated_at, { includeDate: false, seconds: true }) }),
    );
    card.append(header, element("p", { text: service.detail }), footer);
    container.append(card);
  }
}

function renderControls() {
  const safety = state.snapshot.safety;
  const controls = [
    ["Paper-only enforcement", "Live endpoint and capital disabled", safety.paper_only && !safety.live_capital_eligible],
    ["Kill switch", "Persistent stop state", !safety.kill_switch_active],
    ["Leadership fence", "Single authorized orchestrator", safety.leadership_valid],
    ["Account reconciliation", "Broker and internal state match", safety.account_reconciled],
    ["Protective orders", "Both bracket legs verified", safety.protective_orders_verified || safety.all_positions_flat],
    ["End-of-day flat", "No overnight exposure allowed", safety.all_positions_flat],
  ];
  const container = byId("control-list");
  clear(container);
  for (const [label, detail, passed] of controls) {
    const row = element("div", { className: "control-row" });
    const copy = element("div");
    copy.append(element("strong", { text: label }), element("small", { text: detail }));
    const status = element("span", { className: `control-state ${passed ? "positive" : "warning"}` });
    status.append(healthDot(passed ? "healthy" : "warning"), document.createTextNode(passed ? "Verified" : "Check"));
    row.append(copy, status);
    container.append(row);
  }
}

function renderQualificationDetail() {
  const { qualification } = state.snapshot;
  const score = qualificationProgress(qualification.items);
  setText("qualification-detail-score", `${Math.round(score * 100)}%`);
  const container = byId("qualification-list");
  clear(container);
  for (const item of qualification.items) {
    const row = element("div", { className: "qualification-row" });
    const label = element("div", { className: "qualification-label" });
    label.append(element("strong", { text: item.label }), element("span", { text: item.detail || humanize(item.status) }));
    const progress = element("div", { className: "progress-track" });
    const fill = element("span");
    fill.style.width = `${clamp(item.target ? item.current / item.target : 0) * 100}%`;
    progress.append(fill);
    row.append(label, progress, element("span", { className: "qualification-value", text: `${formatNumber(item.current)} / ${formatNumber(item.target)}` }));
    container.append(row);
  }
  const blockerBox = byId("blocker-box");
  const blockerList = byId("blocker-list");
  clear(blockerList);
  blockerBox.hidden = qualification.blockers.length === 0;
  for (const blocker of qualification.blockers) blockerList.append(element("li", { text: humanize(blocker) }));
}

function renderEvidence() {
  const release = state.snapshot.release;
  setText("release-status-pill", humanize(release.status));
  setTone(byId("release-status-pill"), release.paper_release_candidate ? "positive" : statusTone(release.status));
  const values = [
    ["Release", `v${release.release_version}`],
    ["Specification", `v${release.specification_version}`],
    ["Tests", release.tests_passed === null ? "—" : `${release.tests_passed}/${release.tests_collected ?? release.tests_passed}`],
    ["Branch coverage", release.branch_coverage_pct === null ? "—" : `${release.branch_coverage_pct.toFixed(2)}%`],
    ["Ruff / mypy", release.ruff_errors === null || release.mypy_errors === null ? "—" : `${release.ruff_errors} / ${release.mypy_errors}`],
    ["Security findings", release.security_findings ?? "—"],
    ["Dependency CVEs", release.dependency_vulnerabilities ?? "—"],
    ["Schemas / invariants", release.schema_count === null ? "—" : `${release.schema_count} / ${release.invariant_count ?? "—"}`],
  ];
  const grid = byId("evidence-grid");
  clear(grid);
  for (const [label, value] of values) {
    const item = element("div");
    item.append(element("dt", { text: label }), element("dd", { text: value }));
    grid.append(item);
  }
  setText("release-report-hash", truncateHash(release.report_hash, 16));
  byId("release-report-hash").title = release.report_hash || "Unavailable";
}

function renderAlertTimeline() {
  const container = byId("alert-timeline");
  clear(container);
  if (!state.snapshot.alerts.length) {
    container.append(emptyInline("No alerts or operating events were published."));
    return;
  }
  for (const alert of state.snapshot.alerts) {
    const item = element("div", { className: "timeline-item" });
    const copy = element("div");
    copy.append(element("strong", { text: alert.title }), element("p", { text: `${alert.message} · ${alert.source}` }));
    item.append(healthDot(alert.severity), copy, element("time", { text: formatDateTime(alert.timestamp, { seconds: true }) }));
    container.append(item);
  }
}

function renderLineChart(container, rawPoints, options) {
  clear(container);
  const points = rawPoints.filter((point) => Number.isFinite(point[options.valueKey]));
  if (points.length < 2) {
    container.append(emptyInline("At least two observations are required for this chart."));
    return;
  }
  const width = 820;
  const height = options.secondaryKey ? 305 : 280;
  const margins = { top: 18, right: 18, bottom: 28, left: 64 };
  const plotWidth = width - margins.left - margins.right;
  const primaryHeight = options.secondaryKey ? 205 : height - margins.top - margins.bottom;
  const values = points.map((point) => point[options.valueKey]);
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  const padding = Math.max((maximum - minimum) * 0.15, Math.abs(maximum || 1) * 0.005);
  minimum -= padding;
  maximum += padding;
  const range = maximum - minimum || 1;
  const x = (index) => margins.left + (index / (points.length - 1)) * plotWidth;
  const y = (value) => margins.top + (1 - (value - minimum) / range) * primaryHeight;
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", role: "img", "aria-label": options.title });
  const svgTitle = svgElement("title");
  svgTitle.textContent = options.title;
  svg.append(svgTitle);
  const defs = svgElement("defs");
  const gradientId = `area-gradient-${container.id || "chart"}`;
  const gradient = svgElement("linearGradient", { id: gradientId, x1: "0", y1: "0", x2: "0", y2: "1" });
  gradient.append(svgElement("stop", { offset: "0%", "stop-color": "var(--primary)", "stop-opacity": "0.24" }), svgElement("stop", { offset: "100%", "stop-color": "var(--primary)", "stop-opacity": "0" }));
  defs.append(gradient);
  svg.append(defs);

  for (let index = 0; index <= 4; index += 1) {
    const value = maximum - (range * index) / 4;
    const yValue = margins.top + (primaryHeight * index) / 4;
    svg.append(svgElement("line", { class: "chart-grid-line", x1: margins.left, y1: yValue, x2: width - margins.right, y2: yValue }));
    const label = svgElement("text", { class: "chart-axis-label", x: margins.left - 9, y: yValue + 3, "text-anchor": "end" });
    label.textContent = options.formatter(value);
    svg.append(label);
  }

  const coordinates = points.map((point, index) => [x(index), y(point[options.valueKey])]);
  const linePath = coordinates.map(([xValue, yValue], index) => `${index ? "L" : "M"}${xValue.toFixed(2)},${yValue.toFixed(2)}`).join(" ");
  const areaPath = `${linePath} L${coordinates.at(-1)[0]},${margins.top + primaryHeight} L${coordinates[0][0]},${margins.top + primaryHeight} Z`;
  svg.append(
    svgElement("path", { class: "chart-area", d: areaPath, fill: `url(#${gradientId})` }),
    svgElement("path", { class: "chart-line", d: linePath }),
  );

  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  for (const index of labelIndexes) {
    const label = svgElement("text", { class: "chart-axis-label", x: x(index), y: height - 7, "text-anchor": index === 0 ? "start" : index === points.length - 1 ? "end" : "middle" });
    const date = points[index][options.labelKey];
    label.textContent = date && !Number.isNaN(Date.parse(date))
      ? new Date(date).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
      : date || "—";
    svg.append(label);
  }

  for (const [index, [xValue, yValue]] of coordinates.entries()) {
    const point = svgElement("circle", { class: "chart-point", cx: xValue, cy: yValue, r: index === coordinates.length - 1 ? 4 : 2.2, tabindex: "0" });
    const title = svgElement("title");
    title.textContent = `${points[index][options.labelKey] || `Observation ${index + 1}`}: ${options.formatter(points[index][options.valueKey])}`;
    point.append(title);
    svg.append(point);
  }

  if (options.secondaryKey) {
    const secondary = points.map((point) => Math.max(0, Number(point[options.secondaryKey]) || 0));
    const secondaryMax = Math.max(1, ...secondary);
    const bandTop = 244;
    const bandHeight = 38;
    const secondaryPath = secondary
      .map((value, index) => {
        const yValue = bandTop + (value / secondaryMax) * bandHeight;
        return `${index ? "L" : "M"}${x(index).toFixed(2)},${yValue.toFixed(2)}`;
      })
      .join(" ");
    svg.append(svgElement("line", { class: "chart-grid-line", x1: margins.left, y1: bandTop, x2: width - margins.right, y2: bandTop }));
    svg.append(svgElement("path", { class: "chart-line chart-line-secondary", d: secondaryPath }));
    const label = svgElement("text", { class: "chart-axis-label", x: margins.left - 9, y: bandTop + 4, "text-anchor": "end" });
    label.textContent = "DD";
    svg.append(label);
  }
  container.append(svg);
}

function renderBarChart(container, rawPoints, options) {
  clear(container);
  const points = rawPoints.filter((point) => Number.isFinite(point[options.valueKey]));
  if (!points.length) {
    container.append(emptyInline("No daily observations were published."));
    return;
  }
  const width = 740;
  const height = 240;
  const margins = { top: 18, right: 12, bottom: 30, left: 58 };
  const plotWidth = width - margins.left - margins.right;
  const plotHeight = height - margins.top - margins.bottom;
  const values = points.map((point) => point[options.valueKey]);
  const maxAbsolute = Math.max(1, ...values.map(Math.abs));
  const zeroY = margins.top + plotHeight / 2;
  const slot = plotWidth / points.length;
  const barWidth = Math.max(4, Math.min(28, slot * 0.62));
  const svg = svgElement("svg", { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", role: "img", "aria-label": options.title });
  const title = svgElement("title");
  title.textContent = options.title;
  svg.append(title, svgElement("line", { class: "chart-zero-line", x1: margins.left, y1: zeroY, x2: width - margins.right, y2: zeroY }));
  for (const [index, point] of points.entries()) {
    const value = point[options.valueKey];
    const heightValue = (Math.abs(value) / maxAbsolute) * (plotHeight / 2 - 6);
    const xValue = margins.left + slot * index + (slot - barWidth) / 2;
    const yValue = value >= 0 ? zeroY - heightValue : zeroY;
    const bar = svgElement("rect", { class: value >= 0 ? "chart-bar-positive" : "chart-bar-negative", x: xValue, y: yValue, width: barWidth, height: Math.max(1, heightValue), rx: 3, tabindex: "0" });
    const tooltip = svgElement("title");
    tooltip.textContent = `${point[options.labelKey]}: ${options.formatter(value)}`;
    bar.append(tooltip);
    svg.append(bar);
    if (index === 0 || index === points.length - 1 || (points.length <= 8 && index % 2 === 0)) {
      const label = svgElement("text", { class: "chart-axis-label", x: xValue + barWidth / 2, y: height - 8, "text-anchor": "middle" });
      label.textContent = point[options.labelKey] && !Number.isNaN(Date.parse(point[options.labelKey]))
        ? new Date(point[options.labelKey]).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
        : point[options.labelKey];
      svg.append(label);
    }
  }
  for (const [value, yValue] of [[maxAbsolute, margins.top + 4], [0, zeroY + 4], [-maxAbsolute, margins.top + plotHeight]]) {
    const label = svgElement("text", { class: "chart-axis-label", x: margins.left - 9, y: yValue, "text-anchor": "end" });
    label.textContent = options.formatter(value);
    svg.append(label);
  }
  container.append(svg);
}

function openSignalDialog(signal) {
  const content = byId("dialog-content");
  clear(content);
  const body = element("div", { className: "dialog-body" });
  const titleRow = element("div", { className: "dialog-title-row" });
  titleRow.append(element("span", { className: "rank-badge", text: signal.rank ? `#${signal.rank}` : "—" }), element("h2", { id: "dialog-title", text: signal.ticker }), element("span", { className: `pill pill-${statusTone(signal.status)}`, text: humanize(signal.status) }));
  body.append(titleRow);

  const scoreSection = element("section", { className: "dialog-section" });
  scoreSection.append(element("h3", { text: "Decision summary" }), element("p", { text: `${signal.conviction_score.toFixed(0)} conviction · ${signal.technical_grade} technical grade · ${humanize(signal.execution_status)}` }));
  body.append(scoreSection);

  const catalystSection = element("section", { className: "dialog-section" });
  catalystSection.append(element("h3", { text: `${signal.catalyst_source} catalyst` }), element("p", { text: signal.catalyst }));
  body.append(catalystSection);

  const thesisSection = element("section", { className: "dialog-section" });
  thesisSection.append(element("h3", { text: "Master thesis" }), element("p", { text: signal.thesis }));
  body.append(thesisSection);

  const planSection = element("section", { className: "dialog-section" });
  planSection.append(element("h3", { text: "Deterministic trade plan" }));
  const plan = element("div", { className: "trade-plan-grid" });
  const targetHitLabel = { target_1: "Hit target 1", target_2: "Hit target 2" }[signal.target_hit] || "—";
  for (const [label, value] of [
    ["Entry", formatPrice(signal.entry_price, state.snapshot.account.currency)],
    ["Stop", formatPrice(signal.stop_price, state.snapshot.account.currency)],
    ["Target 1", formatPrice(signal.target_price, state.snapshot.account.currency)],
    ["Target 2", formatPrice(signal.target_price_2, state.snapshot.account.currency)],
    ["Quantity", formatNumber(signal.quantity)],
    ["Target reached", targetHitLabel],
  ]) {
    const item = element("div");
    item.append(element("span", { text: label }), element("strong", { text: value }));
    plan.append(item);
  }
  planSection.append(plan);
  body.append(planSection);

  const flagsSection = element("section", { className: "dialog-section" });
  flagsSection.append(element("h3", { text: "Risk flags" }));
  const tags = element("div", { className: "tag-list" });
  const flags = signal.risk_flags.length ? signal.risk_flags : ["No published risk flags"];
  for (const flag of flags) tags.append(element("span", { className: "tag", text: humanize(flag) }));
  flagsSection.append(tags);
  body.append(flagsSection);
  content.append(body);
  byId("signal-dialog").showModal();
}

function cellWithPill(text, tone) {
  const cell = element("td");
  cell.append(element("span", { className: `pill pill-${tone}`, text }));
  return cell;
}

function healthDot(status) {
  return element("span", { className: "health-dot", attrs: { "data-status": status, "aria-hidden": "true" } });
}

function emptyInline(message) {
  const node = element("div", { className: "empty-state" });
  node.append(element("span", { text: "—", attrs: { "aria-hidden": "true" } }), element("p", { text: message }));
  return node;
}

function switchView(view, updateHash = true) {
  if (!VIEW_META[view]) return;
  state.currentView = view;
  for (const button of all("[data-view]")) {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const panel of all("[data-view-panel]")) {
    const active = panel.dataset.viewPanel === view;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  }
  setText("page-eyebrow", VIEW_META[view][0]);
  setText("page-title", VIEW_META[view][1]);
  if (updateHash) history.replaceState(null, "", `#${view}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function switchTradingTab(tab) {
  state.currentTradingTab = tab;
  for (const button of all("[data-trading-tab]")) button.classList.toggle("is-active", button.dataset.tradingTab === tab);
  for (const panel of all("[data-trading-panel]")) {
    const active = panel.dataset.tradingPanel === tab;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  }
  byId("signal-filters").hidden = tab !== "signals";
}

function applyTheme(theme) {
  const resolved = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = resolved;
  document.querySelector('meta[name="theme-color"]').content = resolved === "dark" ? "#07111f" : "#f3f6fa";
  try {
    localStorage.setItem("daybreak-theme", resolved);
  } catch {
    // Theme persistence is optional.
  }
}

function bindEvents() {
  for (const button of all("[data-view]")) button.addEventListener("click", () => switchView(button.dataset.view));
  for (const button of all("[data-go-view]")) button.addEventListener("click", () => switchView(button.dataset.goView));
  for (const button of all("[data-trading-tab]")) button.addEventListener("click", () => switchTradingTab(button.dataset.tradingTab));
  byId("refresh-button").addEventListener("click", () => loadPublished({ announce: true }));
  byId("load-file-button").addEventListener("click", () => byId("snapshot-file").click());
  byId("snapshot-file").addEventListener("change", (event) => loadLocalFile(event.target.files?.[0]));
  byId("restore-published-button").addEventListener("click", () => loadPublished({ announce: true }));
  byId("signal-search").addEventListener("input", renderSignalTable);
  byId("signal-status-filter").addEventListener("change", renderSignalTable);
  byId("theme-toggle").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  byId("signal-dialog").addEventListener("click", (event) => {
    const dialog = byId("signal-dialog");
    if (event.target === dialog) dialog.close();
  });
  window.addEventListener("hashchange", () => switchView(location.hash.slice(1) || "overview", false));
  window.addEventListener("dragover", (event) => {
    if ([...(event.dataTransfer?.types || [])].includes("Files")) event.preventDefault();
  });
  window.addEventListener("drop", (event) => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    event.preventDefault();
    const file = event.dataTransfer?.files?.[0];
    if (file?.name.toLowerCase().endsWith(".json")) loadLocalFile(file);
    else showToast("Drop a Daybreak JSON snapshot to load it locally.");
  });
}

function initializeTheme() {
  let saved = "dark";
  try {
    saved = localStorage.getItem("daybreak-theme") || (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  } catch {
    saved = "dark";
  }
  applyTheme(saved);
}

function initialize() {
  initializeTheme();
  bindEvents();
  const requestedView = location.hash.slice(1);
  switchView(VIEW_META[requestedView] ? requestedView : "overview", false);
  switchTradingTab("signals");
  loadPublished();
  state.clockTimer = window.setInterval(updateFreshness, 1_000);
}

initialize();
