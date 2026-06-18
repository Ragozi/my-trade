const API = "";

async function fetchJson(path) {
  const r = await fetch(API + path);
  return r.json();
}

function fmtMoney(n) {
  if (n == null || isNaN(n)) return "—";
  const sign = n < 0 ? "-" : "";
  return sign + "$" + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtPct(n) {
  if (n == null || isNaN(n)) return "—";
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

function fmtVol(n) {
  if (!n) return "—";
  return (n / 1e6).toFixed(1) + "M";
}

function pnlClass(v) {
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "";
}

function eventClass(type) {
  return "event-type " + (type || "").replace(/\s/g, "_");
}

async function loadDashboard() {
  const [config, account, stats, events, trades, universe] = await Promise.all([
    fetchJson("/api/config"),
    fetchJson("/api/account"),
    fetchJson("/api/stats"),
    fetchJson("/api/events"),
    fetchJson("/api/trades"),
    fetchJson("/api/universe"),
  ]);

  const modeBadge = document.getElementById("mode-badge");
  if (config.paper_trading) {
    modeBadge.textContent = "Paper";
    modeBadge.className = "badge badge-paper";
  } else {
    modeBadge.textContent = "Live";
    modeBadge.className = "badge badge-live";
  }

  const sym = (config.symbols && config.symbols[0]) || "BTC/USD";
  document.getElementById("config-band").textContent =
    `${sym} | $${config.notional_per_trade}/trade | 24/7`;

  const equity = account.equity ?? 0;
  const dailyPnl = account.daily_pnl ?? stats.today?.total_pnl ?? 0;
  const pnlPct = equity > 0 ? (dailyPnl / equity) * 100 : 0;

  document.getElementById("kpi-equity").textContent = fmtMoney(equity);
  document.getElementById("kpi-equity").className = "value";

  const pnlEl = document.getElementById("kpi-pnl");
  pnlEl.textContent = fmtMoney(dailyPnl);
  pnlEl.className = "value " + pnlClass(dailyPnl);
  document.getElementById("kpi-pnl-sub").textContent = fmtPct(pnlPct);

  document.getElementById("kpi-bp").textContent = fmtMoney(account.buying_power);
  document.getElementById("kpi-positions").textContent =
    (account.positions || []).length;

  const t = stats.today || {};
  document.getElementById("kpi-winrate").textContent =
    t.closed_trades ? t.win_rate.toFixed(0) + "%" : "—";
  document.getElementById("kpi-winrate-sub").textContent =
    `${t.wins || 0}W / ${t.losses || 0}L (${t.closed_trades || 0} closed)`;

  document.getElementById("kpi-signals").textContent = t.signals_today ?? 0;
  document.getElementById("kpi-entries").textContent = t.entries_today ?? 0;

  const marketEl = document.getElementById("kpi-market");
  if (account.error) {
    marketEl.textContent = "N/A";
    marketEl.className = "value";
  } else {
    marketEl.textContent = account.market_open ? "Open" : "Closed";
    marketEl.className = "value " + (account.market_open ? "positive" : "");
  }

  renderEvents(events);
  renderTrades(trades);
  renderUniverse(universe);
  renderPositions(account.positions || []);
}

function renderEvents(events) {
  const tbody = document.querySelector("#events-table tbody");
  if (!events?.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="loading">No events yet — run the bot to populate.</td></tr>';
    return;
  }
  tbody.innerHTML = events
    .map(
      (e) => `
    <tr>
      <td>${new Date(e.created_at).toLocaleString()}</td>
      <td><span class="${eventClass(e.event_type)}">${e.event_type}</span></td>
      <td>${e.symbol || "—"}</td>
      <td>${e.message}</td>
    </tr>`
    )
    .join("");
}

function renderTrades(trades) {
  const tbody = document.querySelector("#trades-table tbody");
  if (!trades?.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="loading">No trades logged yet.</td></tr>';
    return;
  }
  tbody.innerHTML = trades
    .map((t) => {
      const pnl = t.pnl != null ? fmtMoney(t.pnl) : "open";
      const cls = t.pnl != null ? pnlClass(t.pnl) : "";
      return `
    <tr>
      <td>${new Date(t.created_at).toLocaleString()}</td>
      <td><strong>${t.symbol}</strong></td>
      <td>${t.qty?.toFixed(4) ?? "—"}</td>
      <td>${fmtMoney(t.entry_price)}</td>
      <td>${t.exit_price != null ? fmtMoney(t.exit_price) : "—"}</td>
      <td class="${cls}">${pnl}</td>
      <td>${t.exit_reason || "—"}</td>
    </tr>`;
    })
    .join("");
}

function renderUniverse(data) {
  const ul = document.getElementById("universe-list");
  const meta = document.getElementById("universe-meta");
  const symbols = data?.file?.symbols || data?.journal?.symbols || [];

  if (!symbols.length) {
    ul.innerHTML = '<li class="loading">No universe scan yet. Start the bot.</li>';
    meta.textContent = "";
    return;
  }

  meta.textContent = data.file
    ? `Updated ${new Date(data.file.scanned_at).toLocaleString()} · ${data.file.candidates_checked} checked · sources: ${(data.file.sources || []).join(", ")}`
    : "";

  ul.innerHTML = symbols
    .map(
      (s) => `
    <li>
      <span><strong>${s.symbol}</strong> <span class="meta">${s.source || ""}</span></span>
      <span>$${Number(s.price).toFixed(2)} · ${fmtVol(s.avg_volume)} vol</span>
    </li>`
    )
    .join("");
}

function renderPositions(positions) {
  const tbody = document.querySelector("#positions-table tbody");
  if (!positions.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="loading">No open positions</td></tr>';
    return;
  }
  tbody.innerHTML = positions
    .map(
      (p) => `
    <tr>
      <td><strong>${p.symbol}</strong></td>
      <td>${p.qty?.toFixed(4)}</td>
      <td>${fmtMoney(p.avg_entry_price)}</td>
      <td class="${pnlClass(p.unrealized_pl)}">${fmtMoney(p.unrealized_pl)}</td>
    </tr>`
    )
    .join("");
}

document.getElementById("refresh-btn").addEventListener("click", () => {
  document.body.style.opacity = "0.6";
  loadDashboard().finally(() => {
    document.body.style.opacity = "1";
  });
});

loadDashboard();
setInterval(loadDashboard, 30000);
