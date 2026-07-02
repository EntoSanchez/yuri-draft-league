# Phase 1B-2: Configurable Draft Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make three currently-hardcoded draft-structure rules configurable — **roster size** (the 10-pick cap), **first-pick-must-be-regular**, and **draft order method** (snake vs linear) — plus a **randomize-order** admin helper and their settings-page editor, each defaulting to reproduce this season byte-for-byte.

**Architecture:** Small settings-backed accessors replace three hardcoded constants at their exact sites. `get_roster_size(db)` / `get_first_pick_regular(db)` read through the caller's already-open DB connection (used inside `draft_live_pick`). `get_draft_order_method()` reads via the existing `get_setting` helper and is resolved **inside** the sequence functions (default arg `None`), so **no call site of `_get_pool_sequence` changes** — avoiding a 7-call-site refactor. Defaults reproduce current behavior; equivalence tests prove identical output at defaults and that a changed setting changes the rule. First behavior-affecting Phase-1B slice, deliberately small and low-risk.

**Tech Stack:** Python 3 / Flask / SQLite; pytest (existing harness `tests/conftest.py`); Jinja2 + Tailwind.

Slice **B2** of Phase 1B (spec `docs/superpowers/specs/2026-06-30-settings-rework-and-draft-board-templates-design.md`, §5.6 — roster-size / first-pick / draft-order). The **tier-definitions refactor** and **uber-slot count** are the higher-risk B3 slice; draft-mode policy and mechanics/captains follow.

## Global Constraints

- Run Python only via the venv: `D:/Yuri Draft League/.venv/Scripts/python.exe` (Windows). Never base python.
- **Behavior-preservation:** every default must reproduce the current hardcoded value (`roster_size`=10, `first_pick_regular`=on, `draft_order_method`=snake). With no setting stored, draft behavior is byte-for-byte unchanged — proven by equivalence tests.
- `get_roster_size(db)` / `get_first_pick_regular(db)` read via the caller's open `db` (no nested connection). `get_draft_order_method()` uses the existing `get_setting` helper (safe: the sequence functions call it in read contexts / before any write).
- **Never** `git add -A`; stage explicit paths only. Never commit `*.db` or `backups/`. Do NOT push.
- `import random` is **not currently imported** — add it. `random.shuffle` runs in a normal Flask request (app code, not a workflow script).
- Match existing route/template style.

## File Structure

- `app.py` — 3 accessors; internal order-method resolution in the sequence fns; roster/first-pick wiring in `draft_live_pick`; a `randomize_order` admin-draft action; `import random`; `first_pick_regular` in the checkbox force-0 loop.
- `templates/admin/settings.html` — new "Draft Structure" section.
- `templates/admin/draft.html` — a "Randomize order" button.
- `tests/test_draft_structure.py` — NEW: accessor + equivalence + rule tests.
- `tests/test_settings_page.py` — extend for the new section.

---

## Task 1: Config accessors (behavior-preserving defaults)

**Files:**
- Modify: `app.py` (add `import random` to the top imports; add accessors after `get_setting`, ~line 600)
- Test: `tests/test_draft_structure.py`

**Interfaces:**
- Produces:
  - `get_roster_size(db) -> int` (default 10)
  - `get_first_pick_regular(db) -> bool` (default True)
  - `get_draft_order_method() -> str` (`'snake'` default | `'linear'`; no db arg — uses `get_setting`)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_draft_structure.py
"""B2: configurable roster size / first-pick / draft-order, defaults reproduce today."""


def test_defaults_reproduce_current_behavior(app_mod):
    with app_mod.get_db() as db:
        assert app_mod.get_roster_size(db) == 10
        assert app_mod.get_first_pick_regular(db) is True
    assert app_mod.get_draft_order_method() == "snake"


def test_accessors_read_stored_values(app_mod):
    with app_mod.get_db() as db:
        for k, v in [("roster_size", "12"), ("first_pick_regular", "0"),
                     ("draft_order_method", "linear")]:
            db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)", (k, v))
    with app_mod.get_db() as db:
        assert app_mod.get_roster_size(db) == 12
        assert app_mod.get_first_pick_regular(db) is False
    assert app_mod.get_draft_order_method() == "linear"


