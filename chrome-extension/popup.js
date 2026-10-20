const DEFAULT_SERVER = "http://localhost:8000";

let serverUrl = DEFAULT_SERVER;
let activeAccountId = null;
let accounts = [];

// ── DOM helpers ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
function show(id) { $(id).classList.remove("hidden"); }
function hide(id) { $(id).classList.add("hidden"); }
function showOnly(id) {
  ["setup-section", "offline-section", "main-section"].forEach(s => hide(s));
  show(id);
}

// ── Storage ───────────────────────────────────────────────────────────────────
async function loadSettings() {
  return new Promise(r => chrome.storage.local.get(
    ["serverUrl", "activeAccountId", "lastSummary", "lastPollAt", "serverOnline"],
    r
  ));
}

async function saveSettings() {
  chrome.storage.local.set({ serverUrl, activeAccountId });
}

// ── Render ────────────────────────────────────────────────────────────────────
function renderSummary(summary) {
  if (!summary) return;
  $("stat-breaches").textContent = summary.breaches ?? "—";
  $("stat-pending").textContent = summary.opt_out_pending ?? "—";
  $("stat-errors").textContent = summary.opt_out_error ?? "—";
  $("stat-confirmed").textContent = summary.opt_out_confirmed ?? "—";

  const bar = $("overall-status");
  const icon = $("status-icon");
  const text = $("status-text");

  bar.className = "status-bar";
  if (summary.overall_status === "error") {
    bar.classList.add("status-error");
    icon.textContent = "🔴";
    text.textContent = "Atención requerida";
  } else if (summary.overall_status === "warning") {
    bar.classList.add("status-warning");
    icon.textContent = "🟡";
    text.textContent = "Opt-outs pendientes";
  } else {
    bar.classList.add("status-ok");
    icon.textContent = "🟢";
    text.textContent = "Todo en orden";
  }

  if (summary.last_scan) {
    const d = new Date(summary.last_scan);
    $("last-scan-meta").textContent = `Último scan: ${d.toLocaleDateString("es")} ${d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}`;
  }
}

function renderAccounts() {
  const sel = $("account-select");
  sel.innerHTML = "";
  accounts.forEach(a => {
    const opt = document.createElement("option");
    opt.value = a.id;
    opt.textContent = a.email;
    if (a.id == activeAccountId) opt.selected = true;
    sel.appendChild(opt);
  });
}

function setServerDot(online) {
  const dot = $("server-status");
  dot.className = "server-dot " + (online ? "online" : "offline");
  dot.title = online ? "Servidor online" : "Servidor offline";
}

function setLastUpdated(ts) {
  if (!ts) return;
  const d = new Date(ts);
  $("last-updated").textContent = `Act. ${d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}`;
}

// ── Data fetching ─────────────────────────────────────────────────────────────
async function fetchAccounts() {
  try {
    const r = await fetch(`${serverUrl}/api/accounts`, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return [];
    return r.json();
  } catch { return []; }
}

async function fetchSummary(accountId) {
  try {
    const r = await fetch(`${serverUrl}/api/summary/${accountId}`, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return null;
    return r.json();
  } catch { return null; }
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  const stored = await loadSettings();
  serverUrl = stored.serverUrl || DEFAULT_SERVER;
  activeAccountId = stored.activeAccountId || null;

  setServerDot(stored.serverOnline !== false);
  setLastUpdated(stored.lastPollAt);

  if (stored.lastSummary) {
    showOnly("main-section");
    renderSummary(stored.lastSummary);
  }

  // Try live fetch
  accounts = await fetchAccounts();

  if (!accounts.length) {
    setServerDot(false);
    if (!stored.lastSummary) {
      showOnly("offline-section");
    } else {
      showOnly("offline-section");
    }
    return;
  }

  setServerDot(true);
  if (!activeAccountId) activeAccountId = accounts[0].id;

  renderAccounts();
  showOnly("main-section");

  const summary = await fetchSummary(activeAccountId);
  if (summary) {
    renderSummary(summary);
    chrome.storage.local.set({ lastSummary: summary, lastPollAt: Date.now() });
    setLastUpdated(Date.now());
  }
}

// ── Events ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  init();

  $("account-select")?.addEventListener("change", async e => {
    activeAccountId = parseInt(e.target.value);
    await saveSettings();
    const summary = await fetchSummary(activeAccountId);
    if (summary) renderSummary(summary);
  });

  $("scan-btn")?.addEventListener("click", async () => {
    const btn = $("scan-btn");
    btn.disabled = true;
    btn.textContent = "Escaneando...";
    chrome.runtime.sendMessage({ type: "scan" }, res => {
      btn.disabled = false;
      btn.textContent = "▶ Escanear ahora";
      if (res?.ok) {
        init();
      }
    });
  });

  $("open-dashboard-btn")?.addEventListener("click", () => {
    chrome.tabs.create({ url: serverUrl });
  });

  $("retry-btn")?.addEventListener("click", () => init());

  $("change-url-btn")?.addEventListener("click", () => {
    $("server-url-input").value = serverUrl;
    showOnly("setup-section");
  });

  $("settings-toggle")?.addEventListener("click", () => {
    if (!$("setup-section").classList.contains("hidden")) {
      init();
    } else {
      $("server-url-input").value = serverUrl;
      showOnly("setup-section");
    }
  });

  $("save-settings-btn")?.addEventListener("click", async () => {
    const url = $("server-url-input").value.trim().replace(/\/$/, "");
    if (!url) return;
    serverUrl = url;
    await saveSettings();
    await init();
  });
});
