# Phase 1B-4: Configurable Draft-Mode Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a league-wide **draft-mode policy** — `combination` (per-coach, today's behavior), `only_points`, or `only_tickets` — that forces all Griffin coaches to one draft mode, with a default that reproduces this season byte-for-byte.

**Architecture:** A `get_draft_mode_policy()` accessor (default `combination`) plus a pure `_apply_mode_policy(mode, draft_format)` helper that overrides the computed mode **only** when the policy forces one and the format is Griffin. It is applied as a post-computation override at the three places the per-coach draft mode is resolved (`_effective_draft_mode`, `_get_coach_draft_state`, `draft_live_pick`) — each site's existing default computation is left untouched, so at the default policy nothing changes. Equivalence tests prove identity at default and the override under a forced policy.

**Tech Stack:** Python 3 / Flask / SQLite; pytest (existing harness); Jinja2 + Tailwind.

Slice **B4** of Phase 1B (spec `docs/superpowers/specs/2026-06-30-settings-rework-and-draft-board-templates-design.md`, §5.4 Draft Mode). **Battle Mechanics & Captains config (incl. Dynamax) is deferred to its own slice (B5)** — it mirrors the Z-Move captain across 22+ sites and warrants isolation. Standings + transactions follow.

## Global Constraints

- Run Python only via `./.venv/Scripts/python.exe` (from `D:/Yuri Draft League`). Never base python.
- **Behavior-preservation:** with the policy unset/`combination`, every draft-mode resolution is byte-for-byte unchanged. The override only fires for `only_points`/`only_tickets` under Griffin format. Never change a site's existing default computation.
- `get_draft_mode_policy()` uses the existing `get_setting` helper (no db arg); `_apply_mode_policy` is a pure function.
- **Never** `git add -A`; stage explicit paths only. Never commit `*.db` or `backups/`. Do NOT push.
- Match existing route/template style.

## File Structure

- `app.py` — `get_draft_mode_policy()` + `_apply_mode_policy()`; apply at 3 sites; `admin_settings` writes nothing new (the policy is a plain radio persisted by the generic loop).
- `templates/admin/settings.html` — a "Draft Mode" section (radio).
- `tests/test_draft_mode_policy.py` — NEW.
- `tests/test_settings_page.py` — extend for the new section.

---

## Task 1: Policy accessor + override helper

**Files:**
- Modify: `app.py` — add `get_draft_mode_policy()` after `get_setting`, and `_apply_mode_policy()` just before `_effective_draft_mode` (line 128)
- Test: `tests/test_draft_mode_policy.py`

**Interfaces:**
- Produces:
  - `get_draft_mode_policy() -> str` (`'combination'` default | `'only_points'` | `'only_tickets'`)
  - `_apply_mode_policy(mode, draft_format) -> str`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_draft_mode_policy.py
"""B4: league-wide draft-mode policy; default reproduces per-coach behavior."""


def test_policy_default_is_combination(app_mod):
    assert app_mod.get_draft_mode_policy() == "combination"


def test_apply_mode_policy_combination_is_identity(app_mod):
    # default (combination) never overrides
    assert app_mod._apply_mode_policy("tier_tickets", "griffin") == "tier_tickets"
    assert app_mod._apply_mode_policy("points", "griffin") == "points"
    assert app_mod._apply_mode_policy("legacy", "griffin") == "legacy"


def test_apply_mode_policy_forces_under_griffin(app_mod):
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('draft_mode_policy','only_points')")
    assert app_mod._apply_mode_policy("tier_tickets", "griffin") == "points"
    # non-griffin format is never overridden (legacy stays legacy)
    assert app_mod._apply_mode_policy("legacy", "") == "legacy"