def test_roster_size_bad_value_falls_back_to_10(app_mod):
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('roster_size', 'oops')")
        assert app_mod.get_roster_size(db) == 10
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_structure.py -v`
Expected: FAIL (accessors undefined).

- [ ] **Step 3: Add `import random` and the accessors**

Add `import random` to the top imports of `app.py` (next to `import os`). Then add after `get_setting`:

```python
def get_roster_size(db):
    """Max picks per team (default 10 — reproduces the hardcoded cap)."""
    row = db.execute("SELECT value FROM league_settings WHERE key='roster_size'").fetchone()
    try:
        return int(row["value"]) if row and row["value"] else 10
    except (ValueError, TypeError):
        return 10


def get_first_pick_regular(db):
    """Whether the first overall pick must be a regular-tier mon (default True)."""
    row = db.execute("SELECT value FROM league_settings WHERE key='first_pick_regular'").fetchone()
    return (row["value"] if row else "1") != "0"


def get_draft_order_method():
    """'snake' (default, reverses each pass) or 'linear' (same order every pass).
    No db arg — resolves via get_setting so the pure sequence fns can call it."""
    return "linear" if get_setting("draft_order_method", "snake") == "linear" else "snake"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_structure.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_draft_structure.py
git commit -m "feat: draft-structure config accessors (roster size / first-pick / order)"
```

---

## Task 2: Configurable draft order method (snake / linear), resolved internally

Because `_get_pool_sequence` has 7 call sites, the method is resolved **inside** the sequence functions (default arg `None` → read the setting) so **no call site changes**.

**Files:**
- Modify: `app.py` — `_get_snake_pick_sequence` (lines 4715-4726), `_get_pool_sequence` (lines 4729-4732). **No call sites change.**
- Test: `tests/test_draft_structure.py`

**Interfaces:**
- Consumes: `get_draft_order_method()` (Task 1).
- Produces: `_get_snake_pick_sequence(snake_order, round_structure, order_method=None)` and `_get_pool_sequence(snake_order, pool_coach_ids, round_structure, order_method=None)`; `None` resolves to the configured method.

- [ ] **Step 1: Write failing tests**

```python
# add to tests/test_draft_structure.py
def test_snake_sequence_default_matches_current(app_mod):
    # default (no setting) resolves to snake -> reproduces existing reversal behavior.
    seq = app_mod._get_snake_pick_sequence([1, 2, 3], [{"name": "R1", "picks_per_coach": 2}])
    coaches = [c for (_pn, _ri, _sn, c) in seq]
    assert coaches == [1, 2, 3, 3, 2, 1]  # pass0 forward, pass1 reversed


def test_linear_sequence_no_reversal(app_mod):
    seq = app_mod._get_snake_pick_sequence([1, 2, 3], [{"name": "R1", "picks_per_coach": 2}], "linear")
    coaches = [c for (_pn, _ri, _sn, c) in seq]
    assert coaches == [1, 2, 3, 1, 2, 3]  # every pass forward


def test_sequence_resolves_setting_when_method_none(app_mod):
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('draft_order_method', 'linear')")
    seq = app_mod._get_pool_sequence([1, 2, 3, 4], {1, 3}, [{"name": "R1", "picks_per_coach": 2}])
    coaches = [c for (_pn, _ri, _sn, c) in seq]
    assert coaches == [1, 3, 1, 3]  # linear resolved from the setting, no reversal
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_structure.py -k "sequence" -v`
Expected: FAIL (functions take 2 args / don't resolve the setting).

- [ ] **Step 3: Rewrite the two sequence functions**

Replace `_get_snake_pick_sequence` (lines 4715-4726) with:

```python
def _get_snake_pick_sequence(snake_order, round_structure, order_method=None):
    """Flat list of (pick_number, round_idx, slot_name, coach_id).
    order_method 'snake' reverses each alternate pass; 'linear' keeps the same order.
    None resolves to the configured draft_order_method (default 'snake')."""
    if order_method is None:
        order_method = get_draft_order_method()
    picks = []
    pick_num = 1
    for round_idx, rnd in enumerate(round_structure):
        picks_per = rnd["picks_per_coach"]
        for pass_num in range(picks_per):
            if order_method == "linear":
                order = snake_order
            else:
                order = snake_order if (round_idx * picks_per + pass_num) % 2 == 0 else list(reversed(snake_order))
            for coach_id in order:
                picks.append((pick_num, round_idx, rnd["name"], coach_id))
                pick_num += 1
    return picks
```

Replace `_get_pool_sequence` (lines 4729-4732) with:

```python
def _get_pool_sequence(snake_order, pool_coach_ids, round_structure, order_method=None):
    """Snake/linear sequence for a single pool (filters snake_order to pool coaches)."""
    pool_order = [c for c in snake_order if c in pool_coach_ids]
    return _get_snake_pick_sequence(pool_order, round_structure, order_method)
