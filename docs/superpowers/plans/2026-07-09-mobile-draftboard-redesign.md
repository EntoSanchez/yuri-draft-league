# Mobile Draft Board Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/draftboard` page usable on phones (≤767px): replace the ~1,500px sideways scroll with a vertical stacked board, add a tap action sheet for per-mon stats/actions, and a filter drawer — all reusing existing JS, desktop pixel-identical.

**Architecture:** Purely additive. A new `static/mobile-draftboard.js` builds the action sheet + filter drawer DOM once and wires them to the page's EXISTING globals/handlers (`toggleStar`, `pinPoke`, `filterBoard`, `clearFilters`, `_starred`, `_pinned`, `_typeColors`). New CSS lives inside `@media (max-width: 767px)` in `static/mobile.css`. `draftboard.html` gets one `<script>` include + a funnel button. All mobile behavior gates on `matchMedia('(max-width: 767px)')`.

**Tech Stack:** Jinja2 template, vanilla JS (no framework), CSS custom properties. No build step. No Python changes. No pytest (client-side; verified by rendering + DevTools).

Design handoff: `C:/Users/zcs55/Downloads/mobile_ux_z10/design_handoff_mobile_draftboard/README.md` (mocks in `Mobile Redesign.dc.html`, sections `#3a`/`#3b`/`#3c`). **The handoff files are design references, NOT code to copy — recreate in the codebase.**

## Global Constraints

- **Desktop (≥768px) MUST be pixel-identical** before/after. All CSS inside `@media (max-width: 767px)`; all JS behavior gated on `matchMedia('(max-width: 767px)')` (and `(hover: none)` for tap-vs-tooltip).
- **Reuse, do NOT rewrite** the existing JS. Exact functions in `templates/draftboard.html`: `toggleStar(e, name)` (~1442), `setStarFilter()` (~1459), `setPool(pool)` (~1466), `clearFilters()` (~1475), `filterBoard()` (~1494), `buildAbilityList()` (~1588), `_typeColors` map (~1621), `pinPoke(e, name)` (~1808), `updateCompareTray()` (~1821), `openCompare()` (~1889), `_showStatTip(poke, e)` (~2045), and the document `mouseover` tooltip binding (~2124). State globals: `_starred` (Set + localStorage), `_pinned` (Array, `MAX_COMPARE=4`).
- **No new localStorage keys.** Star/compare persistence already exists; the sheet's STAR/COMPARE buttons must call the same handlers so `_starred`/`_pinned`/tray/localStorage stay in sync.
- **Colors/fonts: use site CSS vars, not mock hexes.** `--ink`/`--panel`/`--panel-2`, `--hairline`/`--hairline-2`, `--cyan`/`--magenta`/`--amber`/`--lime`/`--red`, `--text`/`--text-mute`/`--text-dim`, `--font-display`/`--font-body`/`--font-mono`. Sharp corners (0–2px radius) everywhere except bottom sheets (≤10px top radius OK).
- **Stat-bar palette** (action sheet, matches team-page Unit Matrix): HP `#ef4444`, ATK `#f97316`, DEF `#3b82f6`, SPA `#8b5cf6`, SPD `#22c55e`, SPE `#eab308`. Fill = `value/180` capped at 100%.
- **Speed tiers** (L100, IV31, from `data-spe` = base): `ev0 = 2·B + 36`, `ev252 = 2·B + 99`, `ev252plus = floor((2·B + 99) × 1.1)`.
- **Tap targets ≥44px; input text ≥16px** (no iOS focus-zoom). **76px tab-bar clearance** + `env(safe-area-inset-bottom)` on anything docked at the bottom.
- **Branch:** `feat/mobile-draftboard`. Do NOT work on `main`. Never `git add -A` (embedded `damage-calc/` + DBs); add explicit paths.
- **Build marker:** bump `console.log("YDL build: ...")` in `templates/base.html` at the end (current is `ai-commentary-retry-v59` → use `mobile-draftboard-v60`).

### Verification method (no pytest for client-side)

