/* Global Macro Brief — dashboard interactions (vanilla, no deps) */
(function () {
  "use strict";

  /* ── Theme (persisted) ─────────────────────────────────────────────── */
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem("gmb-theme"); } catch (e) {}
  if (saved) root.setAttribute("data-theme", saved);

  var themeBtn = document.getElementById("themeToggle");
  function syncThemeIcon() {
    var dark = root.getAttribute("data-theme") !== "light";
    if (themeBtn) themeBtn.textContent = dark ? "☾" : "☀";
  }
  syncThemeIcon();
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("gmb-theme", next); } catch (e) {}
      syncThemeIcon();
    });
  }

  /* ── Tab filtering ─────────────────────────────────────────────────── */
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  var panes = Array.prototype.slice.call(document.querySelectorAll(".topic-pane"));
  var stage = document.getElementById("stage");

  function activate(topic) {
    tabs.forEach(function (t) {
      t.classList.toggle("is-active", t.dataset.topic === topic);
    });
    var all = topic === "__all__";
    panes.forEach(function (p) {
      var show = all || p.dataset.topic === topic;
      p.classList.toggle("hidden", !show);
      // hide pane titles in the "All" view for a denser scan
      var title = p.querySelector(".pane-title");
      if (title) title.style.display = all ? "" : "none";
    });
    if (stage) stage.scrollTop = 0;
    try { history.replaceState(null, "", "#" + topic); } catch (e) {}
  }

  tabs.forEach(function (t) {
    t.addEventListener("click", function () { activate(t.dataset.topic); });
  });

  // keyboard: ←/→ to move between tabs
  document.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (/input|select|textarea/i.test((e.target.tagName || ""))) return;
    var idx = tabs.findIndex(function (t) { return t.classList.contains("is-active"); });
    if (idx < 0) return;
    idx += e.key === "ArrowRight" ? 1 : -1;
    if (idx < 0) idx = tabs.length - 1;
    if (idx >= tabs.length) idx = 0;
    activate(tabs[idx].dataset.topic);
    tabs[idx].scrollIntoView({ inline: "center", block: "nearest" });
  });

  // restore tab from hash if present
  var hash = (location.hash || "").replace("#", "");
  if (hash && tabs.some(function (t) { return t.dataset.topic === hash; })) activate(hash);
  else activate("__all__");

  /* ── Card expand / collapse ────────────────────────────────────────── */
  document.querySelectorAll(".card-head").forEach(function (head) {
    head.addEventListener("click", function () {
      var card = head.closest(".card");
      var open = card.classList.toggle("open");
      head.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });

  /* ── Day navigation ────────────────────────────────────────────────── */
  var daySelect = document.getElementById("daySelect");
  if (daySelect) {
    daySelect.addEventListener("change", function () {
      if (daySelect.value) window.location.href = daySelect.value;
    });
  }
})();