```

**Do not change any call site** — all callers pass `order_method` implicitly as `None`, which resolves to the setting.

- [ ] **Step 4: Run the sequence tests + full suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_structure.py -v && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (all existing draft-flow tests still green — default resolves to snake).

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_draft_structure.py
git commit -m "feat: configurable draft order method (snake/linear), resolved internally, default snake"
```

---

## Task 3: Configurable roster size + first-pick rule (in draft_live_pick)

**Files:**
- Modify: `app.py` — first-pick rule (lines 5391-5394), roster cap (lines 5396-5402), makeup room check (line 5514)
- Test: `tests/test_draft_structure.py`

**Interfaces:**
- Consumes: `get_roster_size(db)`, `get_first_pick_regular(db)` (Task 1). Read inside `draft_live_pick` using its already-open `db`, **before** any INSERT, and the `roster_size` value is reused at the makeup check.

- [ ] **Step 1: Write the rule tests**

`draft_live_pick` is the POST at `/draft/live/pick`. Set up a minimal single-coach active session so coach 1 is on the clock at pick 1, then assert the cap/rule respond to the settings.

```python
# add to tests/test_draft_structure.py
import json as _json


def _count_roster(app_mod):
    with app_mod.get_db() as db:
        return db.execute("SELECT COUNT(*) FROM pokemon_roster").fetchone()[0]


def _setup_single_coach_draft(app_mod, mons):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM draft_tiers")
        db.execute("DELETE FROM pokemon_roster"); db.execute("DELETE FROM draft_sessions")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (1,'C','T','A')")
        for name, pts in mons:
            db.execute("INSERT INTO draft_tiers (name, points) VALUES (?,?)", (name, pts))
        db.execute("INSERT INTO draft_sessions (name, status, snake_order, current_pick_a) "
                   "VALUES ('S','active',?,1)", (_json.dumps([1]),))


def test_roster_cap_uses_setting(client, app_mod):
    _setup_single_coach_draft(app_mod, [("Garchomp", 18)])
    with app_mod.get_db() as db:
        db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name, points) VALUES (1,'A',1),(1,'B',1)")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('roster_size','2')")
    before = _count_roster(app_mod)
    client.post("/draft/live/pick", data={"pokemon_name": "Garchomp", "pick_pool": "A"})
    assert _count_roster(app_mod) == before  # cap hit at 2 -> pick rejected


def test_first_pick_rule_on_blocks_zero_point(client, app_mod):
    _setup_single_coach_draft(app_mod, [("ZeroMon", 0)])   # first_pick_regular defaults ON
    client.post("/draft/live/pick", data={"pokemon_name": "ZeroMon", "pick_pool": "A"})
    assert _count_roster(app_mod) == 0  # 0-pt first pick blocked by the (default-on) rule


def test_first_pick_rule_off_allows_zero_point(client, app_mod):
    _setup_single_coach_draft(app_mod, [("ZeroMon", 0)])
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('first_pick_regular','0')")
    client.post("/draft/live/pick", data={"pokemon_name": "ZeroMon", "pick_pool": "A"})
    assert _count_roster(app_mod) == 1  # rule OFF -> 0-pt first pick allowed
```

Note: if `draft_live_pick` rejects for an unrelated reason (e.g. it needs a column the minimal session lacks), the implementer inspects the route and extends `_setup_single_coach_draft` so coach 1 is validly on the clock for pick 1 (all draft_sessions columns have schema defaults). The three assertions must isolate the cap / first-pick behavior. If the pick endpoint path differs, grep `@app.route` for it.

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_structure.py -k "cap or first_pick" -v`
Expected: FAIL for `test_roster_cap_uses_setting` (cap still hardcoded 10, so 2 picks is under the cap → pick accepted → count changes) and for `test_first_pick_rule_off_allows_zero_point` (rule hardcoded on → 0-pt blocked). `test_first_pick_rule_on_blocks_zero_point` may already pass (rule is on by default).

- [ ] **Step 3: Wire the settings in `draft_live_pick`**

Replace the first-pick rule (currently lines 5391-5394):
```python
        # First overall pick must be a regular-tier pokemon (not mega, must have pts ≥ 1)
        if pick_num == 1 and (is_mega or points < 1):
            flash("The first pick must be a regular-tier Pokemon (not Mega).", "warning")
            return redirect(url_for("draft_live"))