Each task ends with a **render + inspect** check, not a unit test:
- **Render check:** boot the app against a temp DB and GET `/draftboard`, assert 200 + the new markup/CSS/JS is present (a Python one-liner shown per task).
- **Manual check:** open `/draftboard` in the browser at DevTools width ≤767px (and ≥768px to confirm desktop unchanged). The task lists exactly what to look for.
- **The full pytest suite must stay green** (`./.venv/Scripts/python.exe -m pytest -q` → currently 114) — this catches any template-compile break.

### `.board-poke` data attributes (available on every tile — the action sheet reads these)

`data-name` (lowercased), `data-status` (`available`/`drafted`/`banned`), `data-pool`, `data-abilities` (pipe-sep, lower), `data-moves` (pipe-sep), `data-type1`, `data-type2` (lower), `data-hp`, `data-atk`, `data-def`, `data-spa`, `data-spd`, `data-spe`, `data-bst`, `data-pts`, `data-tier`. Sprite: `.poke-orb img`. Display name: `.poke-name` text. Drafted team badge: `.board-badge`.

---

## Task 1: Vertical board CSS (3a)

**Files:**
- Modify: `static/mobile.css` — extend the file (append a new `@media (max-width: 767px)` block for the draft board).

**Interfaces:**
- Consumes: existing draftboard DOM classes `.dbl-cols`, `.board-col[data-pts]`, `.board-col-body`, `.board-poke`, `.dbl-band`, `.poke-orb`, `.board-badge`, `.star-btn`, `.pin-btn`.
- Produces: on phones, tiers stack vertically; each `.board-col` is full-width with a sticky point-band header; `.board-col-body` becomes a 2-up tile grid; star/pin markers are always visible (not hover-gated). No JS in this task.

Note: the EXISTING mobile block in `templates/draftboard.html` (~line 470) sets `.board-col { width: 150px }` and horizontal scroll. This task's rules live in `mobile.css` which loads AFTER the page's `<style>`, so `!important` on the width override wins. We do NOT edit the page's `<style>` block here.

- [ ] **Step 1: Append the vertical-board CSS to `static/mobile.css`**

Add at the END of `static/mobile.css`:

```css
/* ═══════════════════════════════════════════════════════════════
   DRAFT BOARD (/draftboard) — phone vertical layout (3a)
   Stacks tiers vertically; each point tier gets a sticky band header
   and a 2-up tile grid. Desktop (≥768px) is untouched.
   ═══════════════════════════════════════════════════════════════ */
@media (max-width: 767px) {
  /* Stack the tier columns vertically instead of a sideways flex row */
  .dbl-cols { flex-direction: column !important; gap: 0 !important; }
  .board-col { width: 100% !important; }

  /* Per-tier sticky band header (replaces the sideways column headers).
     Sticks under the site nav; ~52px is the mobile #main-nav height. */
  .board-col-header {
    position: sticky; top: 52px; z-index: 20;
    display: flex; align-items: center; gap: 10px;
    padding: 8px 16px;
    background: color-mix(in srgb, var(--ink) 92%, transparent);
    -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--hairline);
  }
  .board-col-header .col-label { font-family: var(--font-display); font-weight: 700; font-size: 15px; color: var(--cyan); }
  .board-col-header .col-count { font-family: var(--font-mono); font-size: 9px; letter-spacing: .12em; color: var(--text-dim); }

  /* 2-up tile grid */
  .board-col-body {
    display: grid !important; grid-template-columns: 1fr 1fr; gap: 8px;
    padding: 6px 16px 12px;
  }

  /* Tile */
  .board-poke {
    min-height: 44px; align-items: center; gap: 8px;
    padding: 8px 9px; border: 1px solid var(--hairline);
    background: var(--panel); position: relative;
    border-bottom: 1px solid var(--hairline);  /* override the desktop last-child rule */
  }
  .board-poke .poke-orb img { width: 32px; height: 32px; image-rendering: pixelated; }
  .board-poke .poke-name { font-size: 11px; font-weight: 700; }
  .drafted-poke { opacity: 0.42; }

  /* Star / pin markers always visible on touch (desktop gates them on hover) */
  .board-poke .star-btn, .board-poke .pin-btn { opacity: 1 !important; }
}
```

