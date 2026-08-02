import {
  normalizeSnapshot,
  SnapshotError,
  computeRiskUsage,
  computeDailyLossUsage,
  sortSetups,
  groupExitReasons,
  summarizeTrades,
  equityCurveToPath,
  equityCurveBounds,
  worstSystemStatus,
  formatCurrency,
  formatPercent,
} from "./data.mjs";

const DEMO_SNAPSHOT_URL = "./data/dashboard.json";

const state = {
  snapshot: null,
  sourceIsPrivate: false,
  activeView: "overview",
};

const views = {
  overview: document.getElementById("view-overview"),
  trading: document.getElementById("view-trading"),
  performance: document.getElementById("view-performance"),
  system: document.getElementById("view-system"),
};

const sourceLabel = document.getElementById("source-label");
const resetSourceButton = document.getElementById("reset-source-button");
const privateFileInput = document.getElementById("private-file-input");
const tabButtons = [...document.querySelectorAll(".tab")];

init();

async function init() {
  wireNav();
  wirePrivateLoader();
  await loadDemoSnapshot();
  renderAll();
}

function wireNav() {
  for (const button of tabButtons) {
    button.addEventListener("click", () => {
      setActiveView(button.dataset.view);
    });
  }
}

function setActiveView(view) {
  if (!views[view]) return;
  state.activeView = view;
  for (const [name, section] of Object.entries(views)) {
    section.hidden = name !== view;
  }
  for (const button of tabButtons) {
    const selected = button.dataset.view === view;
    button.setAttribute("aria-selected", String(selected));
    button.classList.toggle("is-active", selected);
  }
}

function wirePrivateLoader() {
  privateFileInput.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      state.snapshot = normalizeSnapshot(parsed);
      state.sourceIsPrivate = true;
      sourceLabel.textContent = `Private snapshot: ${file.name} (local only, not uploaded)`;
      resetSourceButton.hidden = false;
      renderAll();
    } catch (error) {
      const reason = error instanceof SnapshotError ? error.message : "invalid JSON file";
      window.alert(`Could not load private snapshot: ${reason}`);
    } finally {
      privateFileInput.value = "";
    }
  });

  resetSourceButton.addEventListener("click", async () => {
    resetSourceButton.hidden = true;
    await loadDemoSnapshot();
    renderAll();
  });
}

async function loadDemoSnapshot() {
  const response = await fetch(DEMO_SNAPSHOT_URL);
  if (!response.ok) {
    throw new Error(`failed to load demo snapshot: HTTP ${response.status}`);
  }
  const parsed = await response.json();
  state.snapshot = normalizeSnapshot(parsed);
  state.sourceIsPrivate = false;
  sourceLabel.textContent = "Demo data (fictional, public-safe)";
}

function renderAll() {
  const snapshot = state.snapshot;
  if (!snapshot) return;
  renderOverview(views.overview, snapshot);
  renderTrading(views.trading, snapshot);
  renderPerformance(views.performance, snapshot);
  renderSystem(views.system, snapshot);
}

// ---------- DOM helpers ----------

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.class) node.className = options.class;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.attrs) {
    for (const [key, value] of Object.entries(options.attrs)) {
      node.setAttribute(key, value);
    }
  }
  for (const child of children) {
    if (child) node.append(child);
  }
  return node;
}

function clear(node) {
  node.replaceChildren();
}

function statTile(label, value, options = {}) {
  const valueClass = options.tone ? `stat-value stat-value--${options.tone}` : "stat-value";
  return el("div", { class: "stat-tile" }, [
    el("div", { class: "stat-label", text: label }),
    el("div", { class: valueClass, text: value }),
    options.sub ? el("div", { class: "stat-sub", text: options.sub }) : null,
  ]);
}

function statusChip(status, label) {
  return el("span", { class: `chip chip--${status}` }, [
    el("span", { class: "chip-dot", attrs: { "aria-hidden": "true" } }),
    el("span", { text: label }),
  ]);
}

function toneForNumber(value) {
  if (value > 0) return "good";
  if (value < 0) return "critical";
  return "neutral";
}

function buildTable(headers, rows, emptyMessage = "No data.") {
  if (!rows.length) {
    return el("p", { class: "empty-state", text: emptyMessage });
  }
  const thead = el(
    "thead",
    {},
    [el("tr", {}, headers.map((h) => el("th", { text: h.label, attrs: { scope: "col" } })))],
  );
  const tbody = el(
    "tbody",
    {},
    rows.map((row) =>
      el(
        "tr",
        {},
        headers.map((h) => {
          const cellValue = h.format ? h.format(row) : row[h.key];
          const cell = el("td", { text: String(cellValue ?? "") });
          if (h.numeric) cell.classList.add("num");
          if (h.tone) cell.classList.add(`tone-${h.tone(row)}`);
          return cell;
        }),
      ),
    ),
  );
  return el("table", { class: "data-table" }, [thead, tbody]);
}