```
with:
```python
        # First overall pick must be a regular-tier pokemon (not mega, pts ≥ 1) — configurable.
        if get_first_pick_regular(db) and pick_num == 1 and (is_mega or points < 1):
            flash("The first pick must be a regular-tier Pokemon (not Mega).", "warning")
            return redirect(url_for("draft_live"))
```

Replace the roster cap (currently lines 5396-5402):
```python
        # Enforce max 10 picks per team (8 regular + 2 uber)
        team_pick_count = db.execute(
            "SELECT COUNT(*) FROM pokemon_roster WHERE coach_id=?", (coach_id,)
        ).fetchone()[0]
        if team_pick_count >= 10:
            flash(f"This team already has {team_pick_count} picks (max 10).", "warning")
            return redirect(url_for("draft_live"))
```
with:
```python
        # Enforce the roster cap (configurable; default 10).
        roster_size = get_roster_size(db)
        team_pick_count = db.execute(
            "SELECT COUNT(*) FROM pokemon_roster WHERE coach_id=?", (coach_id,)
        ).fetchone()[0]
        if team_pick_count >= roster_size:
            flash(f"This team already has {team_pick_count} picks (max {roster_size}).", "warning")
            return redirect(url_for("draft_live"))
```

Replace the makeup room check (currently line 5514):
```python
        has_room = (team_pick_count + 1) < 10
```
with:
```python
        has_room = (team_pick_count + 1) < roster_size
```
(`roster_size` is already in scope from the cap block — same function, computed before the INSERTs.)

- [ ] **Step 4: Run the rule tests + full suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_structure.py -v && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_draft_structure.py
git commit -m "feat: configurable roster size + first-pick rule (defaults reproduce today)"
```

---

## Task 4: Randomize-order admin helper

**Files:**
- Modify: `app.py` — a `randomize_order` action in the `admin_draft` POST handler (near `create_session`, ~line 5779)
- Modify: `templates/admin/draft.html` — a "Randomize order" button in the SESSION_CONTROLS panel
- Test: `tests/test_draft_structure.py`

**Interfaces:**
- Consumes: `import random` (Task 1). Produces POST action `randomize_order` (form `session_id`) shuffling `draft_sessions.snake_order`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_draft_structure.py
def test_randomize_order_permutes_snake(client, app_mod):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_sessions")
        db.execute("INSERT INTO draft_sessions (id, name, status, snake_order) "
                   "VALUES (7,'S','setup','[1, 2, 3, 4, 5, 6, 7, 8]')")
    client.post("/admin/draft", data={"action": "randomize_order", "session_id": "7"})
    with app_mod.get_db() as db:
        so = _json.loads(db.execute("SELECT snake_order FROM draft_sessions WHERE id=7").fetchone()["snake_order"])
    assert sorted(so) == [1, 2, 3, 4, 5, 6, 7, 8]  # same members, permutation preserved
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_structure.py -k randomize -v`
Expected: FAIL (no `randomize_order` action).

- [ ] **Step 3: Add the action to `admin_draft`**

Add a branch alongside the other `elif action == ...` branches in the `admin_draft` POST handler (e.g. right after the `create_session` branch):

```python
        elif action == "randomize_order":
            sid = request.form.get("session_id")
            with get_db() as db:
                row = db.execute("SELECT snake_order FROM draft_sessions WHERE id=?", (sid,)).fetchone()
                if row:
                    ids = json.loads(row["snake_order"] or "[]")
                    random.shuffle(ids)
                    db.execute("UPDATE draft_sessions SET snake_order=? WHERE id=?",
                               (json.dumps(ids), sid))
                    flash("Draft order randomized.", "success")
            return redirect(url_for("admin_draft"))
```

- [ ] **Step 4: Add the button to `templates/admin/draft.html`**

Inside the `<details>` "SESSION_CONTROLS" panel (near the SET / MARK COMPLETE / RESET forms), add:

```html
    <form method="POST" onsubmit="return confirm('Randomize the draft order for this session?')">
      <input type="hidden" name="action" value="randomize_order">
      <input type="hidden" name="session_id" value="{{ active_session.id }}">
      <button type="submit" class="ad-btn ad-btn-ghost">🎲 RANDOMIZE ORDER</button>
    </form>
```

- [ ] **Step 5: Run the test + full suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_structure.py -v && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py templates/admin/draft.html tests/test_draft_structure.py
git commit -m "feat: randomize draft order admin helper"
```

---

## Task 5: Draft Structure settings section