- [ ] **Step 2: Render check — CSS is served and page renders**

Run:
```bash
./.venv/Scripts/python.exe -c "
import os,tempfile; os.environ['DATABASE']=os.path.join(tempfile.mkdtemp(),'t.db')
import importlib.util; s=importlib.util.spec_from_file_location('app','app.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
c=m.app.test_client(); r=c.get('/draftboard'); css=c.get('/static/mobile.css').get_data(as_text=True)
print('draftboard', r.status_code, '| mobile.css has vertical rule:', 'DRAFT BOARD (/draftboard)' in css)
"
```
Expected: `draftboard 200 | mobile.css has vertical rule: True`

- [ ] **Step 3: Manual check (DevTools ≤767px)**

Open `/draftboard`, set width to 390px. Confirm: no horizontal page scroll; point tiers stacked vertically; each tier has a sticky header showing its point value + count; two tiles per row ≥44px tall; star/pin icons visible on tiles. Then set width to 1000px and confirm the desktop board is unchanged (sideways columns).

- [ ] **Step 4: Full suite (catch template break)**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: `114 passed`.

- [ ] **Step 5: Commit**

```bash
git add static/mobile.css
git commit -m "feat: mobile draft board vertical layout (3a)"
```

---

## Task 2: Mon action sheet (3b)

**Files:**
- Create: `static/mobile-draftboard.js`
- Modify: `templates/draftboard.html` — add one `<script src>` include at the very bottom (before `{% endblock %}` / after the existing scripts).
- Modify: `static/mobile.css` — append action-sheet CSS.

**Interfaces:**
- Consumes: `.board-poke` data attributes; existing globals `toggleStar(e, name)`, `pinPoke(e, name)`, `_starred` (Set), `_pinned` (Array), `_typeColors` (map). Reads `matchMedia`.
- Produces: `window._mdb` namespace with `openSheet(pokeEl)` / `closeSheet()`. Tapping a `.board-poke` on a phone opens the sheet. STAR/COMPARE buttons call the existing handlers. Sets a body-scroll lock while open.

- [ ] **Step 1: Create `static/mobile-draftboard.js` with the action sheet**

Create `static/mobile-draftboard.js`:

```javascript
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
```

- [ ] **Step 2: Add the include to `templates/draftboard.html`**

Find the LAST `</script>` before `{% endblock %}` in `templates/draftboard.html` and add immediately after it:

```html
<script src="{{ url_for('static', filename='mobile-draftboard.js', v='60') }}"></script>
```

- [ ] **Step 3: Append action-sheet CSS to `static/mobile.css`**

Add at the END of `static/mobile.css`:

