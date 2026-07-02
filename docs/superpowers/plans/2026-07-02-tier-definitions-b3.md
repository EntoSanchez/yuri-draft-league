# Phase 1B-3: Configurable Tier Definitions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make **which point values belong to which tier** and **each tier's ticket allocation** configurable — the `_regular_tier_label` thresholds and the `TICKET_ALLOC`/`TICKET_RANK`/`TIER_TO_TICKET` constants become functions of a `tier_definitions` setting — with defaults that reproduce this season byte-for-byte, plus a settings editor.

**Architecture:** A `tier_definitions` JSON setting (ordered 5-tier list `[{name, columns:[ints], ticket_alloc}]`) drives `get_tier_definitions()` and the derived `get_ticket_alloc()` / `get_ticket_rank()` / `get_tier_to_ticket()`. `_regular_tier_label(pts)` maps points via the configured columns (threshold-style fallback), reproducing 16/13/9/5 at default. The 8 ticket-constant references are rewired to the new functions; **the old module constants are kept as the fallback default**, so a missed rewire can only leave a site on the (correct) default — never change behavior. Equivalence tests prove the derived values equal the old constants and the label is identical for points 0–30. Scope is deliberately **the fixed 5 tiers (Tier 1–5)** — editing their columns + ticket allocation; **adding/removing/renaming tiers and `uber_picks_per_team` are out of scope** (they cascade into TIER_ORDER, round structure, uber slots — a later slice).

**Tech Stack:** Python 3 / Flask / SQLite; pytest (existing harness); Jinja2 + Tailwind.

Slice **B3** of Phase 1B (spec `docs/superpowers/specs/2026-06-30-settings-rework-and-draft-board-templates-design.md`, §5.5 tier definitions + ticket allocation).

## Global Constraints

- Run Python only via `./.venv/Scripts/python.exe` (from `D:/Yuri Draft League`). Never base python.
- **Behavior-preservation:** with no `tier_definitions` stored, `_regular_tier_label` returns the same label for every point value 0–30, and `get_ticket_alloc()/get_ticket_rank()/get_tier_to_ticket()` equal the current `TICKET_ALLOC`/`TICKET_RANK`/`TIER_TO_TICKET` exactly. Equivalence tests must prove this. If any diff appears at defaults, STOP.
- **Keep the module constants `TICKET_ALLOC` / `TICKET_RANK` / `TIER_TO_TICKET`** — they are the fallback default; do not delete them. A call site not yet rewired must still reference the constant (safe = default).
- The new accessors use the existing `get_setting` helper (no db arg); they are called in read / pre-write contexts (as the current constant references are).
- **Never** `git add -A`; stage explicit paths only. Never commit `*.db` or `backups/`. Do NOT push.
- Match existing route/template style. `json` and `re` are already imported in `app.py`.

## File Structure

- `app.py` — `DEFAULT_TIER_DEFINITIONS`; `get_tier_definitions()` + derived accessors; refactor `_regular_tier_label`; rewire 8 ticket references; `admin_settings` assembles `tier_definitions` from per-tier form fields and passes `tier_defs` to the template.
- `templates/admin/settings.html` — a "Tier Definitions" editor section.
- `tests/test_tier_definitions.py` — NEW: accessor + equivalence tests.
- `tests/test_settings_page.py` — extend for the new section.

---

## Task 1: Tier-definition accessors (defaults == current constants)

**Files:**
- Modify: `app.py` — add `DEFAULT_TIER_DEFINITIONS` + accessors (place them just after the `TICKET_ALLOC/TICKET_RANK/TIER_TO_TICKET` constants, ~line 4723)
- Test: `tests/test_tier_definitions.py`

**Interfaces:**
- Produces:
  - `DEFAULT_TIER_DEFINITIONS` (list of 5 `{name, columns, ticket_alloc}`)
  - `get_tier_definitions() -> list[dict]`
  - `get_ticket_alloc() -> dict` (e.g. `{"T1":1,...}`)
  - `get_ticket_rank() -> dict`
  - `get_tier_to_ticket() -> dict`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tier_definitions.py
