const DEFAULT_SERVER = "http://localhost:8000";
const POLL_INTERVAL_MINUTES = 15;

async function getSettings() {
  return new Promise(resolve => {
    chrome.storage.local.get(["serverUrl", "activeAccountId"], data => {
      resolve({
        serverUrl: data.serverUrl || DEFAULT_SERVER,
        accountId: data.activeAccountId || null,
      });
    });
  });
}

async function fetchSummary(serverUrl, accountId) {
  if (!accountId) {
    // Try to get first account
    const resp = await fetch(`${serverUrl}/api/accounts`, { signal: AbortSignal.timeout(5000) });
    if (!resp.ok) return null;
    const accounts = await resp.json();
    if (!accounts.length) return null;
    accountId = accounts[0].id;
    chrome.storage.local.set({ activeAccountId: accountId });
  }
  const resp = await fetch(`${serverUrl}/api/summary/${accountId}`, {
    signal: AbortSignal.timeout(5000),
  });
  if (!resp.ok) return null;
  return resp.json();
}

function updateBadge(summary) {
  if (!summary) {
    chrome.action.setBadgeText({ text: "?" });
    chrome.action.setBadgeBackgroundColor({ color: "#666" });
    return;
  }

  const issues = summary.opt_out_error + summary.breaches;
  const pending = summary.opt_out_pending;

  if (issues > 0) {
    chrome.action.setBadgeText({ text: String(issues) });
    chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
  } else if (pending > 0) {
    chrome.action.setBadgeText({ text: String(pending) });
    chrome.action.setBadgeBackgroundColor({ color: "#f59e0b" });
  } else {
    chrome.action.setBadgeText({ text: "✓" });
    chrome.action.setBadgeBackgroundColor({ color: "#22c55e" });
  }
}

async function poll() {
  try {
    const { serverUrl, accountId } = await getSettings();
    const summary = await fetchSummary(serverUrl, accountId);

    // Check for new errors and notify
    const prevKey = `prev_status_${accountId}`;
    const prev = await new Promise(r => chrome.storage.local.get(prevKey, d => r(d[prevKey])));
    if (prev && summary) {
      if (summary.opt_out_error > (prev.opt_out_error || 0)) {
        chrome.notifications.create({
          type: "basic",
          iconUrl: "icons/icon48.png",
          title: "Gmail Cleaner — Error en opt-out",
          message: `${summary.opt_out_error} solicitud(es) de opt-out fallaron. Revisa el dashboard.`,
        });
      }
      if (summary.breaches > (prev.breaches || 0)) {
        chrome.notifications.create({
          type: "basic",
          iconUrl: "icons/icon48.png",
          title: "Gmail Cleaner — Nueva brecha detectada",
          message: `Tu email aparece en ${summary.breaches} brecha(s) de datos.`,
        });
      }
    }

    if (summary) {
      chrome.storage.local.set({ [prevKey]: summary });
    }

    updateBadge(summary);
    chrome.storage.local.set({ lastSummary: summary, lastPollAt: Date.now(), serverOnline: !!summary });
  } catch {
    updateBadge(null);
    chrome.storage.local.set({ serverOnline: false });
  }
}

// Setup alarm
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("poll", { periodInMinutes: POLL_INTERVAL_MINUTES });
  poll();
});

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === "poll") poll();
});

// Poll when extension icon is clicked (before popup opens)
chrome.action.onClicked && chrome.action.onClicked.addListener(() => poll());

// Message from popup: force poll
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "poll") {
    poll().then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg.type === "scan") {
    getSettings().then(async ({ serverUrl, accountId }) => {
      if (!accountId) { sendResponse({ ok: false }); return; }
      try {
        const r = await fetch(`${serverUrl}/api/scan/${accountId}`, {
          method: "POST",
          signal: AbortSignal.timeout(10000),
        });
        const data = await r.json();
        await poll();
        sendResponse({ ok: true, scanned: data.scanned });
      } catch {
        sendResponse({ ok: false });
      }
    });
    return true;
  }
});