```css
/* Draft-board mobile: action sheet (3b) + drawer (3c) shared chrome */
.mdb-overlay { display: none; position: fixed; inset: 0; z-index: 9000; background: rgba(0,0,0,.62); }
.mdb-overlay.open { display: block; }
.mdb-sheet, .mdb-drawer {
  display: none; position: fixed; left: 0; right: 0; bottom: 0; z-index: 9001;
  background: var(--panel-2); border-top: 1px solid var(--cyan-dim);
  border-radius: 10px 10px 0 0; box-shadow: 0 -8px 30px rgba(0,0,0,.6);
  padding: 10px 16px calc(16px + env(safe-area-inset-bottom));
  transform: translateY(100%); transition: transform .24s cubic-bezier(.2,.7,.2,1);
  max-height: 88vh; overflow-y: auto;
}
.mdb-sheet.open, .mdb-drawer.open { display: block; transform: translateY(0); }
@media (prefers-reduced-motion: reduce) { .mdb-sheet, .mdb-drawer { transition: none; } }
.mdb-grab { width: 40px; height: 4px; border-radius: 2px; background: rgba(255,255,255,.18); margin: 2px auto 12px; }
.mdb-sheet-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.mdb-sheet-sprite { width: 58px; height: 58px; border: 1px solid var(--hairline-2); display: flex; align-items: center; justify-content: center; }
.mdb-sheet-sprite img { width: 54px; height: 54px; image-rendering: pixelated; }
.mdb-sheet-id { flex: 1; min-width: 0; }
.mdb-sheet-name { font-family: var(--font-display); font-weight: 700; font-size: 17px; color: var(--text); }
.mdb-sheet-types { display: flex; gap: 4px; margin-top: 4px; }
.mdb-type { font-size: 8.5px; font-weight: 800; color: #fff; padding: 2px 7px; }
.mdb-sheet-cost { text-align: right; }
.mdb-sheet-cost .pt { font-family: var(--font-mono); font-weight: 800; font-size: 16px; color: var(--cyan); display: block; }
.mdb-sheet-cost .bst { font-family: var(--font-mono); font-size: 8px; color: var(--text-dim); }
.mdb-stats { display: flex; flex-direction: column; gap: 7px; margin-bottom: 12px; }
.mdb-stat { display: flex; align-items: center; gap: 8px; }
.mdb-stat-l { font-family: var(--font-mono); font-size: 9px; color: var(--text-dim); width: 30px; }
.mdb-stat-track { flex: 1; height: 6px; background: rgba(255,255,255,.06); overflow: hidden; }
.mdb-stat-track i { display: block; height: 100%; }
.mdb-stat-v { font-family: var(--font-mono); font-weight: 700; font-size: 11px; width: 28px; text-align: right; }
.mdb-speed { font-family: var(--font-mono); font-size: 9px; color: var(--text-mute); background: var(--panel); border: 1px solid var(--hairline); padding: 7px 10px; margin-bottom: 12px; }
.mdb-speed b { color: var(--magenta); }
.mdb-actions { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.mdb-btn { height: 44px; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-weight: 700; font-size: 10.5px; text-decoration: none; cursor: pointer; }
.mdb-btn.star { background: none; border: 1px solid var(--amber); color: var(--amber); }
.mdb-btn.star.on { background: var(--amber); color: #000; }
.mdb-btn.cmp { background: var(--cyan); border: 1px solid var(--cyan); color: #000; }
.mdb-btn.cmp.on { background: none; color: var(--cyan); }
.mdb-btn.dex { background: none; border: 1px solid var(--hairline-2); color: var(--text); }
```

- [ ] **Step 4: Render check**

Run:
```bash
./.venv/Scripts/python.exe -c "
import os,tempfile; os.environ['DATABASE']=os.path.join(tempfile.mkdtemp(),'t.db')
import importlib.util; s=importlib.util.spec_from_file_location('app','app.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
c=m.app.test_client()
r=c.get('/draftboard'); b=r.get_data(as_text=True)
js=c.get('/static/mobile-draftboard.js')
print('draftboard', r.status_code, '| js included:', 'mobile-draftboard.js' in b, '| js served:', js.status_code, '| has openSheet:', 'openSheet' in js.get_data(as_text=True))
"
```
Expected: `draftboard 200 | js included: True | js served: 200 | has openSheet: True`

- [ ] **Step 5: Manual check (DevTools ≤767px, touch emulation)**

At 390px, tap a Pokémon tile → the action sheet slides up showing sprite, name, type chips, PT/BST, 6 colored stat bars, the speed strip (`SPE @ 252+ … · @ 252 … · @ 0 …`), and STAR / COMPARE / DEX buttons. Tap COMPARE → the mon appears in the compare tray (confirms it reused `pinPoke`). Tap STAR → the tile's star marker turns on. Tap the overlay → sheet closes. Confirm desktop (≥768px) tiles do NOT open a sheet on click.

- [ ] **Step 6: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: `114 passed`.

- [ ] **Step 7: Commit**

```bash
git add static/mobile-draftboard.js static/mobile.css templates/draftboard.html
git commit -m "feat: mobile draft board tap action sheet (3b)"
```

---

## Task 3: Filter drawer + funnel button (3c) + tooltip suppression

**Files:**
- Modify: `static/mobile-draftboard.js` — add the filter drawer, funnel-button wiring, live count, and touch tooltip suppression.
- Modify: `templates/draftboard.html` — add a funnel button in the mobile control area.
- Modify: `static/mobile.css` — append drawer + funnel-button CSS.

