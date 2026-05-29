/**
 * Define & Translate - Content Script
 * Handles Define button, floating panel, and FastAPI integration.
 */

(function () {
  "use strict";

  const C = window.DT_CONSTANTS || {};
  const LANGUAGES = C.ALLOWED_LANGUAGES || [];
  const MAX_LEN = C.MAX_SELECTION_LENGTH || 300;
  const URL_KEYWORDS = C.UNSUPPORTED_URL_KEYWORDS || [];
  async function getApiBase() {
    const r = await chrome.storage.local.get(["api_base_url"]);
    return r.api_base_url || C.API_BASE_URL || "http://localhost:8000";
  }

  const DEFAULT_PANEL_WIDTH = 360;
  const DEFAULT_PANEL_HEIGHT = 400;
  const MIN_PANEL_WIDTH = 280;
  const MIN_PANEL_HEIGHT = 200;

  /** Nearest block-like ancestor for full_context; inline-only (e.g. <a>) is not enough. */
  const CONTEXT_ROOT_SELECTOR =
    "p, li, td, th, caption, dt, dd, blockquote, figcaption, article, section, main, [role='article'], h1, h2, h3, h4, h5, h6";

  /**
   * Panel inner roots only: using .dt-panel-content would include inter-element whitespace
   * from template literals (text nodes between child divs) at the start of textContent.
   */
  const PANEL_CONTEXT_ROOT_SELECTOR =
    ".dt-panel-meaning, .dt-panel-translation, .dt-panel-message, .dt-panel-header-text";

  /**
   * Element whose textContent supplies full_context. Walks up from the selection so
   * inline selections (e.g. inside <a>) still use the surrounding paragraph/block.
   */
  function getContextRootElement(range) {
    let node = range.commonAncestorContainer;
    if (node.nodeType === Node.TEXT_NODE) node = node.parentNode;
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return node;

    if (node.closest?.("[data-dt-panel]")) {
      const panelInner = node.closest?.(PANEL_CONTEXT_ROOT_SELECTOR);
      if (panelInner) return panelInner;
    }

    const preferred = node.closest?.(CONTEXT_ROOT_SELECTOR);
    if (preferred) return preferred;

    let cur = node.parentNode;
    while (cur && cur !== document.body) {
      if (cur.nodeType === Node.ELEMENT_NODE && (cur.tagName || "").toLowerCase() === "div") {
        return cur;
      }
      cur = cur.parentNode;
    }
    return node;
  }

  let defineBtn = null;
  let panel = null;
  let panelActive = false;
  let pendingRequestId = null;
  let lastRequestFingerprint = null;
  let defineClickDebounceTimer = null;
  let cachedMeaning = null;
  let cachedTranslation = null;
  let cachedFullContext = null;
  let isDragging = false;
  let isResizing = false;
  let resizeEdge = null;
  let dragStartX = 0, dragStartY = 0, panelStartX = 0, panelStartY = 0;
  let isSelecting = false;
  let selectionDebounceTimer = null;

  /** Light-DOM host for open shadow root; panel + Define button live inside shadow. */
  let dtShadowHost = null;
  let dtShadowRoot = null;
  let dtMountObserverTimer = null;

  function abortPendingLookupIfAny() {
    if (pendingRequestId) {
      chrome.runtime.sendMessage({ type: "abortLookup", requestId: pendingRequestId });
      pendingRequestId = null;
    }
  }

  function clearPanelStateOnly() {
    panelActive = false;
    cachedMeaning = null;
    cachedTranslation = null;
    cachedFullContext = null;
    lastRequestFingerprint = null;
    window.removeEventListener("resize", constrainPanelToViewport);
  }

  /**
   * Ensures shadow mount exists on document.body and clears stale element refs
   * when SPA navigation detaches injected nodes.
   */
  function ensureUiAttached() {
    if (!document.body) return;

    if (dtShadowHost && dtShadowHost.isConnected) {
      if (defineBtn && !defineBtn.isConnected) defineBtn = null;
      if (panel && !panel.isConnected) {
        abortPendingLookupIfAny();
        panel = null;
        clearPanelStateOnly();
      }
      return;
    }

    abortPendingLookupIfAny();
    dtShadowHost = null;
    dtShadowRoot = null;
    defineBtn = null;
    panel = null;
    clearPanelStateOnly();
    getDtShadowRoot();
  }

  /** Creates shadow host + loads extension CSS into shadow (isolated from page styles). */
  function getDtShadowRoot() {
    if (!document.body) return null;
    if (dtShadowHost && dtShadowHost.isConnected) return dtShadowRoot;

    dtShadowHost = null;
    dtShadowRoot = null;

    const host = document.createElement("div");
    host.setAttribute("data-dt-ui-mount", "true");
    host.style.cssText =
      "all:initial;position:fixed;top:0;left:0;width:0;height:0;margin:0;padding:0;border:0;" +
      "overflow:visible;pointer-events:none;z-index:2147483647;";
    const sr = host.attachShadow({ mode: "open" });
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = chrome.runtime.getURL("content/content.css");
    sr.appendChild(link);
    document.body.appendChild(host);
    dtShadowHost = host;
    dtShadowRoot = sr;
    return sr;
  }

  function patchHistoryForSpaNavigation() {
    if (window.__dtHistoryPatched) return;
    window.__dtHistoryPatched = true;
    const push = history.pushState.bind(history);
    const replace = history.replaceState.bind(history);
    history.pushState = (...args) => {
      const ret = push(...args);
      closePanel();
      queueMicrotask(ensureUiAttached);
      return ret;
    };
    history.replaceState = (...args) => {
      const ret = replace(...args);
      closePanel();
      queueMicrotask(ensureUiAttached);
      return ret;
    };
    window.addEventListener("popstate", () => { closePanel(); queueMicrotask(ensureUiAttached); });

    if (window.navigation) {
      window.navigation.addEventListener("navigate", (e) => {
        if (e.hashChange || e.downloadRequest !== null) return;
        closePanel();
        queueMicrotask(ensureUiAttached);
      });
    }
  }

  function startDtMountObserver() {
    if (!document.body || window.__dtMountObsStarted) return;
    window.__dtMountObsStarted = true;
    const obs = new MutationObserver(() => {
      clearTimeout(dtMountObserverTimer);
      dtMountObserverTimer = setTimeout(() => {
        if (!dtShadowHost || !dtShadowHost.isConnected) ensureUiAttached();
      }, 50);
    });
    obs.observe(document.body, { childList: true });
  }

  function isEditableElement(el) {
    if (!el) return false;
    const tag = (el.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return true;
    if (el.isContentEditable) return true;
    const role = (el.getAttribute?.("role") || "").toLowerCase();
    if (["textbox", "searchbox", "combobox"].includes(role)) return true;
    return el.closest?.(
      "input, textarea, select, [contenteditable], [role=textbox], [role=searchbox], [role=combobox]"
    );
  }

  function nodeInsideEditableField(node) {
    if (!node) return false;
    const el =
      node.nodeType === Node.TEXT_NODE
        ? node.parentElement
        : node.nodeType === Node.ELEMENT_NODE
          ? node
          : null;
    return !!(el && isEditableElement(el));
  }

  /**
   * Document Selection for native input/textarea is unreliable; use range endpoints, anchor/focus,
   * and common ancestor (FR-1.01-01a / FR-1.02-01a).
   */
  function isSelectionInsideEditableField(sel) {
    if (!sel || sel.rangeCount === 0) return false;
    let range;
    try {
      range = sel.getRangeAt(0);
    } catch {
      return false;
    }
    if (
      nodeInsideEditableField(sel.anchorNode) ||
      nodeInsideEditableField(sel.focusNode) ||
      nodeInsideEditableField(range.startContainer) ||
      nodeInsideEditableField(range.endContainer) ||
      nodeInsideEditableField(range.commonAncestorContainer)
    ) {
      return true;
    }
    return false;
  }

  /**
   * When the focused control is input/textarea, selection often matches value slice even if
   * anchorNode does not point into the field (FR-1.02-01a).
   */
  function isActiveNativeFieldSelection(text) {
    if (!text) return false;
    const ae = document.activeElement;
    if (!ae || (ae.tagName !== "INPUT" && ae.tagName !== "TEXTAREA")) return false;
    const typ = (ae.type || "").toLowerCase();
    if (
      ae.tagName === "INPUT" &&
      ["hidden", "button", "checkbox", "radio", "submit", "file", "image", "reset", "color", "range"].includes(typ)
    ) {
      return false;
    }
    const s = ae.selectionStart;
    const e = ae.selectionEnd;
    if (s == null || e == null || s === e) return false;
    const slice = ae.value.slice(s, e);
    return slice === text || slice.trim() === text.trim();
  }

  const CODE_OR_SCRIPT_SELECTOR = "script, pre, code";

  function nodeInsideNonTextMedia(node) {
    const el = elementFromSelectionNode(node);
    return !!(el && el.closest("img, video, canvas"));
  }

  /**
   * True if the selection touches image/video/canvas (anchor/focus or any such node in the
   * cloned range contents).
   */
  function selectionIntersectsNonTextMedia(sel) {
    if (!sel || sel.rangeCount === 0) return false;
    let range;
    try {
      range = sel.getRangeAt(0);
    } catch {
      return false;
    }
    if (nodeInsideNonTextMedia(sel.anchorNode) || nodeInsideNonTextMedia(sel.focusNode)) return true;
    try {
      const frag = range.cloneContents();
      if (frag?.querySelector?.("img, video, canvas")) return true;
    } catch {
      /* ignore */
    }
    return false;
  }

  function nodeInsideCodeOrScriptBlock(node) {
    const el = elementFromSelectionNode(node);
    return !!(el && el.closest(CODE_OR_SCRIPT_SELECTOR));
  }

  /**
   * True if the selection involves script/pre/code (endpoints or element nodes in the
   * range), including partial selections where cloneContents only has text but anchor is in code.
   */
  function selectionInvolvesCodeOrScript(sel) {
    if (!sel || sel.rangeCount === 0) return false;
    if (nodeInsideCodeOrScriptBlock(sel.anchorNode) || nodeInsideCodeOrScriptBlock(sel.focusNode)) {
      return true;
    }
    let range;
    try {
      range = sel.getRangeAt(0);
    } catch {
      return false;
    }
    try {
      const frag = range.cloneContents();
      if (frag?.querySelector?.(CODE_OR_SCRIPT_SELECTOR)) return true;
    } catch {
      /* ignore */
    }
    return false;
  }

  function selectionContainsDisallowedContent(sel) {
    return selectionIntersectsNonTextMedia(sel) || selectionInvolvesCodeOrScript(sel);
  }

  /** FR-1.02-01a: no Define button, no panel refresh, no lookup. */
  function shouldIgnoreSelectionForDefineAndLookup(sel, text) {
    return (
      isSelectionInsideEditableField(sel) ||
      isActiveNativeFieldSelection(text) ||
      selectionContainsDisallowedContent(sel)
    );
  }

  function hasDomExclusions() {
    const passwordFields = document.querySelectorAll('input[type="password"]');
    if (passwordFields.length > 0) return true;
    const paymentForms = document.querySelectorAll('form[action*="payment"], form[action*="checkout"], [data-payment], [data-checkout]');
    if (paymentForms.length > 0) return true;
    const paymentInputs = document.querySelectorAll('input[name*="payment"], input[name*="card"], input[name*="cvv"]');
    if (paymentInputs.length > 0) return true;
    return false;
  }

  function isSupportedUrl() {
    if (window.location.protocol !== "https:") return false;
    const url = window.location.href.toLowerCase();
    return !URL_KEYWORDS.some(kw => url.includes(kw));
  }

  function isPanelElement(el) {
    return el?.closest?.("[data-dt-panel]") || el?.closest?.("[data-dt-define-btn]");
  }

  /** Document-level listeners often see `event.target` as the shadow host, not the inner node. */
  function composedPathElements(e) {
    return e && typeof e.composedPath === "function" ? e.composedPath() : [];
  }

  function eventTouchesDtDefineButton(e) {
    if (e.target?.closest?.("[data-dt-define-btn]") || e.target?.closest?.(".dt-define-btn")) return true;
    return composedPathElements(e).some(
      n =>
        n &&
        n.nodeType === Node.ELEMENT_NODE &&
        (n.hasAttribute?.("data-dt-define-btn") || n.classList?.contains?.("dt-define-btn"))
    );
  }

  function eventTouchesDtPanel(e) {
    if (e.target?.closest?.("[data-dt-panel]")) return true;
    return composedPathElements(e).some(
      n => n && n.nodeType === Node.ELEMENT_NODE && n.closest?.("[data-dt-panel]")
    );
  }

  function eventTouchesDtLangSelect(e) {
    if (e.target?.closest?.(".dt-panel-lang-select")) return true;
    return composedPathElements(e).some(
      n => n && n.nodeType === Node.ELEMENT_NODE && n.closest?.(".dt-panel-lang-select")
    );
  }

  function isPanelChromeTargetFromEvent(e) {
    for (const n of composedPathElements(e)) {
      if (n && n.nodeType === Node.ELEMENT_NODE && isPanelChromeTarget(n)) return true;
    }
    return false;
  }

  /** anchorNode is often a Text node, which has no .closest; use parent element for panel/editable checks. */
  function elementFromSelectionNode(node) {
    if (!node) return null;
    if (node.nodeType === Node.TEXT_NODE) return node.parentElement;
    if (node.nodeType === Node.ELEMENT_NODE) return node;
    return null;
  }

  /** True if the event target is inside panel chrome (drag, resize, close) — not the selectable body text. */
  function isPanelChromeTarget(target) {
    if (!target?.closest?.("[data-dt-panel]")) return false;
    if (target.closest?.(".dt-panel-close")) return true;
    if (target.closest?.(".dt-panel-header")) return true;
    if (target.closest?.(".dt-panel-resize")) return true;
    if (target.closest?.(".dt-panel-lang-select")) return true;
    return false;
  }

  function getExtensionVersion() {
    return chrome?.runtime?.getManifest?.()?.version || "1.0.0";
  }

  function uuid4() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  /** Letters/digits (Unicode) plus apostrophe and hyphen as part of a word (e.g. don't, co-op). */
  function isWordInternalStr(ch) {
    if (!ch) return false;
    if (/[\p{L}\p{N}]/u.test(ch)) return true;
    if (ch === "'" || ch === "\u2019" || ch === "\u2018") return true;
    if (ch === "-" || ch === "\u2010" || ch === "\u2011" || ch === "\u2013") return true;
    return false;
  }

  /** Best-effort: skip word-boundary trim when context is likely CJK (no spaces between words). */
  function isCjkScriptChar(ch) {
    return /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]/u.test(ch);
  }

  /**
   * Words that should not be treated as sentence-ending when followed by a period.
   * Includes titles, ranks, month abbreviations, Latin abbreviations, and geographic
   * acronym segments. Entries with dots (e.g. "e.g", "U.S") represent the text
   * accumulated by the word-before-period extractor when scanning back through a
   * multi-dot abbreviation.
   */
  const SENTENCE_ABBR = new Set([
    "Mr", "Mrs", "Ms", "Dr", "Prof", "Sr", "Jr",
    "Gen", "Col", "Lt", "Sgt", "Cpl", "Capt", "Cmdr", "Adm", "Gov", "Rep", "Sen",
    "St", "Rev",
    "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec",
    "vs", "etc", "approx", "dept", "est", "vol", "pp", "fig", "no", "No",
    "e", "i", "e.g", "i.e",
    "U", "U.S", "U.K", "E.U", "D", "D.C",
  ]);

  /**
   * Extracts the word token immediately before position `dotIdx` in `text`,
   * walking back through letters and dots to capture multi-dot abbreviations
   * (e.g. "e.g", "U.S").
   */
  function wordBeforeDot(text, dotIdx) {
    let k = dotIdx - 1;
    while (k >= 0 && /[A-Za-z.]/.test(text[k])) k--;
    return text.slice(k + 1, dotIdx);
  }

  /**
   * Scans `text` left-to-right and returns the index of the first genuine
   * sentence-ending punctuation, skipping periods that are part of
   * abbreviations or decimal numbers. Returns -1 if none found.
   */
  function findFirstSentenceBoundary(text) {
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === "?" || ch === "!") return i;
      if (ch === ".") {
        if (/\d/.test(text[i - 1] ?? "") && /\d/.test(text[i + 1] ?? "")) continue;
        if (SENTENCE_ABBR.has(wordBeforeDot(text, i))) continue;
        return i;
      }
    }
    return -1;
  }

  /**
   * Scans `text` left-to-right and returns the index of the last genuine
   * sentence-ending punctuation, skipping periods that are part of
   * abbreviations or decimal numbers. Returns -1 if none found.
   */
  function findLastSentenceBoundary(text) {
    let last = -1;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === "?" || ch === "!") { last = i; continue; }
      if (ch === ".") {
        if (/\d/.test(text[i - 1] ?? "") && /\d/.test(text[i + 1] ?? "")) continue;
        if (SENTENCE_ABBR.has(wordBeforeDot(text, i))) continue;
        last = i;
      }
    }
    return last;
  }

  /**
   * After final char cap: if the cap cut through a word, drop the broken edge.
   * Uses fullText + idx so we can see the character before/after the capped region.
   */
  function trimLeadingBrokenWord(before, fullText, idx) {
    if (!before) return before;
    const firstCh = [...before][0];
    if (firstCh && isCjkScriptChar(firstCh)) return before;
    const bStart = idx - before.length;
    if (bStart <= 0) return before;
    const prevCh = [...fullText.slice(0, bStart)].pop() || "";
    if (!firstCh || !isWordInternalStr(prevCh) || !isWordInternalStr(firstCh)) return before;
    let drop = 0;
    for (const ch of before) {
      if (!isWordInternalStr(ch)) break;
      drop += ch.length;
    }
    return before.slice(drop).trimStart();
  }

  function trimTrailingBrokenWord(after, fullText, idx, selLen) {
    if (!after) return after;
    const pts = [...after];
    const lastCh = pts[pts.length - 1];
    if (lastCh && isCjkScriptChar(lastCh)) return after;
    const aEnd = idx + selLen + after.length;
    if (aEnd >= fullText.length) return after;
    const nextCh = [...fullText.slice(aEnd)][0] || "";
    if (!lastCh || !isWordInternalStr(lastCh) || !isWordInternalStr(nextCh)) return after;
    let k = pts.length - 1;
    while (k >= 0 && isWordInternalStr(pts[k])) k -= 1;
    return pts.slice(0, k + 1).join("").trimEnd();
  }

  /**
   * Walks all text nodes inside `root` in depth-first (document) order — the
   * same order `root.textContent` uses to concatenate them — and returns the
   * exact character offset of `range.startContainer` + `range.startOffset`
   * within that flat string. Returns -1 if the start container is not found
   * (e.g. it is an element node rather than a text node, or lies outside root).
   */
  function getRangeOffsetInRoot(root, range) {
    const target = range.startContainer;
    if (!target || target.nodeType !== Node.TEXT_NODE) return -1;
    let offset = 0;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node === target) return offset + range.startOffset;
      offset += node.textContent.length;
    }
    return -1;
  }

  /**
   * Chromium's window.getSelection() does not expose endpoints inside an open shadow root:
   * anchor/focus/commonAncestorContainer resolve to the shadow host or an outer ancestor, so
   * selections made inside the panel cannot be traced back to .dt-panel-meaning etc. Use
   * ShadowRoot.getSelection() when the shadow tree has an active selection.
   */
  function getActiveSelection() {
    try {
      if (dtShadowRoot && typeof dtShadowRoot.getSelection === "function") {
        const shadowSel = dtShadowRoot.getSelection();
        if (shadowSel && shadowSel.rangeCount > 0 && (shadowSel.toString() || "").length > 0) {
          return shadowSel;
        }
      }
    } catch {
      /* ignore */
    }
    return window.getSelection();
  }

  function getFullContext(selectedText) {
    const sel = getActiveSelection();
    const range = sel && sel.rangeCount > 0 ? sel.getRangeAt(0) : null;
    if (!range) return selectedText;
    const len = selectedText.length;
    const beforeLimit = Math.floor((MAX_LEN - len) / 2);
    const afterLimit = MAX_LEN - len - beforeLimit;
    const root = getContextRootElement(range);
    const fullText = root?.textContent || "";
    let idx = getRangeOffsetInRoot(root, range);
    if (idx < 0) idx = fullText.indexOf(selectedText);
    if (idx < 0) return selectedText;
    let before = fullText.slice(Math.max(0, idx - beforeLimit), idx);
    let after = fullText.slice(idx + len, Math.min(fullText.length, idx + len + afterLimit));
    const beforeTerm = findLastSentenceBoundary(before);
    if (beforeTerm >= 0) before = before.slice(beforeTerm + 1).trimStart();
    before = before.slice(-beforeLimit);
    const afterTerm = findFirstSentenceBoundary(after);
    if (afterTerm >= 0) after = after.slice(0, afterTerm + 1);
    after = after.slice(0, afterLimit);
    before = trimLeadingBrokenWord(before, fullText, idx);
    after = trimTrailingBrokenWord(after, fullText, idx, len);
    return before + selectedText + after;
  }

  function positionDefineButton(rect) {
    if (!defineBtn) return;
    const btnHeight = 36;
    const spacing = 10;
    const spaceAbove = rect.top;
    let top;
    if (spaceAbove >= btnHeight + spacing) {
      top = rect.top - btnHeight - spacing;
    } else {
      top = rect.bottom + spacing;
    }
    const left = rect.left + (rect.width - 120) / 2;
    defineBtn.style.position = "fixed";
    defineBtn.style.top = `${top}px`;
    defineBtn.style.left = `${left}px`;
  }

  function createDefineButton() {
    ensureUiAttached();
    if (defineBtn && defineBtn.isConnected) return defineBtn;
    defineBtn = null;
    const root = getDtShadowRoot();
    if (!root) return null;
    const btn = document.createElement("button");
    btn.setAttribute("data-dt-define-btn", "true");
    btn.textContent = "Define";
    btn.className = "dt-define-btn";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      handleDefineClick();
    });
    root.appendChild(btn);
    defineBtn = btn;
    return btn;
  }

  function showDefineButton(rect) {
    const btn = createDefineButton();
    if (!btn) return;
    positionDefineButton(rect);
    btn.style.display = "block";
  }

  function hideDefineButton() {
    if (defineBtn) defineBtn.style.display = "none";
  }

  function createPanel() {
    ensureUiAttached();
    if (panel && panel.isConnected) return panel;
    panel = null;
    const root = getDtShadowRoot();
    if (!root) return null;
    const wrap = document.createElement("div");
    wrap.setAttribute("data-dt-panel", "true");
    wrap.className = "dt-panel";
    wrap.innerHTML = `
      <div class="dt-panel-header">
        <span class="dt-panel-header-text"></span>
        <button class="dt-panel-close" aria-label="Close">&times;</button>
      </div>
      <div class="dt-panel-divider"></div>
      <div class="dt-panel-content">
        <div class="dt-panel-spinner" style="display:none;"></div>
        <div class="dt-panel-message" style="display:none;"></div>
        <div class="dt-panel-meaning" style="display:none;"></div>
        <div class="dt-panel-divider2" style="display:none;"></div>
        <div class="dt-panel-translation-wrap">
          <select class="dt-panel-lang-select"></select>
          <div class="dt-panel-translation"></div>
          <div class="dt-panel-translation-spinner" style="display:none;"></div>
        </div>
      </div>
    `;
    const headerText = wrap.querySelector(".dt-panel-header-text");
    const closeBtn = wrap.querySelector(".dt-panel-close");
    const content = wrap.querySelector(".dt-panel-content");
    const spinner = wrap.querySelector(".dt-panel-spinner");
    const message = wrap.querySelector(".dt-panel-message");
    const meaningEl = wrap.querySelector(".dt-panel-meaning");
    const divider2 = wrap.querySelector(".dt-panel-divider2");
    const transWrap = wrap.querySelector(".dt-panel-translation-wrap");
    const langSelect = wrap.querySelector(".dt-panel-lang-select");
    const translationEl = wrap.querySelector(".dt-panel-translation");

    const nullOpt = document.createElement("option");
    nullOpt.value = "";
    nullOpt.textContent = "-";
    langSelect.appendChild(nullOpt);
    LANGUAGES.forEach(({ label, value }) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      langSelect.appendChild(opt);
    });

    closeBtn.addEventListener("click", closePanel);
    wrap.addEventListener("mousedown", (e) => e.stopPropagation());

    let lastTouchY = 0;
    wrap.addEventListener("touchstart", (e) => {
      lastTouchY = e.touches[0].clientY;
    }, { passive: true });

    wrap.addEventListener("wheel", (e) => {
      e.preventDefault();
      if (content.contains(e.target) || e.target === content) {
        content.scrollTop += e.deltaY;
      }
    }, { passive: false });

    wrap.addEventListener("touchmove", (e) => {
      e.preventDefault();
      if (content.contains(e.target) || e.target === content) {
        const dy = lastTouchY - e.touches[0].clientY;
        content.scrollTop += dy;
        lastTouchY = e.touches[0].clientY;
      }
    }, { passive: false });

    let headerDrag = wrap.querySelector(".dt-panel-header");
    headerDrag.addEventListener("mousedown", startDrag);

    const edges = ["n", "s", "e", "w", "ne", "nw", "se", "sw"];
    edges.forEach(edge => {
      const el = document.createElement("div");
      el.className = `dt-panel-resize dt-panel-resize-${edge}`;
      el.dataset.edge = edge;
      el.addEventListener("mousedown", (e) => { e.preventDefault(); startResize(e, edge); });
      wrap.appendChild(el);
    });

    langSelect.addEventListener("change", () => handleLanguageChange());

    root.appendChild(wrap);
    panel = wrap;
    resetPanelPosition();
    return wrap;
  }

  function resetPanelPosition() {
    if (!panel || !panel.isConnected) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    panel.style.width = DEFAULT_PANEL_WIDTH + "px";
    panel.style.height = DEFAULT_PANEL_HEIGHT + "px";
    panel.style.left = (vw - DEFAULT_PANEL_WIDTH - 24) + "px";
    panel.style.top = (vh - DEFAULT_PANEL_HEIGHT - 24) + "px";
  }

  function truncateHeaderText(text, maxWidth) {
    const measureEl = document.createElement("span");
    measureEl.className = "dt-panel-header-text";
    measureEl.style.cssText = "visibility:hidden;position:absolute;white-space:nowrap;";
    panel.querySelector(".dt-panel-header").appendChild(measureEl);
    let result = text;
    measureEl.textContent = result;
    while (measureEl.scrollWidth > maxWidth && result.length > 0) {
      result = result.slice(0, -1);
      measureEl.textContent = result + "\u2026";
    }
    measureEl.remove();
    return result.length < text.length ? result + "\u2026" : text;
  }

  function updateHeaderTruncation() {
    const headerText = panel?.querySelector(".dt-panel-header-text");
    if (!headerText) return;
    const fullText = headerText.dataset.fullText || "";
    const closeBtn = panel?.querySelector(".dt-panel-close");
    const padding = 32;
    const closeWidth = closeBtn?.offsetWidth || 40;
    const buffer = 16;
    // Hidden panels report offsetWidth 0; negative maxWidth would truncate the whole string.
    const panelW = panel.offsetWidth || DEFAULT_PANEL_WIDTH;
    const maxWidth = Math.max(panelW - padding - closeWidth - buffer, 48);
    headerText.textContent = truncateHeaderText(fullText, maxWidth);
  }

  function startDrag(e) {
    if (e.target.closest(".dt-panel-close")) return;
    isDragging = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    panelStartX = panel.offsetLeft;
    panelStartY = panel.offsetTop;
    document.addEventListener("mousemove", onDragMove);
    document.addEventListener("mouseup", onDragUp);
    e.preventDefault();
  }

  function onDragMove(e) {
    if (!isDragging) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    let left = panelStartX + dx;
    let top = panelStartY + dy;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    if (left < 0) left = 0;
    if (top < 0) top = 0;
    if (left + panel.offsetWidth > vw) left = vw - panel.offsetWidth;
    if (top + panel.offsetHeight > vh) top = vh - panel.offsetHeight;
    if (top < 0) top = 0;
    panel.style.left = left + "px";
    panel.style.top = top + "px";
  }

  function onDragUp() {
    isDragging = false;
    document.removeEventListener("mousemove", onDragMove);
    document.removeEventListener("mouseup", onDragUp);
  }

  function startResize(e, edge) {
    isResizing = true;
    resizeEdge = edge;
    const startW = panel.offsetWidth;
    const startH = panel.offsetHeight;
    const startX = panel.offsetLeft;
    const startY = panel.offsetTop;
    const startMouseX = e.clientX;
    const startMouseY = e.clientY;

    function onResizeMove(e) {
      if (!isResizing) return;
      const dx = e.clientX - startMouseX;
      const dy = e.clientY - startMouseY;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      let w = startW, h = startH, left = startX, top = startY;
      if (resizeEdge.includes("e")) {
        w = Math.min(Math.max(MIN_PANEL_WIDTH, startW + dx), vw - left);
      }
      if (resizeEdge.includes("w")) {
        w = Math.max(MIN_PANEL_WIDTH, startW - dx);
        left = startX + (startW - w);
        if (left < 0) { left = 0; w = Math.max(MIN_PANEL_WIDTH, startX + startW); }
      }
      if (resizeEdge.includes("s")) {
        h = Math.min(Math.max(MIN_PANEL_HEIGHT, startH + dy), vh - top);
      }
      if (resizeEdge.includes("n")) {
        h = Math.max(MIN_PANEL_HEIGHT, startH - dy);
        top = startY + (startH - h);
        if (top < 0) { top = 0; h = Math.max(MIN_PANEL_HEIGHT, startY + startH); }
      }
      panel.style.width = w + "px";
      panel.style.height = h + "px";
      panel.style.left = left + "px";
      panel.style.top = top + "px";
      updateHeaderTruncation();
    }
    function onResizeUp() {
      isResizing = false;
      document.removeEventListener("mousemove", onResizeMove);
      document.removeEventListener("mouseup", onResizeUp);
    }
    document.addEventListener("mousemove", onResizeMove);
    document.addEventListener("mouseup", onResizeUp);
  }

  function constrainPanelToViewport() {
    if (!panel || !panel.isConnected) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = parseInt(panel.style.left, 10) || 0;
    let top = parseInt(panel.style.top, 10) || 0;
    if (left < 0) left = 0;
    if (top < 0) top = 0;
    if (left + panel.offsetWidth > vw) left = vw - panel.offsetWidth;
    if (top + panel.offsetHeight > vh) top = vh - panel.offsetHeight;
    if (top < 0) top = 0;
    panel.style.left = left + "px";
    panel.style.top = top + "px";
  }

  async function showPanel(selectedText) {
    const created = createPanel();
    if (!created) return false;
    if (!panelActive) resetPanelPosition();
    const headerText = panel.querySelector(".dt-panel-header-text");
    headerText.dataset.fullText = selectedText;
    headerText.textContent = selectedText;
    updateHeaderTruncation();
    panel.querySelector(".dt-panel-spinner").style.display = "none";
    panel.querySelector(".dt-panel-message").style.display = "none";
    panel.querySelector(".dt-panel-meaning").style.display = "none";
    panel.querySelector(".dt-panel-divider2").style.display = "none";
    panel.querySelector(".dt-panel-translation-wrap").style.display = "none";
    const langSelect = panel.querySelector(".dt-panel-lang-select");
    const stored = await getTargetLanguage();
    if (langSelect) langSelect.value = stored || "";
    panel.style.display = "flex";
    panel.style.flexDirection = "column";
    updateHeaderTruncation();
    panelActive = true;
    window.addEventListener("resize", constrainPanelToViewport);
    return true;
  }

  function closePanel() {
    if (pendingRequestId) {
      chrome.runtime.sendMessage({ type: "abortLookup", requestId: pendingRequestId });
      pendingRequestId = null;
    }
    if (panel && panel.isConnected) {
      panel.style.display = "none";
      window.removeEventListener("resize", constrainPanelToViewport);
    }
    panelActive = false;
    cachedMeaning = null;
    cachedTranslation = null;
    cachedFullContext = null;
    lastRequestFingerprint = null;
    window.getSelection()?.removeAllRanges();
  }

  function handleDefineClick() {
    if (defineClickDebounceTimer) return;
    defineClickDebounceTimer = setTimeout(() => { defineClickDebounceTimer = null; }, 500);
    hideDefineButton();
    const sel = window.getSelection();
    const text = sel?.toString()?.trim() || "";
    if (!text) return;
    if (text.length > MAX_LEN) {
      showPanel(text).then((ok) => {
        if (ok) showMessage("Please keep selection within 300 characters");
      });
      return;
    }
    // Snapshot context while the selection is still live; showPanel() + awaits in
    // fetchLookup can collapse the selection before getFullContext would otherwise run.
    const fullContext = getFullContext(text);
    showPanel(text).then((ok) => {
      if (ok) fetchLookup(text, null, undefined, undefined, fullContext);
    });
  }

  function showMessage(msg) {
    const el = panel?.querySelector(".dt-panel-message");
    const transWrap = panel?.querySelector(".dt-panel-translation-wrap");
    const meaningEl = panel?.querySelector(".dt-panel-meaning");
    const divider2 = panel?.querySelector(".dt-panel-divider2");
    if (el) {
      el.textContent = msg;
      el.style.display = "block";
    }
    if (meaningEl) meaningEl.style.display = "none";
    if (divider2) divider2.style.display = "none";
    if (transWrap) transWrap.style.display = "none";
  }

  function showSpinner(show, options) {
    const spinner = panel?.querySelector(".dt-panel-spinner");
    const transSpinner = panel?.querySelector(".dt-panel-translation-spinner");
    const message = panel?.querySelector(".dt-panel-message");
    const meaning = panel?.querySelector(".dt-panel-meaning");
    const transWrap = panel?.querySelector(".dt-panel-translation-wrap");
    const langSelect = panel?.querySelector(".dt-panel-lang-select");
    const translationEl = panel?.querySelector(".dt-panel-translation");
    const keepMeaning = options?.keepMeaning === true;
    if (show) {
      if (keepMeaning) {
        if (spinner) spinner.style.display = "none";
        if (meaning) meaning.style.display = "block";
        if (transWrap) transWrap.style.display = "block";
        if (langSelect) langSelect.style.display = "none";
        if (translationEl) translationEl.style.display = "none";
        if (transSpinner) transSpinner.style.display = "flex";
      } else {
        if (spinner) spinner.style.display = "flex";
        if (message) message.style.display = "none";
        if (meaning) meaning.style.display = "none";
        if (transWrap) transWrap.style.display = "none";
        if (transSpinner) transSpinner.style.display = "none";
      }
    } else {
      if (spinner) spinner.style.display = "none";
      if (transSpinner) transSpinner.style.display = "none";
    }
  }

  function showResult(meaning, translation) {
    const meaningEl = panel?.querySelector(".dt-panel-meaning");
    const transWrap = panel?.querySelector(".dt-panel-translation-wrap");
    const translationEl = panel?.querySelector(".dt-panel-translation");
    const langSelect = panel?.querySelector(".dt-panel-lang-select");
    const transSpinner = panel?.querySelector(".dt-panel-translation-spinner");
    const divider2 = panel?.querySelector(".dt-panel-divider2");
    if (meaningEl) {
      meaningEl.textContent = meaning || "";
      meaningEl.style.display = meaning ? "block" : "none";
    }
    if (divider2) divider2.style.display = (meaning || translation) ? "block" : "none";
    if (transWrap) {
      transWrap.style.display = "block";
      if (langSelect) langSelect.style.display = "block";
      if (translationEl) {
        translationEl.textContent = translation || "";
        translationEl.style.display = "block";
      }
      if (transSpinner) transSpinner.style.display = "none";
    }
    updateHeaderTruncation();
  }

  async function getInstallId() {
    const r = await chrome.storage.local.get("install_id");
    let id = r.install_id;
    if (!id) {
      id = uuid4();
      await chrome.storage.local.set({ install_id: id });
    }
    return id;
  }

  async function getTargetLanguage() {
    const r = await chrome.storage.local.get("target_language");
    return r.target_language || null;
  }

  async function setTargetLanguage(lang) {
    await chrome.storage.local.set({ target_language: lang });
  }

  function handleLanguageChange() {
    const langSelect = panel?.querySelector(".dt-panel-lang-select");
    const translationEl = panel?.querySelector(".dt-panel-translation");
    const lang = langSelect?.value || null;
    const effectiveLang = lang && lang.trim() ? lang : null;
    setTargetLanguage(effectiveLang);
    const headerText = panel?.querySelector(".dt-panel-header-text");
    const selectedText = headerText?.dataset?.fullText || "";
    if (!selectedText) return;
    if (!effectiveLang) {
      if (translationEl) translationEl.textContent = "";
      return;
    }
    if (cachedMeaning) {
      fetchLookup(selectedText, effectiveLang, "translation_only", cachedMeaning, cachedFullContext);
    } else {
      fetchLookup(selectedText, effectiveLang, "meaning_and_translation", undefined, cachedFullContext);
    }
  }

  async function fetchLookup(selectedText, targetLanguage, mode, reuseMeaning, fullContextOverride) {
    const fp = selectedText + (targetLanguage || "") + (mode || "");
    if (fp === lastRequestFingerprint) {
      if (cachedMeaning !== null || cachedTranslation !== null) {
        showResult(cachedMeaning, cachedTranslation);
        return;
      }
      // Same input is already in-flight — don't start another request.
      if (pendingRequestId) return;
      // Cache is empty and no request is running (e.g. prior request failed) — retry.
    }
    lastRequestFingerprint = fp;

    if (pendingRequestId) {
      chrome.runtime.sendMessage({ type: "abortLookup", requestId: pendingRequestId });
      pendingRequestId = null;
    }

    showSpinner(true, { keepMeaning: mode === "translation_only" });
    const installId = await getInstallId();
    const storedLang = await getTargetLanguage();
    const effectiveLang = targetLanguage ?? storedLang;
    const effectiveMode = mode || (effectiveLang ? "meaning_and_translation" : "meaning_only");

    // Prefer caller-provided context: showPanel() toggles display on panel inner elements,
    // which collapses any shadow-DOM selection before this async flow reaches getFullContext.
    const fullContext = fullContextOverride != null
      ? fullContextOverride
      : getFullContext(selectedText);
    // Cache so follow-up lookups for the same selection (e.g. language change) keep the
    // original context even after the live selection is gone.
    cachedFullContext = fullContext;
    const requestId = uuid4();
    const payload = {
      client_request_id: requestId,
      install_id: installId,
      selected_text: selectedText,
      full_context: fullContext.length <= MAX_LEN ? fullContext : null,
      target_language: effectiveLang || null,
      mode: effectiveMode,
      page_url: window.location.origin + window.location.pathname,
      extension_version: getExtensionVersion(),
    };

    pendingRequestId = requestId;
    const apiBase = await getApiBase();

    try {
      const tStart = performance.now();
      const response = await chrome.runtime.sendMessage({
        type: "fetchLookup",
        requestId,
        apiBase,
        payload,
      });
      const totalMs = Math.round(performance.now() - tStart);
      console.log("[DT] Total lookup time (content -> background -> API -> back):", totalMs, "ms");

      if (response.requestId !== pendingRequestId) return;
      pendingRequestId = null;

      if (response.aborted) return;

      if (!response.ok) {
        const data = response.data || {};
        const errMsg = data.error_message || "Something went wrong. Please try again later.";
        if (response.error) {
          showMessage("Unable to connect. Please check your Internet connection and try again.");
        } else {
          showMessage(errMsg);
        }
        showSpinner(false);
        return;
      }

      const data = response.data || {};
      const meaning = data.meaning ?? reuseMeaning ?? null;
      const translation = data.translation ?? null;
      if (meaning) cachedMeaning = meaning;
      cachedTranslation = translation;

      showResult(meaning, translation);
      showSpinner(false);
    } catch (err) {
      if (pendingRequestId === requestId) pendingRequestId = null;
      showMessage("Unable to connect. Please check your Internet connection and try again.");
      showSpinner(false);
    }
  }

  function handleSelection() {
    ensureUiAttached();
    const sel = window.getSelection();
    const text = sel?.toString()?.trim() || "";
    const anchorEl = elementFromSelectionNode(sel?.anchorNode);

    if (!isSupportedUrl() || hasDomExclusions()) {
      hideDefineButton();
      return;
    }

    if (panelActive) {
      if (isDragging || isResizing) return;
      if (shouldIgnoreSelectionForDefineAndLookup(sel, text)) return;
      if (!text) return;
      if (text.length > MAX_LEN) {
        showPanel(text).then((ok) => {
          if (ok) showMessage("Please keep selection within 300 characters");
        });
        return;
      }
      const currentHeaderText = panel?.querySelector(".dt-panel-header-text")?.dataset?.fullText || "";
      if (text === currentHeaderText && (cachedMeaning !== null || cachedTranslation !== null || pendingRequestId !== null)) return;
      // Snapshot context before showPanel hides .dt-panel-meaning etc., which collapses
      // any in-panel shadow-DOM selection and would leave getFullContext with nothing to read.
      const fullContext = getFullContext(text);
      showPanel(text).then((ok) => {
        if (ok) fetchLookup(text, null, undefined, undefined, fullContext);
      });
      return;
    }

    if (!text || shouldIgnoreSelectionForDefineAndLookup(sel, text)) {
      hideDefineButton();
      return;
    }
    if (anchorEl && isPanelElement(anchorEl)) {
      hideDefineButton();
      return;
    }
    try {
      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      if (rect.width > 0 || rect.height > 0) {
        showDefineButton(rect);
      } else {
        hideDefineButton();
      }
    } catch {
      hideDefineButton();
    }
  }

  function handleClick(e) {
    if (eventTouchesDtDefineButton(e) || eventTouchesDtPanel(e)) return;
    if (panelActive && (isDragging || isResizing)) return;
    if (panelActive && eventTouchesDtLangSelect(e)) return;
    if (!panelActive) hideDefineButton();
    if (panelActive && !eventTouchesDtPanel(e)) {
      window.getSelection()?.removeAllRanges();
    }
  }

  function onSelectionEnd() {
    if (selectionDebounceTimer) {
      clearTimeout(selectionDebounceTimer);
      selectionDebounceTimer = null;
    }
    handleSelection();
  }

  document.addEventListener("selectionchange", () => {
    if (isDragging || isResizing) return;
    if (isSelecting) return;
    if (selectionDebounceTimer) clearTimeout(selectionDebounceTimer);
    selectionDebounceTimer = setTimeout(onSelectionEnd, 300);
  });

  document.addEventListener("mousedown", (e) => {
    const onDefineBtn = eventTouchesDtDefineButton(e);
    const onPanel = eventTouchesDtPanel(e);
    if (!onDefineBtn && !onPanel) {
      isSelecting = true;
    } else if (onPanel && panelActive && !isPanelChromeTargetFromEvent(e)) {
      isSelecting = true;
    }
    handleClick(e);
  }, true);

  document.addEventListener("mouseup", () => {
    if (isSelecting) {
      isSelecting = false;
      onSelectionEnd();
    }
  });

  document.addEventListener("touchstart", (e) => {
    const onDefineBtn = eventTouchesDtDefineButton(e);
    const onPanel = eventTouchesDtPanel(e);
    if (!onDefineBtn && !onPanel) {
      isSelecting = true;
    } else if (onPanel && panelActive && !isPanelChromeTargetFromEvent(e)) {
      isSelecting = true;
    }
  }, { passive: true });

  document.addEventListener("touchend", () => {
    if (isSelecting) {
      isSelecting = false;
      onSelectionEnd();
    }
  }, { passive: true });

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg === "tabClosed" || msg === "navigate") closePanel();
  });

  window.addEventListener("beforeunload", () => closePanel());

  patchHistoryForSpaNavigation();
  startDtMountObserver();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => ensureUiAttached(), { once: true });
  } else {
    ensureUiAttached();
  }
})();
