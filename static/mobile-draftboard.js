/* Mobile draft-board enhancements (≤767px): tap action sheet + filter drawer.
   Reuses the page's existing globals (toggleStar, pinPoke, filterBoard,
   clearFilters, _starred, _pinned, _typeColors). Desktop is untouched. */
(function () {
  "use strict";
  var MOBILE = window.matchMedia("(max-width: 767px)");
  var TOUCH = window.matchMedia("(hover: none)");
  function isMobile() { return MOBILE.matches; }

  // ── shared overlay + body-scroll lock ──
  var _open = null; // 'sheet' | 'drawer' | null
  function lockBody(on) { document.body.style.overflow = on ? "hidden" : ""; }

  // ── stat-bar palette (matches team-page Unit Matrix) ──
  var STAT = [
    ["HP", "hp", "#ef4444"], ["ATK", "atk", "#f97316"], ["DEF", "def", "#3b82f6"],
    ["SPA", "spa", "#8b5cf6"], ["SPD", "spd", "#22c55e"], ["SPE", "spe", "#eab308"]
  ];

  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }

  // ── ACTION SHEET ──
  var sheet, sheetOverlay;
  function buildSheet() {
    sheetOverlay = document.createElement("div");
    sheetOverlay.className = "mdb-overlay";
    sheetOverlay.addEventListener("click", closeSheet);
    sheet = document.createElement("div");
    sheet.className = "mdb-sheet";
    sheet.addEventListener("click", function (e) { e.stopPropagation(); });
    document.body.appendChild(sheetOverlay);
    document.body.appendChild(sheet);
  }

  function speedTiers(base) {
    base = parseInt(base, 10) || 0;
    var ev0 = 2 * base + 36, ev252 = 2 * base + 99, ev252p = Math.floor(ev252 * 1.1);
    return { ev0: ev0, ev252: ev252, ev252p: ev252p };
  }

  function openSheet(el) {
    if (!sheet) buildSheet();
    var d = el.dataset;
    var name = (el.querySelector(".poke-name") || {}).textContent || d.name || "";
    var sprite = (el.querySelector(".poke-orb img") || {}).src || "";
    var types = [d.type1, d.type2].filter(function (t) { return t; });
    var tips = window._typeColors || {};
    var typeChips = types.map(function (t) {
      var c = tips[t] || "#6b7280";
      return '<span class="mdb-type" style="background:' + c + '">' + esc(t.toUpperCase()) + "</span>";
    }).join("");
    var bars = STAT.map(function (s) {
      var v = parseInt(d[s[1]], 10) || 0;
      var pct = Math.min(100, v / 180 * 100);
      return '<div class="mdb-stat"><span class="mdb-stat-l">' + s[0] + "</span>" +
        '<span class="mdb-stat-track"><i style="width:' + pct + "%;background:" + s[2] +
        ";box-shadow:0 0 6px " + s[2] + '80"></i></span>' +
        '<span class="mdb-stat-v" style="color:' + s[2] + '">' + v + "</span></div>";
    }).join("");
    var sp = speedTiers(d.spe);
    var starred = window._starred && window._starred.has && window._starred.has(d.name);
    var pinned = window._pinned && window._pinned.indexOf && window._pinned.indexOf(d.name) !== -1;
    sheet.innerHTML =
      '<div class="mdb-grab"></div>' +
      '<div class="mdb-sheet-head">' +
        '<span class="mdb-sheet-sprite"><img src="' + esc(sprite) + '" alt=""></span>' +
        '<div class="mdb-sheet-id"><div class="mdb-sheet-name">' + esc(name) + "</div>" +
          '<div class="mdb-sheet-types">' + typeChips + "</div></div>" +
        '<div class="mdb-sheet-cost"><span class="pt">' + (parseInt(d.pts, 10) || 0) + "PT</span>" +
          '<span class="bst">BST ' + (parseInt(d.bst, 10) || 0) + "</span></div>" +
      "</div>" +
      '<div class="mdb-stats">' + bars + "</div>" +
      '<div class="mdb-speed">SPE @ 252+ <b>' + sp.ev252p + "</b> · @ 252 " + sp.ev252 + " · @ 0 " + sp.ev0 + "</div>" +
      '<div class="mdb-actions">' +
        '<button class="mdb-btn star' + (starred ? " on" : "") + '" data-act="star">★ STAR</button>' +
        '<button class="mdb-btn cmp' + (pinned ? " on" : "") + '" data-act="pin">' + (pinned ? "REMOVE" : "⊕ COMPARE") + "</button>" +
        '<a class="mdb-btn dex" href="/pokedex">DEX →</a>' +
      "</div>";
    // wire STAR / COMPARE to the page's existing handlers (keeps state in sync)
    sheet.querySelector('[data-act="star"]').addEventListener("click", function (e) {
      if (window.toggleStar) window.toggleStar(e, d.name);
      closeSheet();
    });
    sheet.querySelector('[data-act="pin"]').addEventListener("click", function (e) {
      if (window.pinPoke) window.pinPoke(e, d.name);
      closeSheet();
    });
    sheetOverlay.classList.add("open");
    sheet.classList.add("open");
    lockBody(true);
    _open = "sheet";
  }
  function closeSheet() {
    if (sheet) sheet.classList.remove("open");
    if (sheetOverlay) sheetOverlay.classList.remove("open");
    lockBody(false);
    _open = null;
  }

  // ── tap a tile → open the sheet (unless the tap hit an interactive child) ──
  document.addEventListener("click", function (e) {
    if (!isMobile()) return;
    var poke = e.target.closest(".board-poke");
    if (!poke) return;
    if (e.target.closest("button, a, input, .star-btn, .pin-btn, .edit-pts-btn")) return;
    openSheet(poke);
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && _open) { closeSheet(); if (window._mdb) window._mdb.closeDrawer && window._mdb.closeDrawer(); } });

  window._mdb = { openSheet: openSheet, closeSheet: closeSheet, isMobile: isMobile };
})();