**Interfaces:**
- Consumes: existing filter inputs by id — `#db-search`, `#db-ability`, `#db-move`, `#db-type`, `#db-status`, `#db-speed`, `#db-star-btn`; functions `filterBoard()`, `clearFilters()`, `buildAbilityList()`. Existing `window._mdb` from Task 2.
- Produces: `window._mdb.openDrawer()` / `closeDrawer()` / `updateCount()`; a funnel button with an active-filter count badge; the document `mouseover` stat-tooltip suppressed on `(hover: none)`.

- [ ] **Step 1: Add the funnel button to `templates/draftboard.html`**

Find the mobile control area — the `.dbl-ctrl-top` element (search `class="dbl-ctrl-top"`). Immediately INSIDE it, as the first child, add the funnel button (hidden on desktop via CSS):

```html
<button type="button" id="mdb-funnel" class="mdb-funnel" onclick="window._mdb && window._mdb.openDrawer()" aria-label="Filters">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 4h18l-7 8v6l-4 2v-8L3 4z"/></svg>
  <span id="mdb-funnel-badge" class="mdb-funnel-badge" style="display:none">0</span>
</button>
```

- [ ] **Step 2: Add the drawer JS to `static/mobile-draftboard.js`**

Add BEFORE the final `window._mdb = {...}` line (and extend that object). Insert:

```javascript
  // ── FILTER DRAWER (3c) ──
  var drawer, drawerOverlay;
  function $(id) { return document.getElementById(id); }
  function activeFilterCount() {
    var n = 0;
    if (($("db-search") || {}).value) n++;
    if (($("db-ability") || {}).value) n++;
    if (($("db-move") || {}).value) n++;
    var t = $("db-type"); if (t && t.value && t.value !== "all") n++;
    var st = $("db-status"); if (st && st.value && st.value !== "all") n++;
    var sp = $("db-speed"); if (sp && sp.value && sp.value !== "all") n++;
    var starBtn = $("db-star-btn");  // star-only filter: state is the .active class
    if (starBtn && starBtn.classList.contains("active")) n++;
    return n;
  }
  function visibleCount() {
    return document.querySelectorAll(".board-poke:not([style*='display: none'])").length;
  }
  function updateCount() {
    var badge = $("mdb-funnel-badge");
    if (badge) { var n = activeFilterCount(); badge.textContent = n; badge.style.display = n ? "flex" : "none"; }
    var show = $("mdb-show-btn");
    if (show) show.textContent = "SHOW " + visibleCount() + " MONS";
  }
  function buildDrawer() {
    drawerOverlay = document.createElement("div");
    drawerOverlay.className = "mdb-overlay";
    drawerOverlay.addEventListener("click", closeDrawer);
    drawer = document.createElement("div");
    drawer.className = "mdb-drawer";
    drawer.addEventListener("click", function (e) { e.stopPropagation(); });
    drawer.innerHTML =
      '<div class="mdb-grab"></div>' +
      '<div class="mdb-drawer-head"><span>FILTERS</span><button class="mdb-x" id="mdb-drawer-x">✕</button></div>' +
      '<div class="mdb-drawer-body" id="mdb-drawer-body"></div>' +
      '<div class="mdb-drawer-foot">' +
        '<button class="mdb-btn clear" id="mdb-clear-btn">CLEAR</button>' +
        '<button class="mdb-btn show" id="mdb-show-btn">SHOW MONS</button>' +
      "</div>";
    document.body.appendChild(drawerOverlay);
    document.body.appendChild(drawer);
    // Move the REAL filter inputs into the drawer body so we reuse them directly
    // (no proxy/mirroring — they keep their ids, listeners, and autocomplete).
    var body = drawer.querySelector("#mdb-drawer-body");
    ["db-search", "db-type", "db-status", "db-speed", "db-ability", "db-move"].forEach(function (id) {
      var el = $(id);
      if (el) { var wrap = document.createElement("div"); wrap.className = "mdb-field"; wrap.appendChild(el); body.appendChild(wrap); }
    });
    drawer.querySelector("#mdb-drawer-x").addEventListener("click", closeDrawer);
    drawer.querySelector("#mdb-clear-btn").addEventListener("click", function () {
      if (window.clearFilters) window.clearFilters();
      updateCount();
    });
    drawer.querySelector("#mdb-show-btn").addEventListener("click", closeDrawer);
  }
  function openDrawer() {
    if (!drawer) buildDrawer();
    updateCount();
    drawerOverlay.classList.add("open");
    drawer.classList.add("open");
    lockBody(true);
    _open = "drawer";
  }
  function closeDrawer() {
    if (drawer) drawer.classList.remove("open");
    if (drawerOverlay) drawerOverlay.classList.remove("open");
    lockBody(false);
    _open = null;
  }

  // keep the live count in sync after any filter change
  if (window.filterBoard) {
    var _fb = window.filterBoard;
    window.filterBoard = function () { _fb.apply(this, arguments); updateCount(); };
  }

  // ── suppress the hover stat-tooltip on touch devices (tap opens the sheet) ──
  if (TOUCH.matches) {
    document.addEventListener("mouseover", function (e) { e.stopImmediatePropagation(); }, true);
  }
```