def test_apply_mode_policy_only_tickets(app_mod):
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('draft_mode_policy','only_tickets')")
    assert app_mod._apply_mode_policy("points", "griffin") == "tier_tickets"
    assert app_mod._apply_mode_policy("points", "") == "points"  # not griffin -> unchanged
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_mode_policy.py -v`
Expected: FAIL (functions undefined).

- [ ] **Step 3: Add the accessor and helper**

Add after `get_setting` (~line 600):
```python
def get_draft_mode_policy():
    """League draft-mode policy: 'combination' (per-coach, default), 'only_points',
    or 'only_tickets'. Only 'only_points'/'only_tickets' change behavior, and only
    for Griffin coaches (see _apply_mode_policy)."""
    v = get_setting("draft_mode_policy", "combination")
    return v if v in ("combination", "only_points", "only_tickets") else "combination"
```

Add immediately before `def _effective_draft_mode` (line 128):
```python
def _apply_mode_policy(mode, draft_format):
    """Override a per-coach draft mode when the league forces one. Only applies to
    Griffin format; the default 'combination' policy returns mode unchanged."""
    if draft_format == "griffin":
        policy = get_draft_mode_policy()
        if policy == "only_points":
            return "points"
        if policy == "only_tickets":
            return "tier_tickets"
    return mode
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_mode_policy.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_draft_mode_policy.py
git commit -m "feat: draft-mode policy accessor + override helper (default combination)"
```

---

## Task 2: Apply the policy at the three draft-mode resolution sites

**Files:**
- Modify: `app.py` — `_effective_draft_mode` (lines 128-131); `_get_coach_draft_state` (the `mode = ...` line); `draft_live_pick` (the `coach_mode = ...` line, ~5505)
- Test: `tests/test_draft_mode_policy.py`

**Interfaces:**
- Consumes: `_apply_mode_policy` (Task 1). No signatures change.

- [ ] **Step 1: Write equivalence + integration tests**

```python
# add to tests/test_draft_mode_policy.py
def test_effective_mode_default_unchanged(app_mod):
    coach = {"draft_mode": "tier_tickets"}
    assert app_mod._effective_draft_mode(coach, "griffin") == "tier_tickets"   # default policy
    assert app_mod._effective_draft_mode({"draft_mode": None}, "griffin") == "tier_tickets"
    assert app_mod._effective_draft_mode({"draft_mode": "points"}, "") == "legacy"  # non-griffin


def test_effective_mode_forced_by_policy(app_mod):
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('draft_mode_policy','only_points')")
    assert app_mod._effective_draft_mode({"draft_mode": "tier_tickets"}, "griffin") == "points"
    assert app_mod._effective_draft_mode({"draft_mode": "tier_tickets"}, "") == "legacy"  # legacy fmt untouched


def test_coach_draft_state_respects_policy(app_mod):
    # Under only_points + griffin, a tier_tickets coach's state is the POINTS branch (has 'remaining').
    with app_mod.get_db() as db:
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM draft_sessions")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool, draft_mode) VALUES (1,'C','T','A','tier_tickets')")
        db.execute("INSERT INTO draft_sessions (id, name, status) VALUES (1,'S','active')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('draft_format','griffin')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('draft_mode_policy','only_points')")
        st = app_mod._get_coach_draft_state(db, 1, 1)
    assert st["mode"] == "points" and "remaining" in st and "remaining_tickets" not in st
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_mode_policy.py -k "effective or coach_draft_state" -v`
Expected: the `forced`/`respects_policy` tests FAIL (the sites don't apply the policy yet); the `default_unchanged` test passes.

- [ ] **Step 3: Apply the policy at each site**

**`_effective_draft_mode`** — replace lines 128-131:
```python
def _effective_draft_mode(coach, draft_format):
    if draft_format != "griffin":
        return "legacy"
    return (coach["draft_mode"] or "tier_tickets")
```
with:
```python
def _effective_draft_mode(coach, draft_format):
    if draft_format != "griffin":
        return "legacy"
    return _apply_mode_policy(coach["draft_mode"] or "tier_tickets", draft_format)
```

**`_get_coach_draft_state`** — find the line:
```python
    mode = (coach["draft_mode"] or "legacy") if coach else "legacy"