"""B3: configurable tier columns + ticket allocation; defaults reproduce today."""


def test_defaults_equal_current_constants(app_mod):
    assert app_mod.get_ticket_alloc() == {"T1": 1, "T2": 1, "T3": 2, "T4": 2, "T5": 2}
    assert app_mod.get_ticket_rank() == {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}
    assert app_mod.get_tier_to_ticket() == {
        "Tier 1": "T1", "Tier 2": "T2", "Tier 3": "T3", "Tier 4": "T4", "Tier 5": "T5"}


def test_default_columns_partition_0_to_30(app_mod):
    defs = app_mod.get_tier_definitions()
    assert [d["name"] for d in defs] == ["Tier 1", "Tier 2", "Tier 3", "Tier 4", "Tier 5"]
    seen = sorted(c for d in defs for c in d["columns"])
    assert seen == list(range(0, 31))  # every point 0..30 assigned exactly once


def test_stored_definitions_override_and_derive(app_mod):
    import json
    stored = [
        {"name": "Tier 1", "columns": [20, 21], "ticket_alloc": 3},
        {"name": "Tier 2", "columns": [10, 11], "ticket_alloc": 1},
        {"name": "Tier 3", "columns": [0, 1], "ticket_alloc": 1},
        {"name": "Tier 4", "columns": [2, 3], "ticket_alloc": 1},
        {"name": "Tier 5", "columns": [4, 5], "ticket_alloc": 1},
    ]
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('tier_definitions', ?)",
                   (json.dumps(stored),))
    assert app_mod.get_ticket_alloc()["T1"] == 3
    assert app_mod.get_tier_to_ticket()["Tier 1"] == "T1"
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_tier_definitions.py -v`
Expected: FAIL (accessors undefined).

- [ ] **Step 3: Add the default + accessors**

Add immediately after the `TIER_TO_TICKET = {...}` line (~4723). **Do not remove the three constants above** (they remain the fallback default):

```python
# Configurable tier definitions (B3). DEFAULT reproduces the constants above and the
# 16/13/9/5 thresholds: columns partition points 0..30 so _regular_tier_label matches.
DEFAULT_TIER_DEFINITIONS = [
    {"name": "Tier 1", "columns": list(range(16, 31)), "ticket_alloc": 1},  # 16-30
    {"name": "Tier 2", "columns": [13, 14, 15],        "ticket_alloc": 1},
    {"name": "Tier 3", "columns": [9, 10, 11, 12],     "ticket_alloc": 2},
    {"name": "Tier 4", "columns": [5, 6, 7, 8],        "ticket_alloc": 2},
    {"name": "Tier 5", "columns": [0, 1, 2, 3, 4],     "ticket_alloc": 2},
]


def get_tier_definitions():
    """Ordered tier list [{name, columns:[int], ticket_alloc:int}]. Default reproduces
    the 16/13/9/5 thresholds + TICKET_ALLOC. Malformed stored JSON falls back to default."""
    raw = get_setting("tier_definitions", "")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                out = []
                for d in data:
                    out.append({
                        "name": str(d.get("name", "")),
                        "columns": [int(c) for c in d.get("columns", [])],
                        "ticket_alloc": int(d.get("ticket_alloc", 0) or 0),
                    })
                return out
        except Exception:
            pass
    return [dict(d) for d in DEFAULT_TIER_DEFINITIONS]


def get_ticket_alloc():
    """{ticket_key -> allocation}, e.g. {'T1':1,...}. Derived from tier_definitions order."""
    return {f"T{i+1}": t["ticket_alloc"] for i, t in enumerate(get_tier_definitions())}


def get_ticket_rank():
    """{ticket_key -> rank} (1 = best tier)."""
    return {f"T{i+1}": i + 1 for i, t in enumerate(get_tier_definitions())}


def get_tier_to_ticket():
    """{tier name -> ticket_key}, e.g. {'Tier 1':'T1',...}."""
    return {t["name"]: f"T{i+1}" for i, t in enumerate(get_tier_definitions())}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_tier_definitions.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_tier_definitions.py