/**
 * `tone: "budget"` (default) is for a value that gets worse as it rises toward its
 * cap — a risk or loss budget — so the fill turns warning/danger near the cap.
 * `tone: "progress"` is for a value that gets better as it rises toward its
 * target — qualification completion — so the fill never turns warning/danger.
 */
function meter(currentLabel, maxLabel, ratio, { tone = "budget" } = {}) {
  const track = el("div", { class: "meter-track" });
  const fill = el("div", { class: "meter-fill" });
  fill.style.width = `${Math.round(ratio * 100)}%`;
  if (tone === "budget") {
    if (ratio >= 0.9) fill.classList.add("meter-fill--danger");
    else if (ratio >= 0.7) fill.classList.add("meter-fill--warning");
  }
  track.append(fill);
  const caption =
    tone === "progress" ? `${currentLabel} of ${maxLabel}` : `${currentLabel}% of ${maxLabel}% max`;
  return el("div", { class: "meter" }, [track, el("div", { class: "meter-caption", text: caption })]);
}

function equityChart(points) {
  const width = 640;
  const height = 160;
  const path = equityCurveToPath(points, width, height);
  const { min, max } = equityCurveBounds(points);
  const svgNs = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNs, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "equity-chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Session equity curve from ${formatCurrency(min)} to ${formatCurrency(max)}`);

  const areaPath = document.createElementNS(svgNs, "path");
  areaPath.setAttribute("d", `${path} L${width - 4},${height - 4} L4,${height - 4} Z`);
  areaPath.setAttribute("class", "equity-area");
  svg.append(areaPath);

  const linePath = document.createElementNS(svgNs, "path");
  linePath.setAttribute("d", path);
  linePath.setAttribute("class", "equity-line");
  linePath.setAttribute("fill", "none");
  svg.append(linePath);

  const wrapper = el("div", { class: "chart-card" }, [svg]);

  const details = document.createElement("details");
  details.className = "table-toggle";
  const summary = el("summary", { text: "View as table" });
  details.append(summary);
  details.append(
    buildTable(
      [
        { key: "t", label: "Time (ET)" },
        { key: "equity", label: "Equity", numeric: true, format: (r) => formatCurrency(r.equity) },
      ],
      points,
    ),
  );
  wrapper.append(details);
  return wrapper;
}

// ---------- View renderers ----------

function renderOverview(container, snapshot) {
  clear(container);
  const { session, account, risk, positions, system } = snapshot;
  const riskUsage = computeRiskUsage(risk);

  const stats = el("div", { class: "stat-grid" }, [
    statTile("Session state", session.state, { sub: `${session.phase} · ${session.market_status}` }),
    statTile("Account equity", formatCurrency(account.current_equity), {
      tone: toneForNumber(account.day_pnl),
      sub: `${formatCurrency(account.day_pnl)} (${formatPercent(account.day_pnl_pct)}) today`,
    }),
    statTile("Drawdown", formatPercent(account.drawdown_pct), {
      tone: account.drawdown_pct < 0 ? "critical" : "neutral",
      sub: `Max this session ${formatPercent(account.max_drawdown_pct)}`,
    }),
    statTile("Open positions", String(positions.length), {
      sub: `${riskUsage.currentPct}% of ${riskUsage.maxPct}% risk budget used`,
    }),
  ]);

  const killSwitch = el("div", { class: "panel" }, [
    el("h3", { text: "Kill switch" }),
    statusChip(session.kill_switch_active ? "critical" : "good", session.kill_switch_active ? "ACTIVE" : "Inactive"),
    el("p", { class: "panel-note", text: `Leader: ${session.leader_holder}` }),
  ]);

  const riskPanel = el("div", { class: "panel" }, [
    el("h3", { text: "Open risk budget" }),
    meter(riskUsage.currentPct, riskUsage.maxPct, riskUsage.ratio),
  ]);

  const dailyLoss = computeDailyLossUsage(risk);
  const dailyLossPanel = el("div", { class: "panel" }, [
    el("h3", { text: "Daily loss budget" }),
    meter(dailyLoss.currentPct, dailyLoss.maxPct, dailyLoss.ratio),
  ]);

  const systemStatus = worstSystemStatus(system.layers);
  const systemPanel = el("div", { class: "panel" }, [
    el("h3", { text: "System status" }),
    statusChip(systemStatus, systemStatus === "good" ? "All layers healthy" : "Attention needed"),
  ]);

  const panels = el("div", { class: "panel-grid" }, [killSwitch, riskPanel, dailyLossPanel, systemPanel]);

  const equity = el("section", { class: "section" }, [
    el("h2", { text: "Account curve" }),
    equityChart(account.equity_curve),
  ]);

  const positionsTable = buildTable(
    [
      { key: "symbol", label: "Symbol" },
      { key: "side", label: "Side" },
      { key: "quantity", label: "Qty", numeric: true },
      { key: "avg_entry_price", label: "Entry", numeric: true, format: (r) => formatCurrency(r.avg_entry_price) },
      { key: "current_price", label: "Last", numeric: true, format: (r) => formatCurrency(r.current_price) },
      {
        key: "unrealized_pnl",
        label: "Unrealized P&L",
        numeric: true,
        format: (r) => `${formatCurrency(r.unrealized_pnl)} (${formatPercent(r.unrealized_pnl_pct)})`,
        tone: (r) => toneForNumber(r.unrealized_pnl),
      },
    ],
    positions,
    "No open positions.",
  );

  const alerts = el(
    "ul",
    { class: "alert-list" },
    system.alerts.map((alert) =>
      el("li", { class: "alert-item" }, [
        statusChip(alert.severity, alert.severity.toUpperCase()),
        el("span", { class: "alert-message", text: alert.message }),
        el("time", { class: "alert-time", text: formatTime(alert.at) }),
      ]),
    ),
  );

  container.append(
    stats,
    panels,
    equity,
    el("section", { class: "section" }, [el("h2", { text: "Managed positions" }), positionsTable]),
    el("section", { class: "section" }, [el("h2", { text: "Alerts" }), alerts]),
  );
}

