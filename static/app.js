/* Global Macro Brief — dashboard interactions (vanilla, no deps) */
(function () {
  "use strict";

  var root = document.documentElement;

  /* ── Theme (persisted) ─────────────────────────────────────────────── */
  try {
    var saved = localStorage.getItem("gmb-theme");
    if (saved) root.setAttribute("data-theme", saved);
  } catch (e) {}
  var themeBtn = document.getElementById("themeToggle");
  function syncThemeIcon() {
    var dark = root.getAttribute("data-theme") !== "light";
    if (themeBtn) themeBtn.textContent = dark ? "☾" : "☀";
  }
  syncThemeIcon();
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("gmb-theme", next); } catch (e) {}
    syncThemeIcon();
  });

  /* ── Elements ──────────────────────────────────────────────────────── */
  var tabs   = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  var panes  = Array.prototype.slice.call(document.querySelectorAll(".topic-pane"));
  var cards  = Array.prototype.slice.call(document.querySelectorAll(".card"));
  var stage  = document.getElementById("stage");
  var search = document.getElementById("search");
  var searchCount = document.getElementById("searchCount");
  var noResults   = document.getElementById("noResults");
  var noResultsQ  = document.getElementById("noResultsQ");

  var DEFAULT_TAB = "Markets";   // open on Markets when present
  var activeTopic = tabs.some(function (t) { return t.dataset.topic === DEFAULT_TAB; })
    ? DEFAULT_TAB : "__all__";
  var query = "";

  /* ── Combined view: search overrides tab filter ────────────────────── */
  function apply() {
    var terms = query.split(/\s+/).filter(Boolean);
    var searching = terms.length > 0;
    var matches = 0;

    if (searching) {
      // Search across ALL categories; show only matching cards.
      cards.forEach(function (c) {
        var hay = c.dataset.search || "";
        var ok = terms.every(function (t) { return hay.indexOf(t) !== -1; });
        c.style.display = ok ? "" : "none";
        if (ok) matches++;
      });
      panes.forEach(function (p) {
        var any = p.querySelector('.card:not([style*="display: none"])');
        p.classList.toggle("hidden", !any);
        var title = p.querySelector(".pane-title");
        if (title) title.style.display = "";  // show category labels in results
      });
      tabs.forEach(function (t) { t.classList.remove("is-active"); });
    } else {
      // Tab filtering; all cards visible within shown panes.
      cards.forEach(function (c) { c.style.display = ""; });
      var all = activeTopic === "__all__";
      panes.forEach(function (p) {
        var show = all || p.dataset.topic === activeTopic;
        p.classList.toggle("hidden", !show);
        var title = p.querySelector(".pane-title");
        if (title) title.style.display = all ? "" : "none";
      });
      tabs.forEach(function (t) {
        t.classList.toggle("is-active", t.dataset.topic === activeTopic);
      });
    }

    if (searchCount) searchCount.textContent = searching ? matches + " hit" + (matches === 1 ? "" : "s") : "";
    if (noResults) {
      noResults.hidden = !(searching && matches === 0);
      if (noResultsQ) noResultsQ.textContent = query;
    }
    if (stage) stage.scrollTop = 0;
  }

  /* ── Tabs ──────────────────────────────────────────────────────────── */
  tabs.forEach(function (t) {
    t.addEventListener("click", function () {
      activeTopic = t.dataset.topic;
      if (search && search.value) { search.value = ""; query = ""; }
      apply();
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (/input|select|textarea/i.test(e.target.tagName || "")) return;
    if (query) return;  // arrows are for tab nav only when not searching
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
  // "/" focuses search from anywhere
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && !/input|select|textarea/i.test(e.target.tagName || "")) {
      e.preventDefault();
      if (search) search.focus();
    }
  });

  /* ── Card expand / collapse ────────────────────────────────────────── */
  document.querySelectorAll(".card-head").forEach(function (head) {
    head.addEventListener("click", function () {
      var card = head.closest(".card");
      var open = card.classList.toggle("open");
      head.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });

  /* ── Expand / collapse all (visible) ───────────────────────────────── */
  var toggleAll = document.getElementById("toggleAll");
  if (toggleAll) {
    toggleAll.addEventListener("click", function () {
      var expand = toggleAll.getAttribute("aria-pressed") !== "true";
      cards.forEach(function (c) {
        if (c.style.display === "none") return;
        c.classList.toggle("open", expand);
        var h = c.querySelector(".card-head");
        if (h) h.setAttribute("aria-expanded", expand ? "true" : "false");
      });
      toggleAll.setAttribute("aria-pressed", expand ? "true" : "false");
      toggleAll.textContent = expand ? "Collapse all" : "Expand all";
    });
  }

  /* ── Day navigation ────────────────────────────────────────────────── */
  var daySelect = document.getElementById("daySelect");
  if (daySelect) daySelect.addEventListener("change", function () {
    if (daySelect.value) window.location.href = daySelect.value;
  });

  apply();
})();