git commit -m "feat: tier-definition accessors (columns + ticket alloc), defaults == constants"
```

---

## Task 2: Refactor `_regular_tier_label` to use tier definitions

**Files:**
- Modify: `app.py` — `_regular_tier_label` (lines 2579-2586). **Its 5 call sites do not change** (signature stays `_regular_tier_label(pts)`).
- Test: `tests/test_tier_definitions.py`

**Interfaces:**
- Consumes: `get_tier_definitions()` (Task 1).

- [ ] **Step 1: Write the equivalence test**

```python
# add to tests/test_tier_definitions.py
def _old_regular_tier_label(pts):
    if pts >= 16: return "Tier 1"
    if pts >= 13: return "Tier 2"
    if pts >= 9:  return "Tier 3"
    if pts >= 5:  return "Tier 4"
    if pts >= 0:  return "Tier 5"
    return ""


def test_regular_tier_label_matches_old_for_0_to_30(app_mod):
    for pts in range(0, 31):
        assert app_mod._regular_tier_label(pts) == _old_regular_tier_label(pts), f"diff at {pts}"


def test_regular_tier_label_honors_custom_columns(app_mod):
    import json
    # Inverted columns (low pts -> Tier 1, high pts -> Tier 5) so results DIFFER from
    # the old thresholds — the test must fail against old code and pass after the refactor.
    stored = [
        {"name": "Tier 1", "columns": [0, 1], "ticket_alloc": 1},     # old would call 0 -> Tier 5
        {"name": "Tier 2", "columns": [2, 3], "ticket_alloc": 1},
        {"name": "Tier 3", "columns": [4, 5], "ticket_alloc": 1},
        {"name": "Tier 4", "columns": [6, 7], "ticket_alloc": 1},
        {"name": "Tier 5", "columns": [16, 17], "ticket_alloc": 1},   # old would call 16 -> Tier 1
    ]
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('tier_definitions', ?)",
                   (json.dumps(stored),))
    assert app_mod._regular_tier_label(0) == "Tier 1"    # old code: "Tier 5"
    assert app_mod._regular_tier_label(16) == "Tier 5"   # old code: "Tier 1"
```

- [ ] **Step 2: Run to confirm the custom-columns test fails**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_tier_definitions.py -k "regular_tier_label" -v`
Expected: `test_regular_tier_label_matches_old_for_0_to_30` PASSES (old code equals itself — the equivalence baseline); `test_regular_tier_label_honors_custom_columns` FAILS (old code ignores the setting, so `_regular_tier_label(0)` returns "Tier 5" not "Tier 1").

- [ ] **Step 3: Refactor `_regular_tier_label`**

Replace lines 2579-2586:
```python
def _regular_tier_label(pts):
    """Map point value to Tier 1–5 label for regular (non-Mega) Pokemon."""
    if pts >= 16: return "Tier 1"
    if pts >= 13: return "Tier 2"
    if pts >= 9:  return "Tier 3"
    if pts >= 5:  return "Tier 4"
    if pts >= 0:  return "Tier 5"
    return ""
```
with:
```python
def _regular_tier_label(pts):
    """Map point value to a regular tier name via configured tier_definitions.
    Points explicitly listed in a tier's columns map to it; points outside all
    listed columns fall back to the highest tier whose smallest column is <= pts
    (threshold semantics). The default definitions reproduce the 16/13/9/5 tiers."""
    defs = get_tier_definitions()
    for t in defs:
        if pts in t["columns"]:
            return t["name"]
    for t in defs:  # defs are ordered best->worst; first match is the highest tier
        if t["columns"] and pts >= min(t["columns"]):
            return t["name"]
    return defs[-1]["name"] if defs else ""
```