function renderTrading(container, snapshot) {
  clear(container);
  const setups = sortSetups(snapshot.setups);

  const setupsTable = buildTable(
    [
      { key: "rank", label: "Rank", numeric: true },
      { key: "ticker", label: "Ticker" },
      {
        key: "status",
        label: "Status",
        format: (r) => (r.status === "approved" ? "Approved" : "Qualified"),
      },
      { key: "conviction_score", label: "Conviction", numeric: true },
      { key: "catalyst_points", label: "Catalyst", numeric: true },
      { key: "volume_points", label: "Volume", numeric: true },
      { key: "technical_points", label: "Technical", numeric: true },
      { key: "magnitude_bucket", label: "Magnitude" },
    ],
    setups,
    "No ranked setups this session.",
  );

  const ordersTable = buildTable(
    [
      { key: "client_order_id", label: "Client order ID" },
      { key: "symbol", label: "Symbol" },
      { key: "side", label: "Side" },
      { key: "order_class", label: "Class" },
      { key: "status", label: "Status" },
      {
        key: "filled_quantity",
        label: "Filled / Qty",
        numeric: true,
        format: (r) => `${r.filled_quantity} / ${r.quantity}`,
      },
      {
        key: "limit_price",
        label: "Limit",
        numeric: true,
        format: (r) => (r.limit_price == null ? "—" : formatCurrency(r.limit_price)),
      },
    ],
    snapshot.orders,
    "No broker orders this session.",
  );

  const positionsTable = buildTable(
    [
      { key: "symbol", label: "Symbol" },
      { key: "side", label: "Side" },
      { key: "quantity", label: "Qty", numeric: true },
      { key: "stop_price", label: "Stop", numeric: true, format: (r) => formatCurrency(r.stop_price) },
      { key: "target_price", label: "Target", numeric: true, format: (r) => formatCurrency(r.target_price) },
    ],
    snapshot.positions,
    "No open positions.",
  );

  container.append(
    el("section", { class: "section" }, [el("h2", { text: "Ranked setups" }), setupsTable]),
    el("section", { class: "section" }, [el("h2", { text: "Managed positions" }), positionsTable]),
    el("section", { class: "section" }, [el("h2", { text: "Broker orders" }), ordersTable]),
  );
}

