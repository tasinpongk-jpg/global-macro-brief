/* Global Macro Brief — dashboard interactions (vanilla, no deps) */
(function () {
  "use strict";

  var root = document.documentElement;
  function ls(get, key, val) {           // tiny safe-localStorage helper
    try { return get ? localStorage.getItem(key) : (localStorage.setItem(key, val), null); }
    catch (e) { return null; }
  }

  /* ── Theme (persisted) ─────────────────────────────────────────────── */
  var saved = ls(true, "gmb-theme");
  if (saved) root.setAttribute("data-theme", saved);
  var themeBtn = document.getElementById("themeToggle");
  function syncThemeIcon() {
    var dark = root.getAttribute("data-theme") !== "light";
    if (themeBtn) themeBtn.textContent = dark ? "☾" : "☀";
  }
  syncThemeIcon();
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    ls(false, "gmb-theme", next);
    syncThemeIcon();
  });

  /* ── Elements & state ──────────────────────────────────────────────── */
  var tabs   = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  var tabsNav = document.getElementById("tabs");
  var topicStage = document.getElementById("topicStage");
  var assetStage = document.getElementById("assetStage");
  var stage  = document.getElementById("stage");
  var search = document.getElementById("search");
  var searchCount = document.getElementById("searchCount");
  var noResults   = document.getElementById("noResults");
  var noResultsQ  = document.getElementById("noResultsQ");
  var daySelect = document.getElementById("daySelect");

  var DEFAULT_TAB = "Markets";
  var activeTopic = tabs.some(function (t) { return t.dataset.topic === DEFAULT_TAB; })
    ? DEFAULT_TAB : "__all__";
  var query = "";
  var view = "topic";          // "topic" | "asset"
  var pinnedOnly = false;
  var newOnly = false;

  var pins = (function () {
    try { return new Set(JSON.parse(ls(true, "gmb-pins") || "[]")); }
    catch (e) { return new Set(); }
  })();
  function savePins() { ls(false, "gmb-pins", JSON.stringify(Array.prototype.slice.call(pins))); }

  /* ── Predicates ────────────────────────────────────────────────────── */
  function matchesSearch(card) {
    if (!query) return true;
    var hay = card.dataset.search || "";
    return query.split(/\s+/).filter(Boolean).every(function (t) { return hay.indexOf(t) !== -1; });
  }
  function cardInstruments(card) {
    return (card.dataset.instruments || "").split(",").filter(Boolean);
  }
  function matchesPinned(card) {
    if (!pinnedOnly) return true;
    return cardInstruments(card).some(function (s) { return pins.has(s); });
  }
  function isNew(card) { return card.classList.contains("is-new"); }
  function matchesNew(card) { return !newOnly || isNew(card); }
  function cardVisible(card) {
    return matchesSearch(card) && matchesPinned(card) && matchesNew(card);
  }

  /* ── New since last visit ──────────────────────────────────────────── */
  function markNew() {
    var dayKey = daySelect ? daySelect.value.replace(".html", "") : "x";
    var lvKey = "gmb-lv-" + dayKey;
    var last = ls(true, lvKey);
    var lastT = last ? Date.parse(last) : NaN;
    var count = 0;
    Array.prototype.forEach.call(topicStage ? topicStage.querySelectorAll(".card") : [], function (c) {
      var ts = Date.parse(c.dataset.ts || "");
      if (!isNaN(lastT) && !isNaN(ts) && ts > lastT) { c.classList.add("is-new"); count++; }
    });
    var chip = document.getElementById("newToggle");
    if (chip && count > 0) {
      chip.hidden = false;
      document.getElementById("newCount").textContent = count;
      chip.addEventListener("click", function () {
        newOnly = !newOnly;
        chip.setAttribute("aria-pressed", newOnly ? "true" : "false");
        chip.classList.toggle("is-active", newOnly);
        apply();
      });
    }
    // Update reference to now AFTER marking, so the next visit is the baseline.
    try { localStorage.setItem(lvKey, new Date().toISOString()); } catch (e) {}
  }

  /* ── By-asset view (built once from the topic cards) ───────────────── */
  function buildAssetView() {
    if (!assetStage || !topicStage) return;
    assetStage.innerHTML = "";
    var byAsset = {};                 // sym -> [cards]
    var none = [];
    Array.prototype.forEach.call(topicStage.querySelectorAll(".card"), function (card) {
      var syms = cardInstruments(card);
      if (!syms.length) { none.push(card); return; }
      syms.forEach(function (s) { (byAsset[s] = byAsset[s] || []).push(card); });
    });
    var syms = Object.keys(byAsset).sort(function (a, b) {
      var pa = pins.has(a) ? 0 : 1, pb = pins.has(b) ? 0 : 1;   // pinned float to top
      if (pa !== pb) return pa - pb;
      return byAsset[b].length - byAsset[a].length;             // then by coverage
    });
    syms.forEach(function (s) { assetStage.appendChild(assetSection(s, byAsset[s])); });
    if (none.length) assetStage.appendChild(assetSection("Unclassified", none, true));
  }
  function assetSection(sym, cards, plain) {
    var sec = document.createElement("section");
    sec.className = "asset-pane";
    sec.dataset.asset = sym;
    var h = document.createElement("h2");
    h.className = "pane-title";
    h.innerHTML = (plain ? "" : (pins.has(sym) ? "★ " : "")) +
      '<span class="asset-name">' + sym + "</span> <span>" + cards.length + "</span>";
    sec.appendChild(h);
    var wrap = document.createElement("div");
    wrap.className = "cards";
    cards.forEach(function (c) {
      var clone = c.cloneNode(true);
      clone.removeAttribute("id");                 // avoid duplicate ids
      clone.classList.remove("lead");
      wrap.appendChild(clone);
    });
    sec.appendChild(wrap);
    return sec;
  }

  /* ── Apply all filters to the active view ──────────────────────────── */
  function apply() {
    var container = view === "asset" ? assetStage : topicStage;
    var searching = !!query;
    var matches = 0;

    Array.prototype.forEach.call(container.querySelectorAll(".card"), function (c) {
      var ok = cardVisible(c);
      c.style.display = ok ? "" : "none";
      if (ok) matches++;
    });

    if (view === "topic") {
      var all = activeTopic === "__all__" || searching || pinnedOnly || newOnly;
      Array.prototype.forEach.call(topicStage.querySelectorAll(".topic-pane"), function (p) {
        var hasVisible = p.querySelector('.card:not([style*="display: none"])');
        var topicShown = all || p.dataset.topic === activeTopic;
        p.classList.toggle("hidden", !(topicShown && hasVisible));
        var title = p.querySelector(".pane-title");
        if (title) title.style.display = (all ? "" : "none");
      });
      tabs.forEach(function (t) {
        t.classList.toggle("is-active", !searching && !pinnedOnly && !newOnly && t.dataset.topic === activeTopic);
      });
    } else {
      Array.prototype.forEach.call(assetStage.querySelectorAll(".asset-pane"), function (p) {
        p.classList.toggle("hidden", !p.querySelector('.card:not([style*="display: none"])'));
      });
    }

    if (searchCount) searchCount.textContent = searching ? matches + " hit" + (matches === 1 ? "" : "s") : "";
    if (noResults) {
      noResults.hidden = !(matches === 0 && (searching || pinnedOnly || newOnly));
      if (noResultsQ) noResultsQ.textContent = query || (pinnedOnly ? "pinned assets" : "new stories");
    }
    if (stage) stage.scrollTop = 0;
  }

  /* ── View toggle (topic / asset) ───────────────────────────────────── */
  function setView(v) {
    view = v;
    if (v === "asset" && assetStage.children.length === 0) buildAssetView();
    if (topicStage) topicStage.hidden = v === "asset";
    if (assetStage) assetStage.hidden = v !== "asset";
    if (tabsNav) tabsNav.style.display = v === "asset" ? "none" : "";
    document.querySelectorAll("#viewSeg .seg-btn").forEach(function (b) {
      b.classList.toggle("is-active", b.dataset.view === v);
    });
    apply();
  }
  document.querySelectorAll("#viewSeg .seg-btn").forEach(function (b) {
    b.addEventListener("click", function () { setView(b.dataset.view); });
  });

  /* ── Pin filter ────────────────────────────────────────────────────── */
  var pinFilter = document.getElementById("pinFilter");
  if (pinFilter) pinFilter.addEventListener("click", function () {
    pinnedOnly = !pinnedOnly;
    pinFilter.setAttribute("aria-pressed", pinnedOnly ? "true" : "false");
    pinFilter.classList.toggle("is-active", pinnedOnly);
    apply();
  });

  /* ── Tabs ──────────────────────────────────────────────────────────── */
  tabs.forEach(function (t) {
    t.addEventListener("click", function () {
      activeTopic = t.dataset.topic;
      if (search && search.value) { search.value = ""; query = ""; }
      pinnedOnly = false; newOnly = false;
      if (pinFilter) pinFilter.classList.remove("is-active");
      apply();
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (/input|select|textarea/i.test(e.target.tagName || "")) return;
    if (query || view !== "topic") return;
    var idx = tabs.findIndex(function (t) { return t.dataset.topic === activeTopic; });
    if (idx < 0) idx = 0;
    idx += e.key === "ArrowRight" ? 1 : -1;
    if (idx < 0) idx = tabs.length - 1;
    if (idx >= tabs.length) idx = 0;
    activeTopic = tabs[idx].dataset.topic;
    tabs[idx].scrollIntoView({ inline: "center", block: "nearest" });
    apply();
  });

  /* ── Search ────────────────────────────────────────────────────────── */
  if (search) {
    search.addEventListener("input", function () {
      query = search.value.trim().toLowerCase();
      apply();
    });
    search.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { search.value = ""; query = ""; search.blur(); apply(); }
    });
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && !/input|select|textarea/i.test(e.target.tagName || "")) {
      e.preventDefault();
      if (search) search.focus();
    }
  });

  /* ── Delegated clicks: expand cards + pin tickers ──────────────────── */
  document.addEventListener("click", function (e) {
    var sym = e.target.closest(".sym");
    if (sym) {                                   // pin / unpin an asset
      e.stopPropagation();
      var s = sym.dataset.sym;
      if (pins.has(s)) pins.delete(s); else pins.add(s);
      savePins();
      document.querySelectorAll('.sym[data-sym="' + s + '"]').forEach(function (b) {
        b.classList.toggle("pinned", pins.has(s));
      });
      if (assetStage) { assetStage.innerHTML = ""; if (view === "asset") buildAssetView(); }
      apply();
      return;
    }
    var head = e.target.closest(".card-head");
    if (head) {                                  // expand / collapse
      var card = head.closest(".card");
      var open = card.classList.toggle("open");
      head.setAttribute("aria-expanded", open ? "true" : "false");
    }
  });

  /* ── Expand / collapse all (visible) ───────────────────────────────── */
  var toggleAll = document.getElementById("toggleAll");
  if (toggleAll) toggleAll.addEventListener("click", function () {
    var expand = toggleAll.getAttribute("aria-pressed") !== "true";
    var container = view === "asset" ? assetStage : topicStage;
    Array.prototype.forEach.call(container.querySelectorAll(".card"), function (c) {
      if (c.style.display === "none") return;
      c.classList.toggle("open", expand);
      var h = c.querySelector(".card-head");
      if (h) h.setAttribute("aria-expanded", expand ? "true" : "false");
    });
    toggleAll.setAttribute("aria-pressed", expand ? "true" : "false");
    toggleAll.textContent = expand ? "Collapse all" : "Expand all";
  });

  /* ── TL;DR jump to a story ─────────────────────────────────────────── */
  document.querySelectorAll(".tldr-item").forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      var cid = a.dataset.cid;
      if (search && search.value) { search.value = ""; query = ""; }
      pinnedOnly = false; newOnly = false; activeTopic = "__all__";
      if (view !== "topic") setView("topic"); else apply();
      var card = document.getElementById(cid);
      if (card) {
        card.classList.add("open");
        var h = card.querySelector(".card-head");
        if (h) h.setAttribute("aria-expanded", "true");
        setTimeout(function () { card.scrollIntoView({ behavior: "smooth", block: "center" }); }, 30);
      }
    });
  });

  /* ── Day navigation ────────────────────────────────────────────────── */
  if (daySelect) daySelect.addEventListener("change", function () {
    if (daySelect.value) window.location.href = daySelect.value;
  });

  /* ── Init ──────────────────────────────────────────────────────────── */
  // Reflect any already-pinned assets on first paint.
  pins.forEach(function (s) {
    document.querySelectorAll('.sym[data-sym="' + s + '"]').forEach(function (b) {
      b.classList.add("pinned");
    });
  });
  markNew();
  apply();
})();