- [ ] **Step 4: Run the tests + full suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_tier_definitions.py -v && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (equivalence 0–30 holds; custom columns honored; nothing else regresses).

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_tier_definitions.py
git commit -m "feat: _regular_tier_label reads tier_definitions (default reproduces 16/13/9/5)"
```

---

## Task 3: Rewire the ticket-constant references to the accessors

Replace the 8 references to `TICKET_ALLOC` / `TICKET_RANK` / `TIER_TO_TICKET` with the new functions. (The constants stay defined as the fallback default.)

**Files:**
- Modify: `app.py` — lines 4912; 5274-5275; the `tier_tickets` branch 5469-5488; 6127
- Test: `tests/test_tier_definitions.py`

**Interfaces:**
- Consumes: `get_ticket_alloc()`, `get_ticket_rank()`, `get_tier_to_ticket()` (Task 1).

- [ ] **Step 1: Write a ticket-config behavior test**

```python
# add to tests/test_tier_definitions.py
def test_ticket_alloc_config_reaches_coach_state(app_mod):
    """_get_coach_draft_state's remaining_tickets reflects the configured allocation."""
    import json
    stored = [
        {"name": "Tier 1", "columns": [16], "ticket_alloc": 5},
        {"name": "Tier 2", "columns": [13], "ticket_alloc": 1},
        {"name": "Tier 3", "columns": [9], "ticket_alloc": 1},
        {"name": "Tier 4", "columns": [5], "ticket_alloc": 1},
        {"name": "Tier 5", "columns": [0], "ticket_alloc": 1},
    ]
    with app_mod.get_db() as db:
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM draft_sessions")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool, draft_mode) VALUES (1,'C','T','A','tier_tickets')")
        db.execute("INSERT INTO draft_sessions (id, name, status) VALUES (1,'S','active')")
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('tier_definitions', ?)", (json.dumps(stored),))
        st = app_mod._get_coach_draft_state(db, 1, 1)
    assert st["remaining_tickets"]["T1"] == 5  # configured alloc flows through
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_tier_definitions.py -k "reaches_coach_state" -v`
Expected: FAIL (`remaining_tickets["T1"]` is still 1 — `_get_coach_draft_state` uses the hardcoded `TICKET_ALLOC`).

- [ ] **Step 3: Rewire the references**

**4912** — replace:
```python
        remaining_tickets = {t: TICKET_ALLOC[t] - used.get(t, 0) for t in TICKET_ALLOC}
```
with:
```python
        _alloc = get_ticket_alloc()
        remaining_tickets = {t: _alloc[t] - used.get(t, 0) for t in _alloc}
```

**5274-5275** (draft_sheet render_template kwargs) — replace:
```python
        ticket_alloc=TICKET_ALLOC,
        tier_to_ticket=TIER_TO_TICKET,
```
with:
```python
        ticket_alloc=get_ticket_alloc(),
        tier_to_ticket=get_tier_to_ticket(),
```

**5469 branch** — at the top of `elif coach_mode == "tier_tickets":` (line 5469), add three locals, then use them. Replace lines 5469-5488:
```python
        elif coach_mode == "tier_tickets":
            poke_tier = _regular_tier_label(points)
            poke_ticket = TIER_TO_TICKET.get(poke_tier)
            if not poke_ticket:
                flash("Cannot determine ticket tier for this Pokémon.", "warning")
                return redirect(url_for("draft_live"))
            chosen_ticket = request.form.get("ticket_used") or poke_ticket
            chosen_rank = TICKET_RANK.get(chosen_ticket, 999)
            poke_rank = TICKET_RANK[poke_ticket]
            if chosen_rank > poke_rank:
                flash("You cannot use a lower-tier ticket on a higher-tier Pokémon.", "warning")
                return redirect(url_for("draft_live"))
            used_rows = db.execute(
                "SELECT ticket_used, COUNT(*) as cnt FROM draft_picks "
                "WHERE session_id=? AND coach_id=? AND ticket_used IS NOT NULL AND ticket_used != 'uber' "
                "GROUP BY ticket_used",
                (session_row["id"], coach_id),
            ).fetchall()
            used_map = {r["ticket_used"]: r["cnt"] for r in used_rows}
            avail = TICKET_ALLOC.get(chosen_ticket, 0) - used_map.get(chosen_ticket, 0)
            if avail <= 0:
                flash(f"No {chosen_ticket} tickets remaining.", "warning")
                return redirect(url_for("draft_live"))
            ticket_used_val = chosen_ticket
