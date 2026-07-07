/**
 * Define & Translate - Background Service Worker
 * Proxies API requests to localhost so they originate from the extension
 * (avoids Local Network Access permission prompt on the host page).
 */

const abortControllers = new Map();

// Open the onboarding page on first install so the user can review the data
// disclosure and grant consent before any data is collected.
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.tabs.create({ url: chrome.runtime.getURL("onboarding/onboarding.html") });
  }
});

chrome.runtime.onMessage.addListener(
  (message, sender, sendResponse) => {
    if (message.type === "fetchLookup") {
      handleFetchLookup(message, sendResponse);
      return true; // Keep channel open for async response
    }
    if (message.type === "abortLookup") {
      handleAbortLookup(message);
      sendResponse({ ok: true });
      return false;
    }
    if (message.type === "openOnboarding") {
      chrome.tabs.create({ url: chrome.runtime.getURL("onboarding/onboarding.html") });
      sendResponse({ ok: true });
      return false;
    }
  }
);

async function handleFetchLookup(message, sendResponse) {
  const { requestId, apiBase, payload } = message;
  const controller = new AbortController();
  abortControllers.set(requestId, controller);

  try {
    const tStart = performance.now();
    const res = await fetch(`${apiBase}/api/lookup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    let data = {};
    try { data = await res.json(); } catch { /* non-JSON body — leave data empty */ }
    const apiRoundTripMs = Math.round(performance.now() - tStart);
    console.log("[DT] API round-trip (background -> FastAPI -> back):", apiRoundTripMs, "ms");
    abortControllers.delete(requestId);
    sendResponse({ requestId, ok: res.ok, status: res.status, data });
  } catch (err) {
    abortControllers.delete(requestId);
    if (err.name === "AbortError") {
      sendResponse({ requestId, ok: false, aborted: true });
    } else {
      sendResponse({ requestId, ok: false, error: err.message });
    }
  }
}

function handleAbortLookup(message) {
  const { requestId } = message;
  const controller = abortControllers.get(requestId);
  if (controller) {
    controller.abort();
    abortControllers.delete(requestId);
  }
}