```
and replace with:
```python
    mode = (coach["draft_mode"] or "legacy") if coach else "legacy"
    mode = _apply_mode_policy(mode, get_setting("draft_format", ""))
```

**`draft_live_pick`** — find the line (~5505):
```python
        coach_mode = (coach_mode_row["draft_mode"] or "legacy") if coach_mode_row else "legacy"
```
and replace with:
```python
        coach_mode = (coach_mode_row["draft_mode"] or "legacy") if coach_mode_row else "legacy"
        coach_mode = _apply_mode_policy(coach_mode, get_setting("draft_format", ""))
```

(All three sites now apply the override; at the default `combination` policy each returns the same value as before.)

- [ ] **Step 4: Run the tests + full suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_draft_mode_policy.py -v && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass (equivalence at default; forced override under policy; nothing else regresses).

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_draft_mode_policy.py
git commit -m "feat: apply draft-mode policy at the three mode-resolution sites"
```

---

## Task 3: Draft Mode settings section

**Files:**
- Modify: `templates/admin/settings.html` — a "Draft Mode Policy" section (radio, persisted by the generic loop)
- Test: `tests/test_settings_page.py`

**Interfaces:** the plain `draft_mode_policy` key is persisted by the existing `admin_settings` POST loop — no route change.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_settings_page.py
def test_has_draft_mode_policy(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "Draft Mode Policy" in html
    assert 'name="draft_mode_policy"' in html


def test_draft_mode_policy_persists(client, app_mod):
    client.post("/admin/settings", data={"league_name": "X", "draft_mode_policy": "only_points"})
    with app_mod.get_db() as db:
        got = db.execute("SELECT value FROM league_settings WHERE key='draft_mode_policy'").fetchone()["value"]
    assert got == "only_points"
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -k "draft_mode_policy" -v`
Expected: FAIL (section absent).

- [ ] **Step 3: Add the section to `templates/admin/settings.html`**

Insert this `<section>` immediately **after** the `<!-- ── Draft Format & Budget ──` section's closing `</section>` (before Tier Definitions):

```html
  <!-- ── Draft Mode Policy ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-3">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Draft Mode Policy</h2>
    <p class="text-xs text-gray-500">Under Plan Griffin, force every coach to one draft mode, or leave it per-coach.</p>
    <div class="flex flex-col gap-2">
      {% set pol = settings.get('draft_mode_policy', 'combination') %}
      {% for val, label, desc in [
        ('combination', 'Combination (per-coach)', 'Each coach uses their own Tier Tickets / Points setting (default).'),
        ('only_points', 'Only Points', 'All coaches draft with a points budget.'),
        ('only_tickets', 'Only Tier Tickets', 'All coaches draft with tier tickets.'),
      ] %}
      <label class="flex items-center gap-3 cursor-pointer px-4 py-2.5 rounded-lg border transition-colors
                    {% if pol == val %}border-yellow-500 bg-yellow-500/10{% else %}border-gray-700 bg-gray-800{% endif %}">
        <input type="radio" name="draft_mode_policy" value="{{ val }}" {% if pol == val %}checked{% endif %} class="accent-yellow-500">
        <div><span class="text-white font-semibold block text-sm">{{ label }}</span><span class="text-xs text-gray-500">{{ desc }}</span></div>
      </label>
      {% endfor %}
    </div>
  </section>
```

- [ ] **Step 4: Run the settings tests + full suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -v && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add templates/admin/settings.html tests/test_settings_page.py
git commit -m "feat: Draft Mode Policy settings section"
```

---

## Notes for the implementer
- **Behavior-preservation:** the override is additive — each site keeps its existing default computation, and `_apply_mode_policy` returns the input unchanged at the default `combination` policy. If any test shows a diff at default, stop.
- The policy only affects Griffin format; legacy format always resolves to `legacy` regardless of the policy.
- **Out of scope (B5):** Battle Mechanics & Captains config (`mechanic_config`, Dynamax, usage modes, tax). Standings + transactions after.