**Files:**
- Modify: `app.py` — add `first_pick_regular` to the checkbox force-0 loop in `admin_settings`
- Modify: `templates/admin/settings.html` — add a "Draft Structure" section
- Test: `tests/test_settings_page.py`

**Interfaces:**
- Consumes: the unchanged `admin_settings` POST loop (persists `roster_size`, `draft_order_method`); `first_pick_regular` needs force-0 handling (Step 3).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_settings_page.py
def test_has_draft_structure_inputs(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "Draft Structure" in html
    for f in ["roster_size", "first_pick_regular", "draft_order_method"]:
        assert f'name="{f}"' in html


def test_draft_structure_persists(client, app_mod):
    client.post("/admin/settings", data={
        "league_name": "X", "roster_size": "12",
        "draft_order_method": "linear",  # first_pick_regular omitted -> stored "0"
    })
    with app_mod.get_db() as db:
        got = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM league_settings")}
    assert got.get("roster_size") == "12"
    assert got.get("draft_order_method") == "linear"
    assert got.get("first_pick_regular") == "0"
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -k "draft_structure" -v`
Expected: FAIL (`Draft Structure` section absent; `first_pick_regular` not force-0'd).

- [ ] **Step 3: Add `first_pick_regular` to the checkbox force-0 loop in `app.py`**

In `admin_settings` (POST), the loop that forces unchecked checkboxes to "0" currently lists the four `mechanic_*` keys. Add `"first_pick_regular"`:

```python
            for checkbox_key in ("mechanic_mega", "mechanic_tera", "mechanic_zmove", "mechanic_uber", "first_pick_regular"):
```

- [ ] **Step 4: Add the Draft Structure section to `templates/admin/settings.html`**

Insert this `<section>` immediately **before** the `<!-- ── Mega Tiers` section:

```html
  <!-- ── Draft Structure ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-4">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Draft Structure</h2>
    {{ txt('roster_size', 'Roster Size (max picks per team)', 'number', '10') }}
    <label class="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" name="first_pick_regular" value="1" {% if settings.get('first_pick_regular','1') != '0' %}checked{% endif %} class="w-4 h-4 accent-yellow-500">
      <span class="text-sm text-gray-300">First overall pick must be a regular-tier Pokémon (not Mega / 0-pt)</span>
    </label>
    <div>
      <label class="block text-sm font-semibold text-gray-300 mb-1">Draft Order</label>
      <div class="flex gap-3">
        <label class="flex items-center gap-2 cursor-pointer px-4 py-2.5 rounded-lg border transition-colors
                      {% if settings.get('draft_order_method','snake') != 'linear' %}border-yellow-500 bg-yellow-500/10{% else %}border-gray-600 bg-gray-800{% endif %}">
          <input type="radio" name="draft_order_method" value="snake" {% if settings.get('draft_order_method','snake') != 'linear' %}checked{% endif %} class="accent-yellow-500">
          <span class="text-white font-semibold">Snake</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer px-4 py-2.5 rounded-lg border transition-colors
                      {% if settings.get('draft_order_method') == 'linear' %}border-yellow-500 bg-yellow-500/10{% else %}border-gray-600 bg-gray-800{% endif %}">
          <input type="radio" name="draft_order_method" value="linear" {% if settings.get('draft_order_method') == 'linear' %}checked{% endif %} class="accent-yellow-500">
          <span class="text-white font-semibold">Linear</span>
        </label>
      </div>
      <p class="text-xs text-gray-500 mt-1">Snake reverses each pass; Linear keeps the same order every round. Use <a href="/admin/draft" class="text-yellow-400 hover:underline">Admin → Draft</a> to randomize the order.</p>
    </div>
  </section>
```

- [ ] **Step 5: Run the settings tests + full suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -v && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (B1 contract tests still pass; new draft-structure tests pass).

- [ ] **Step 6: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py templates/admin/settings.html tests/test_settings_page.py
git commit -m "feat: Draft Structure settings section (roster size / first-pick / order)"
```

---

## Notes for the implementer
- The **at-a-glance** panel in `settings.html` still lists "Roster cap: 10 picks … First pick must be regular-tier"; those are now configurable. Leave it as documentation of the *default* (a reviewer may optionally suggest trimming those two lines) — do not change behavior.
- Uber-slot count (`uber_picks_per_team`) and the tier-definitions refactor are **out of scope** for B2 — they are B3.
- Every change is guarded by a default reproducing the current value; if any equivalence test shows a diff at defaults, stop — the refactor changed behavior.