Then change the final line from `window._mdb = { openSheet: openSheet, closeSheet: closeSheet, isMobile: isMobile };` to:

```javascript
  window._mdb = {
    openSheet: openSheet, closeSheet: closeSheet, isMobile: isMobile,
    openDrawer: openDrawer, closeDrawer: closeDrawer, updateCount: updateCount
  };
```

**Star-filter state (confirmed):** the page's `setStarFilter()` flips a `currentStarred` global and toggles the `.active` class on `#db-star-btn`; `clearFilters()` removes it. The `activeFilterCount()` code above reads that `.active` class directly (no new global). This is the real, verified state — do not invent one.

- [ ] **Step 3: Append drawer + funnel CSS to `static/mobile.css`**

Add at the END of `static/mobile.css`:

```css
/* Draft-board mobile: funnel button (hidden on desktop) */
.mdb-funnel { display: none; }
@media (max-width: 767px) {
  .mdb-funnel {
    display: inline-flex; align-items: center; justify-content: center; position: relative;
    width: 44px; height: 44px; flex-shrink: 0;
    background: var(--cyan-soft); border: 1px solid var(--cyan-dim); color: var(--cyan); cursor: pointer;
  }
  .mdb-funnel svg { width: 20px; height: 20px; }
  .mdb-funnel-badge {
    position: absolute; top: -4px; right: -4px; min-width: 16px; height: 16px; padding: 0 3px;
    display: flex; align-items: center; justify-content: center;
    background: var(--cyan); color: #000; font-family: var(--font-mono); font-weight: 700; font-size: 9px;
  }
  /* Hide the desktop inline filter row on phones (the drawer relocates them) */
  .dbl-filters { display: none; }
}
.mdb-drawer-head { display: flex; justify-content: space-between; align-items: center; font-family: var(--font-mono); font-size: 10px; letter-spacing: .1em; color: var(--text); margin-bottom: 12px; }
.mdb-x { background: none; border: none; color: var(--text-dim); font-size: 16px; cursor: pointer; }
.mdb-drawer-body { display: flex; flex-direction: column; gap: 10px; }
.mdb-field { display: flex; flex-direction: column; }
.mdb-field input, .mdb-field select { font-size: 16px !important; min-height: 44px; width: 100% !important; max-width: none !important; }
.mdb-drawer-foot { display: flex; gap: 10px; margin-top: 14px; }
.mdb-btn.clear { flex: 0 0 110px; background: none; border: 1px solid var(--magenta); color: var(--magenta); }
.mdb-btn.show { flex: 1; height: 46px; background: var(--cyan); border: 1px solid var(--cyan); color: #000; }
```

**Note:** the `.mdb-field input/select { font-size: 16px }` override defeats iOS focus-zoom and un-does the old mobile block's `max-width: 160px` on these inputs now that they live in the drawer.

- [ ] **Step 4: Render check**