```
with:
```python
        elif coach_mode == "tier_tickets":
            _tier_to_ticket = get_tier_to_ticket()
            _ticket_rank = get_ticket_rank()
            _ticket_alloc = get_ticket_alloc()
            poke_tier = _regular_tier_label(points)
            poke_ticket = _tier_to_ticket.get(poke_tier)
            if not poke_ticket:
                flash("Cannot determine ticket tier for this Pokémon.", "warning")
                return redirect(url_for("draft_live"))
            chosen_ticket = request.form.get("ticket_used") or poke_ticket
            chosen_rank = _ticket_rank.get(chosen_ticket, 999)
            poke_rank = _ticket_rank[poke_ticket]
            if chosen_rank > poke_rank:
                flash("You cannot use a lower-tier ticket on a higher-tier Pokémon.", "warning")
                return redirect(url_for("draft_live"))
            used_rows = db.execute(
                "SELECT ticket_used, COUNT(*) as cnt FROM draft_picks "
                "WHERE session_id=? AND coach_id=? AND ticket_used IS NOT NULL AND ticket_used != 'uber' "
                "GROUP BY ticket_used",
                (session_row["id"], coach_id),
            ).fetchall()
            used_map = {r["ticket_used"]: r["cnt"] for r in used_rows}
            avail = _ticket_alloc.get(chosen_ticket, 0) - used_map.get(chosen_ticket, 0)
            if avail <= 0:
                flash(f"No {chosen_ticket} tickets remaining.", "warning")
                return redirect(url_for("draft_live"))
            ticket_used_val = chosen_ticket
```

**6127** (admin_draft render_template kwargs) — replace:
```python
        ticket_alloc=TICKET_ALLOC,
```
with:
```python
        ticket_alloc=get_ticket_alloc(),
```

(Line numbers may shift as you edit; the four render kwargs `ticket_alloc=TICKET_ALLOC` appear twice — at ~5274 in `draft_sheet` and ~6127 in `admin_draft` — replace both; `tier_to_ticket=TIER_TO_TICKET` appears once at ~5275.)

- [ ] **Step 4: Run the test + full suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_tier_definitions.py -v && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (config flows through; defaults unchanged).

- [ ] **Step 5: Verify no stray constant references remain in the rewired functions**

Run: `cd "D:/Yuri Draft League" && grep -nE "TICKET_ALLOC|TICKET_RANK|TIER_TO_TICKET" app.py`
Expected: only the three constant **definitions** (~4721-4723) remain; no other references (all rewired to `get_*`).

- [ ] **Step 6: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_tier_definitions.py
git commit -m "feat: rewire ticket allocation/rank/mapping to tier_definitions accessors"
```

---

## Task 4: Tier Definitions settings editor

An editor for the 5 tiers' columns + ticket allocation. `admin_settings` assembles the `tier_definitions` JSON from per-tier fields and passes the current definitions to the template.

**Files:**
- Modify: `app.py` — in `admin_settings` POST, assemble `tier_definitions` from `tier_cols_N` / `tier_alloc_N`; pass `tier_defs=get_tier_definitions()` to the template
- Modify: `templates/admin/settings.html` — a "Tier Definitions" section
- Test: `tests/test_settings_page.py`

**Interfaces:**
- Consumes: `get_tier_definitions()` (Task 1).

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_settings_page.py
import json as _json