function renderPerformance(container, snapshot) {
  clear(container);
  const { trades, exit_reason_breakdown: exitReasons, rank_attribution: rankAttribution } =
    snapshot.performance;
  const summary = summarizeTrades(trades);

  const stats = el("div", { class: "stat-grid" }, [
    statTile("Closed trades", String(summary.totalTrades)),
    statTile("Win rate", formatPercent(summary.winRatePct, 1), {
      tone: summary.winRatePct >= 50 ? "good" : "critical",
    }),
    statTile("Total P&L", formatCurrency(summary.totalPnl), { tone: toneForNumber(summary.totalPnl) }),
    statTile("Avg R-multiple", `${summary.avgRMultiple}R`, { tone: toneForNumber(summary.avgRMultiple) }),
  ]);

  const breakdown = groupExitReasons(trades);
  const exitBars = el(
    "div",
    { class: "bar-list" },
    (exitReasons.length ? exitReasons : breakdown).map((row) =>
      el("div", { class: "bar-row" }, [
        el("div", { class: "bar-label", text: row.reason }),
        el("div", { class: "bar-track" }, [
          (() => {
            const fill = el("div", { class: "bar-fill" });
            fill.style.width = `${row.pct}%`;
            return fill;
          })(),
        ]),
        el("div", { class: "bar-value", text: `${row.count} (${row.pct}%)` }),
      ]),
    ),
  );

  const attributionTable = buildTable(
    [
      { key: "rank_bucket", label: "Rank" },
      { key: "trade_count", label: "Trades", numeric: true },
      { key: "win_rate_pct", label: "Win rate", numeric: true, format: (r) => formatPercent(r.win_rate_pct, 1) },
      { key: "avg_r_multiple", label: "Avg R", numeric: true, format: (r) => `${r.avg_r_multiple}R` },
    ],
    rankAttribution,
  );

  const tradesTable = buildTable(
    [
      { key: "symbol", label: "Symbol" },
      { key: "entry_price", label: "Entry", numeric: true, format: (r) => formatCurrency(r.entry_price) },
      { key: "exit_price", label: "Exit", numeric: true, format: (r) => formatCurrency(r.exit_price) },
      { key: "quantity", label: "Qty", numeric: true },
      { key: "pnl", label: "P&L", numeric: true, format: (r) => formatCurrency(r.pnl), tone: (r) => toneForNumber(r.pnl) },
      { key: "r_multiple", label: "R", numeric: true, format: (r) => `${r.r_multiple}R` },
      { key: "exit_reason", label: "Exit reason" },
    ],
    trades,
    "No closed trades.",
  );

  container.append(
    stats,
    el("section", { class: "section" }, [el("h2", { text: "Exit reasons" }), exitBars]),
    el("section", { class: "section" }, [el("h2", { text: "Rank attribution" }), attributionTable]),
    el("section", { class: "section" }, [el("h2", { text: "Trade history" }), tradesTable]),
  );
}

function renderSystem(container, snapshot) {
  clear(container);
  const { layers, safety_controls: safetyControls, qualification, release } = snapshot.system;

  const layerGrid = el(
    "div",
    { class: "layer-grid" },
    layers.map((layer) =>
      el("div", { class: "layer-card" }, [
        el("div", { class: "layer-head" }, [
          el("span", { class: "layer-name", text: layer.name }),
          statusChip(layer.status, layer.status.toUpperCase()),
        ]),
        el("p", { class: "layer-detail", text: layer.detail }),
      ]),
    ),
  );

  const safetyList = el(
    "div",
    { class: "safety-grid" },
    safetyControls.map((control) =>
      el("div", { class: "panel" }, [
        el("h3", { text: control.name }),
        statusChip(safetyTone(control.state), control.state),
        el("p", { class: "panel-note", text: control.detail }),
      ]),
    ),
  );

  const qualPanel = el("div", { class: "panel-grid" }, [
    qualificationMeter("Paper sessions", qualification.sessions_completed, qualification.sessions_required),
    qualificationMeter("Reconciled fills", qualification.fills_completed, qualification.fills_required),
    qualificationMeter(
      "Restore drills",
      qualification.restore_drills_completed,
      qualification.restore_drills_required,
    ),
  ]);

  const releasePanel = el("div", { class: "panel" }, [
    el("h3", { text: "Release evidence" }),
    el("p", { class: "panel-note", text: `Version ${release.version}` }),
    statusChip(release.live_capital_eligible ? "critical" : "good", release.live_capital_eligible ? "LIVE-CAPITAL ELIGIBLE" : "Live-capital ineligible"),
    el("p", { class: "panel-note", text: `Last review ${formatTime(release.last_review_at)}` }),
  ]);

  container.append(
    el("section", { class: "section" }, [el("h2", { text: "Service layers" }), layerGrid]),
    el("section", { class: "section" }, [el("h2", { text: "Fail-closed safety controls" }), safetyList]),
    el("section", { class: "section" }, [el("h2", { text: "Qualification progress" }), qualPanel]),
    el("section", { class: "section" }, [el("h2", { text: "Release" }), releasePanel]),
  );
}

function qualificationMeter(label, completed, required) {
  const ratio = required > 0 ? Math.min(completed / required, 1) : 0;
  return el("div", { class: "panel" }, [
    el("h3", { text: label }),
    meter(completed, required, ratio, { tone: "progress" }),
  ]);
}

function safetyTone(state) {
  if (state === "armed" || state === "active" || state === "disabled" || state === "paper-only") {
    return "good";
  }
  return "warning";
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return iso;
  }
}