Run:
```bash
./.venv/Scripts/python.exe -c "
import os,tempfile; os.environ['DATABASE']=os.path.join(tempfile.mkdtemp(),'t.db')
import importlib.util; s=importlib.util.spec_from_file_location('app','app.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
c=m.app.test_client()
b=c.get('/draftboard').get_data(as_text=True)
js=c.get('/static/mobile-draftboard.js').get_data(as_text=True)
print('funnel button:', 'mdb-funnel' in b, '| openDrawer in js:', 'openDrawer' in js, '| moves real inputs:', 'db-ability' in js)
"
```
Expected: `funnel button: True | openDrawer in js: True | moves real inputs: True`

- [ ] **Step 5: Manual check (DevTools ≤767px)**

At 390px: the inline filter row is hidden; a funnel button shows in the controls. Tap it → drawer slides up with all filters at ≥44px/16px (no iOS zoom on focus). Type in search / pick a type → the board filters live AND the "SHOW N MONS" button count updates AND the funnel badge shows the active-filter count. Ability field autocomplete still works inside the drawer. CLEAR resets everything. Tap SHOW → drawer closes. Confirm the stat tooltip no longer appears on tap (touch), but at ≥768px with a mouse it still appears on hover and the inline filters are back.

- [ ] **Step 6: Full suite + bump build marker**

Run: `./.venv/Scripts/python.exe -m pytest -q` → `114 passed`.
Then in `templates/base.html`, change `console.log("YDL build: ai-commentary-retry-v59");` to `console.log("YDL build: mobile-draftboard-v60");` (or the next integer above the current marker).

- [ ] **Step 7: Commit**

```bash
git add static/mobile-draftboard.js static/mobile.css templates/draftboard.html templates/base.html
git commit -m "feat: mobile draft board filter drawer + tooltip suppression (3c)"
```

---

## Task 4: Integration polish + desktop-parity verification

**Files:**
- Modify (if needed): `static/mobile-draftboard.js`, `static/mobile.css` — only to fix issues found during the integration pass.

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: a verified feature — no desktop regression, sheet/drawer mutually exclusive, safe-area/tab-bar clearance correct.

- [ ] **Step 1: Desktop-parity render diff**

Confirm the desktop path is byte-identical in behavior: at ≥768px, `matchMedia('(max-width:767px)')` is false, so `openSheet` early-returns on tile click, the funnel is `display:none`, `.dbl-filters` is visible, and the tooltip fires. Manually load `/draftboard` at 1200px and confirm: sideways tier columns, hover tooltips, hover-gated star/pin, inline filters — all exactly as before this branch.

- [ ] **Step 2: Sheet/drawer exclusivity + scroll lock**

At ≤767px: open the action sheet, then (without closing) confirm you cannot also open the drawer over it, and vice-versa (only one `_open` at a time; opening one closes the other — if not already the case, in `openSheet` call `closeDrawer()` first and in `openDrawer` call `closeSheet()` first). Confirm the body does not scroll behind an open sheet/drawer, and scrolling is restored after close.

- [ ] **Step 3: Tab-bar + safe-area clearance**

Confirm the compare tray sits above the 76px tab bar (already handled by `mobile.css`'s `#compare-tray { bottom: calc(76px + env(safe-area-inset-bottom)) }`), and the sheet/drawer bottom padding clears the home indicator (the `env(safe-area-inset-bottom)` in `.mdb-sheet`/`.mdb-drawer` padding). Nothing is obscured by the fixed tab bar.

- [ ] **Step 4: Full suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: `114 passed`.

- [ ] **Step 5: Commit (only if Step 2 required a code change)**

```bash
git add static/mobile-draftboard.js static/mobile.css
git commit -m "fix: mobile draft board sheet/drawer exclusivity + clearance"
```

---

## Post-plan: finishing the branch

After all tasks pass and the whole-branch review is clean, use
`superpowers:finishing-a-development-branch` to merge `feat/mobile-draftboard`
into `main` (`--no-ff`), verify the suite, delete the branch. Then offer to
push (`git push origin HEAD:master`) and deploy (PythonAnywhere reload) on the
user's approval — do not auto-push. **Manual phone/DevTools verification of all
three screens is required before merge** since there is no automated browser test.