def test_has_tier_definitions_editor(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "Tier Definitions" in html
    for i in (1, 2, 3, 4, 5):
        assert f'name="tier_cols_{i}"' in html
        assert f'name="tier_alloc_{i}"' in html


def test_tier_definitions_assembled_and_persisted(client, app_mod):
    client.post("/admin/settings", data={
        "league_name": "X",
        "tier_cols_1": "16,17,18", "tier_alloc_1": "2",
        "tier_cols_2": "13,14,15", "tier_alloc_2": "1",
        "tier_cols_3": "9,10,11,12", "tier_alloc_3": "2",
        "tier_cols_4": "5,6,7,8", "tier_alloc_4": "2",
        "tier_cols_5": "0,1,2,3,4", "tier_alloc_5": "2",
    })
    with app_mod.get_db() as db:
        raw = db.execute("SELECT value FROM league_settings WHERE key='tier_definitions'").fetchone()["value"]
    defs = _json.loads(raw)
    assert defs[0] == {"name": "Tier 1", "columns": [16, 17, 18], "ticket_alloc": 2}
    assert len(defs) == 5 and defs[4]["columns"] == [0, 1, 2, 3, 4]
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -k "tier_definitions" -v`
Expected: FAIL (no editor; `tier_definitions` not assembled).

- [ ] **Step 3: Assemble + pass tier_defs in `admin_settings`**

In `admin_settings` POST (after the generic form loop, before the redirect), add:

```python
            # Assemble tier_definitions from the per-tier editor fields (fixed 5 tiers).
            if any(k.startswith("tier_cols_") for k in request.form):
                tdefs = []
                for i, name in enumerate(["Tier 1", "Tier 2", "Tier 3", "Tier 4", "Tier 5"], start=1):
                    cols_raw = request.form.get(f"tier_cols_{i}", "")
                    cols = [int(x) for x in re.split(r"[,\s]+", cols_raw.strip())
                            if x.strip().lstrip("-").isdigit()]
                    alloc = int(request.form.get(f"tier_alloc_{i}", "0") or 0)
                    tdefs.append({"name": name, "columns": cols, "ticket_alloc": alloc})
                db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('tier_definitions', ?)",
                           (json.dumps(tdefs),))
```

In the `admin_settings` GET `render_template("admin/settings.html", ...)` call, add the kwarg:
```python
                           tier_defs=get_tier_definitions(),
```

- [ ] **Step 4: Add the Tier Definitions section to `templates/admin/settings.html`**

Insert this `<section>` immediately **before** the `<!-- ── Draft Structure ──` section:

```html
  <!-- ── Tier Definitions ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-3">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Tier Definitions</h2>
    <p class="text-xs text-gray-500">Which point values belong to each tier, and how many tickets each tier gets. Default reproduces T1 ≥16 · T2 13–15 · T3 9–12 · T4 5–8 · T5 0–4.</p>
    <div class="space-y-2">
      <div class="grid grid-cols-[70px_1fr_70px] gap-2 text-xs text-gray-500 font-semibold">
        <span>Tier</span><span>Point columns (comma-separated)</span><span>Tickets</span>
      </div>
      {% for t in tier_defs %}
      <div class="grid grid-cols-[70px_1fr_70px] gap-2 items-center">
        <span class="text-sm text-gray-300 font-semibold">{{ t.name }}</span>
        <input type="text" name="tier_cols_{{ loop.index }}" value="{{ t.columns | join(', ') }}"
               class="bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white text-sm">
        <input type="number" name="tier_alloc_{{ loop.index }}" value="{{ t.ticket_alloc }}" min="0"
               class="bg-gray-800 border border-gray-600 rounded px-2 py-2 text-white text-sm">
      </div>
      {% endfor %}
    </div>
    <p class="text-xs text-gray-600">Uber points (27–30) are handled by the Uber system regardless of tier columns.</p>
  </section>
```

- [ ] **Step 5: Run the settings tests + full suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -v && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (B1/B2 contract + section tests still pass; new tier-definition tests pass).

- [ ] **Step 6: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py templates/admin/settings.html tests/test_settings_page.py
git commit -m "feat: Tier Definitions settings editor (columns + ticket allocation)"
```

---

## Notes for the implementer
- **Behavior-preservation is the core requirement.** The equivalence tests (Task 2's 0–30 match; Task 1's derived == constants) are the proof. If either shows a diff at defaults, stop.
- The old `TICKET_ALLOC` / `TICKET_RANK` / `TIER_TO_TICKET` constants stay defined — they are the fallback default and a safety net for any un-rewired reference.
- **Out of scope (later slice):** adding/removing/renaming tiers (would cascade into `TIER_ORDER`, the round-structure editor, and the draftboard grouping), and `uber_picks_per_team`. Keep exactly 5 fixed tiers named Tier 1–5.
- `_mega_tier_label` is unrelated (reads `mega_*_pts`) and unchanged.
