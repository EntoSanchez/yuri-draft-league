# Draft Board Templates + DB Backup/Restore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins save/load/edit the draft board as named templates (with auto restore-points and load-safety guards), and create/restore timestamped backups of the whole database.

**Architecture:** Two self-contained admin features added to the existing Flask monolith (`app.py`) following its current patterns (`@admin_required` routes, the `get_db()` context manager, `render_template` + Tailwind admin pages). Board templates are JSON snapshots of `draft_tiers` in a new `draft_board_templates` table; DB backups are timestamped file copies of `DB_PATH` in a git-ignored `backups/` dir. This is Plan 1 of 2 from the spec (`docs/superpowers/specs/2026-06-30-settings-rework-and-draft-board-templates-design.md`, Phases 1A + 1C); the configuration-driven settings page (Phase 1B) is a later plan.

**Tech Stack:** Python 3 / Flask / SQLite (stdlib `sqlite3`, `shutil`, `json`, `datetime`), Jinja2 + Tailwind (CDN), pytest (new dev dependency).

## Global Constraints

- Run Python through the project venv: `D:/Yuri Draft League/.venv/Scripts/python.exe` (Windows). Never the base interpreter.
- **Never** `git add -A`; stage explicit paths only. **Never** commit `*.db` or the `backups/` dir.
- Push (when asked) with `git push origin HEAD:master`.
- All DB access goes through `with get_db() as db:` (auto commit/rollback) — **except** the DB-restore file swap, which must hold **no** open connection to `DB_PATH` (Windows file lock).
- Back up / restore **`app.DB_PATH`** (env-driven) — never a hardcoded path (prod uses a nested `league.db`).
- Match existing route style: `@app.route(..., methods=[...])` + `@admin_required`, `flash(...)`, `return redirect(url_for(...))`, `render_template("admin/<x>.html", ..., league_name=get_setting("league_name", "Pokemon Draft League"))`.
- Admin templates: `{% extends "base.html" %}{% block title %}…{% endblock %}{% block content %}…{% endblock %}`, Tailwind classes, a `← Admin` back link.
- Bump the `base.html` build marker on the deploy commit.

---

## Task 0: Test harness (pytest + temp-DB fixture)

No tests exist yet. This harness underpins every later task: a throwaway SQLite DB per test session, the real schema, and an admin-authenticated test client.

**Files:**
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Create: `tests/test_harness.py`
- Modify: `pyproject.toml` (add pytest dev dep) — or create if absent

**Interfaces:**
- Produces: pytest fixtures `db_path` (str path to the temp DB), `app_mod` (the imported `app` module), `client` (admin-authenticated `FlaskClient`). Later tasks consume `client` and `app_mod`.

- [ ] **Step 1: Add pytest as a dev dependency**

Run:
```bash
cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pip install pytest
```
Expected: `Successfully installed pytest-...`

- [ ] **Step 2: Write `tests/conftest.py`**

```python
import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "test_league.db")


@pytest.fixture()
def app_mod(db_path, monkeypatch):
    # Point both init_db and app at the temp DB BEFORE importing them.
    monkeypatch.setenv("DB_PATH", db_path)
    import init_db
    importlib.reload(init_db)
    init_db.DB_PATH = db_path
    init_db.init_db()  # create base schema in the temp DB
    import app as app_module
    importlib.reload(app_module)  # re-imports with DB_PATH set; runs _migrate_db()
    app_module.DB_PATH = db_path
    app_module.app.config["TESTING"] = True
    return app_module


@pytest.fixture()
def client(app_mod):
    c = app_mod.app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["role"] = "admin"
    return c
```

- [ ] **Step 3: Write a smoke test in `tests/test_harness.py`**

```python
def test_admin_can_reach_tiers_page(client):
    resp = client.get("/admin/tiers")
    assert resp.status_code == 200


def test_temp_db_has_draft_tiers_table(app_mod):
    with app_mod.get_db() as db:
        cols = [r["name"] for r in db.execute("PRAGMA table_info(draft_tiers)")]
    assert "points" in cols and "is_banned" in cols
```

- [ ] **Step 4: Add `tests/__init__.py` (empty) and run the harness**

Run:
```bash
cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_harness.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add tests/conftest.py tests/test_harness.py tests/__init__.py
git commit -m "test: add pytest harness with temp-DB admin client"
```

---

## Task 1: Migration — `draft_board_templates` table

**Files:**
- Modify: `app.py` (the `_migrate_db()` ALTER/CREATE block, around lines 48–62)
- Test: `tests/test_board_templates.py`

**Interfaces:**
- Produces: table `draft_board_templates(id, name, kind, notes, board_json, created_at, updated_at)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_board_templates.py
def test_board_templates_table_exists(app_mod):
    with app_mod.get_db() as db:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(draft_board_templates)")}
    assert {"id", "name", "kind", "notes", "board_json", "created_at", "updated_at"} <= cols
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates.py::test_board_templates_table_exists -v`
Expected: FAIL (no such table).

- [ ] **Step 3: Add the CREATE TABLE to `_migrate_db()`**

`_migrate_db()` runs `for stmt in [ <list of statements> ]: try: db.execute(stmt) except: pass` — an idempotent migration loop. Add the `CREATE TABLE IF NOT EXISTS` as **one more entry in that list** (a triple-quoted string), e.g. right after the last `ALTER TABLE match_games ...` line:

```python
            "ALTER TABLE match_games ADD COLUMN recap_json TEXT",
            """CREATE TABLE IF NOT EXISTS draft_board_templates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                kind        TEXT NOT NULL DEFAULT 'manual',
                notes       TEXT DEFAULT '',
                board_json  TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )""",
```

A multi-line `CREATE TABLE` is a single SQLite statement, so it runs cleanly via `db.execute`; `IF NOT EXISTS` makes it safe to re-run.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_board_templates.py
git commit -m "feat: add draft_board_templates table migration"
```

---

## Task 2: Board snapshot / load / prune helpers

Pure-ish functions the routes build on. Kept separate so they're unit-tested without HTTP.

**Files:**
- Modify: `app.py` (add helpers after `get_setting`, ~line 600; ensure `import datetime` near the top imports)
- Test: `tests/test_board_templates.py`

**Interfaces:**
- Produces:
  - `save_board_template(db, name, kind="manual", notes="") -> int` (new template id)
  - `load_board_template(db, template_id) -> int` (rows restored; raises `ValueError` if missing)
  - `prune_autobackups(db, keep=10) -> None`
  - `_now_iso() -> str`

- [ ] **Step 1: Write failing tests**

```python
# add to tests/test_board_templates.py
def _seed_board(db):
    db.execute("DELETE FROM draft_tiers")
    db.execute("INSERT INTO draft_tiers (name, points, tier_label, is_mega) VALUES (?,?,?,?)",
               ("Garchomp", 18, "Tier 1", 0))
    db.execute("INSERT INTO draft_tiers (name, points, is_mega) VALUES (?,?,?)",
               ("Mega Garchomp", 24, 1))


def test_save_then_load_roundtrips_board(app_mod):
    with app_mod.get_db() as db:
        _seed_board(db)
        tid = app_mod.save_board_template(db, "Base S8")
        db.execute("DELETE FROM draft_tiers")           # wipe live board
        n = app_mod.load_board_template(db, tid)
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert n == 2 and names == {"Garchomp", "Mega Garchomp"}


def test_load_missing_template_raises(app_mod):
    import pytest
    with app_mod.get_db() as db:
        with pytest.raises(ValueError):
            app_mod.load_board_template(db, 99999)


def test_prune_keeps_only_recent_autobackups(app_mod):
    with app_mod.get_db() as db:
        _seed_board(db)
        for _ in range(13):
            app_mod.save_board_template(db, "auto", kind="autobackup")
        app_mod.prune_autobackups(db, keep=10)
        cnt = db.execute(
            "SELECT COUNT(*) FROM draft_board_templates WHERE kind='autobackup'").fetchone()[0]
    assert cnt == 10
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates.py -v`
Expected: FAIL (helpers not defined).

- [ ] **Step 3: Add the helpers to `app.py`**

`app.py` already imports `from datetime import datetime` (line 10), so use `datetime.now()` (not `datetime.datetime.now()`). Add after `get_setting`:

```python
def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def save_board_template(db, name, kind="manual", notes=""):
    """Snapshot the live draft_tiers into a template row; return its id."""
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM draft_tiers ORDER BY points DESC, name")]
    ts = _now_iso()
    cur = db.execute(
        "INSERT INTO draft_board_templates (name, kind, notes, board_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?)",
        (name, kind, notes, json.dumps(rows), ts, ts))
    return cur.lastrowid


def load_board_template(db, template_id):
    """Replace draft_tiers with the template's snapshot. Returns row count."""
    row = db.execute(
        "SELECT board_json FROM draft_board_templates WHERE id=?", (template_id,)).fetchone()
    if not row:
        raise ValueError("template not found")
    rows = json.loads(row["board_json"])
    db.execute("DELETE FROM draft_tiers")
    for r in rows:
        cols = [k for k in r.keys() if k != "id"]
        ph = ",".join("?" for _ in cols)
        db.execute(f"INSERT INTO draft_tiers ({','.join(cols)}) VALUES ({ph})",
                   [r[k] for k in cols])
    return len(rows)


def prune_autobackups(db, keep=10):
    ids = [r["id"] for r in db.execute(
        "SELECT id FROM draft_board_templates WHERE kind='autobackup' ORDER BY id DESC")]
    for old in ids[keep:]:
        db.execute("DELETE FROM draft_board_templates WHERE id=?", (old,))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_board_templates.py
git commit -m "feat: board template snapshot/load/prune helpers"
```

---

## Task 3: Board-templates library route + page (list / save / duplicate / rename / delete)

**Files:**
- Modify: `app.py` (new route `admin_board_templates`, placed near `admin_tiers`)
- Create: `templates/admin/board_templates.html`
- Test: `tests/test_board_templates_routes.py`

**Interfaces:**
- Consumes: `save_board_template`, `prune_autobackups` (Task 2); `admin_required`, `get_db`, `get_setting`.
- Produces: route name `admin_board_templates` at `/admin/board-templates` (GET list; POST actions `save_current`, `duplicate`, `rename`, `delete`).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_board_templates_routes.py
def _seed(app_mod):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Garchomp', 18)")


def test_save_current_creates_template(client, app_mod):
    _seed(app_mod)
    resp = client.post("/admin/board-templates",
                       data={"action": "save_current", "name": "Base S8"},
                       follow_redirects=True)
    assert resp.status_code == 200
    with app_mod.get_db() as db:
        n = db.execute("SELECT COUNT(*) FROM draft_board_templates WHERE name='Base S8'").fetchone()[0]
    assert n == 1


def test_rename_and_delete(client, app_mod):
    _seed(app_mod)
    with app_mod.get_db() as db:
        tid = app_mod.save_board_template(db, "Old Name")
    client.post("/admin/board-templates",
                data={"action": "rename", "template_id": tid, "name": "New Name"})
    client.post("/admin/board-templates",
                data={"action": "delete", "template_id": tid})
    with app_mod.get_db() as db:
        cnt = db.execute("SELECT COUNT(*) FROM draft_board_templates WHERE id=?", (tid,)).fetchone()[0]
    assert cnt == 0


def test_list_page_renders(client, app_mod):
    _seed(app_mod)
    with app_mod.get_db() as db:
        app_mod.save_board_template(db, "Visible Template")
    resp = client.get("/admin/board-templates")
    assert resp.status_code == 200 and b"Visible Template" in resp.data
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates_routes.py -v`
Expected: FAIL (404 / route missing).

- [ ] **Step 3: Add the route to `app.py`**

```python
@app.route("/admin/board-templates", methods=["GET", "POST"])
@admin_required
def admin_board_templates():
    if request.method == "POST":
        action = request.form.get("action")
        with get_db() as db:
            if action == "save_current":
                name = (request.form.get("name") or "").strip() or "Untitled board"
                save_board_template(db, name, notes=request.form.get("notes", ""))
                flash(f"Saved board template '{name}'.", "success")
            elif action == "duplicate":
                tid = request.form["template_id"]
                src = db.execute(
                    "SELECT * FROM draft_board_templates WHERE id=?", (tid,)).fetchone()
                if src:
                    ts = _now_iso()
                    db.execute(
                        "INSERT INTO draft_board_templates (name, kind, notes, board_json, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?)",
                        (src["name"] + " (copy)", "manual", src["notes"],
                         src["board_json"], ts, ts))
                    flash("Template duplicated.", "success")
            elif action == "rename":
                db.execute(
                    "UPDATE draft_board_templates SET name=?, updated_at=? WHERE id=?",
                    ((request.form.get("name") or "").strip() or "Untitled board",
                     _now_iso(), request.form["template_id"]))
                flash("Template renamed.", "success")
            elif action == "delete":
                db.execute("DELETE FROM draft_board_templates WHERE id=?",
                           (request.form["template_id"],))
                flash("Template deleted.", "warning")
        return redirect(url_for("admin_board_templates"))

    with get_db() as db:
        rows = db.execute(
            "SELECT id, name, kind, notes, board_json, created_at, updated_at "
            "FROM draft_board_templates ORDER BY id DESC").fetchall()
    templates, autobackups = [], []
    for r in rows:
        d = dict(r)
        try:
            d["count"] = len(json.loads(r["board_json"]))
        except Exception:
            d["count"] = 0
        d.pop("board_json", None)
        (autobackups if r["kind"] == "autobackup" else templates).append(d)
    return render_template("admin/board_templates.html",
                           templates=templates, autobackups=autobackups,
                           league_name=get_setting("league_name", "Pokemon Draft League"))
```

- [ ] **Step 4: Create `templates/admin/board_templates.html`**

```html
{% extends "base.html" %}
{% block title %}Board Templates – Admin{% endblock %}
{% block content %}
<div class="flex items-center gap-3 mb-6">
  <a href="/admin" class="text-gray-400 hover:text-white">← Admin</a>
  <h1 class="text-2xl font-bold text-white">Draft Board Templates</h1>
</div>

<form method="POST" class="bg-gray-800 border border-gray-700 rounded-xl p-4 mb-6 flex flex-wrap gap-2 items-end">
  <input type="hidden" name="action" value="save_current">
  <div class="flex-1 min-w-[200px]">
    <label class="block text-xs text-gray-400 mb-1">Save the current live board as a new template</label>
    <input name="name" placeholder="Template name" required
           class="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm">
  </div>
  <input name="notes" placeholder="Notes (optional)"
         class="flex-1 min-w-[160px] bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm">
  <button class="px-4 py-2 bg-green-600 hover:bg-green-500 rounded text-sm font-semibold">Save current board</button>
</form>

{% macro row(t, is_auto) %}
<div class="bg-gray-800 border border-gray-700 rounded-lg p-3 flex flex-wrap items-center gap-2">
  <div class="flex-1 min-w-0">
    <div class="font-bold text-white truncate">{{ t.name }}</div>
    <div class="text-xs text-gray-400">{{ t.count }} mons · {{ t.created_at }}{% if t.notes %} · {{ t.notes }}{% endif %}</div>
  </div>
  <a href="/admin/board-templates/{{ t.id }}/download"
     class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs">Download</a>
  {% if not is_auto %}
  <a href="/admin/board-templates/{{ t.id }}/edit"
     class="px-3 py-1.5 bg-blue-700 hover:bg-blue-600 rounded text-xs">Edit</a>
  <form method="POST" class="inline" onsubmit="return confirm('Duplicate this template?')">
    <input type="hidden" name="action" value="duplicate"><input type="hidden" name="template_id" value="{{ t.id }}">
    <button class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs">Duplicate</button>
  </form>
  {% endif %}
  <form method="POST" class="inline"
        onsubmit="return loadBoard(this, {{ t.id }})">
    <input type="hidden" name="action" value="load"><input type="hidden" name="template_id" value="{{ t.id }}">
    <input type="hidden" name="confirm" value="">
    <button formaction="/admin/board-templates/load"
            class="px-3 py-1.5 bg-yellow-600 hover:bg-yellow-500 rounded text-xs font-semibold">Load to live</button>
  </form>
  <form method="POST" class="inline" onsubmit="return confirm('Delete this template?')">
    <input type="hidden" name="action" value="delete"><input type="hidden" name="template_id" value="{{ t.id }}">
    <button class="px-3 py-1.5 bg-red-800 hover:bg-red-700 rounded text-xs">Delete</button>
  </form>
</div>
{% endmacro %}

<h2 class="text-lg font-bold text-gray-200 mb-2">Saved templates</h2>
<div class="space-y-2 mb-8">
  {% for t in templates %}{{ row(t, False) }}{% else %}
  <div class="text-gray-500 text-sm">No saved templates yet.</div>{% endfor %}
</div>

<h2 class="text-lg font-bold text-gray-200 mb-2">Restore points <span class="text-xs text-gray-500">(auto-saved before loads)</span></h2>
<div class="space-y-2">
  {% for t in autobackups %}{{ row(t, True) }}{% else %}
  <div class="text-gray-500 text-sm">No restore points yet.</div>{% endfor %}
</div>

<script>
function loadBoard(form, id) {
  if (!confirm('Replace the entire live board with this template? The current board is auto-saved as a restore point first.')) return false;
  form.querySelector('[name=confirm]').value = 'yes';
  return true;
}
</script>
{% endblock %}
```

Note: the "Load to live" button uses `formaction="/admin/board-templates/load"` (the dedicated route in Task 4); the form's hidden `confirm` is set by JS before submit.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates_routes.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py templates/admin/board_templates.html tests/test_board_templates_routes.py
git commit -m "feat: board-templates library (save/duplicate/rename/delete)"
```

---

## Task 4: Load-to-live route with safety guards

**Files:**
- Modify: `app.py` (new route `admin_board_template_load`)
- Test: `tests/test_board_templates_routes.py`

**Interfaces:**
- Consumes: `save_board_template`, `load_board_template`, `prune_autobackups` (Task 2).
- Produces: route `admin_board_template_load` at `/admin/board-templates/load` (POST `template_id`, `confirm`).

- [ ] **Step 1: Write failing tests**

```python
# add to tests/test_board_templates_routes.py
def _template_with(app_mod, name, mon):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES (?, 10)", (mon,))
        return app_mod.save_board_template(db, name)


def test_load_replaces_board_and_makes_autobackup(client, app_mod):
    tid = _template_with(app_mod, "Template A", "Dragapult")
    with app_mod.get_db() as db:                       # make live board different
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Skeledirge', 12)")
    client.post("/admin/board-templates/load",
                data={"template_id": tid, "confirm": "yes"}, follow_redirects=True)
    with app_mod.get_db() as db:
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
        autos = db.execute(
            "SELECT COUNT(*) FROM draft_board_templates WHERE kind='autobackup'").fetchone()[0]
    assert names == {"Dragapult"} and autos == 1       # board swapped + restore point made


def test_load_blocked_during_active_session(client, app_mod):
    tid = _template_with(app_mod, "Template B", "Dragapult")
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Skeledirge', 12)")
        db.execute("INSERT INTO draft_sessions (name, status) VALUES ('S8', 'active')")
    client.post("/admin/board-templates/load",
                data={"template_id": tid, "confirm": "yes"})
    with app_mod.get_db() as db:
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert names == {"Skeledirge"}                     # unchanged — load refused


def test_load_requires_confirm_when_rosters_exist(client, app_mod):
    tid = _template_with(app_mod, "Template C", "Dragapult")
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Skeledirge', 12)")
        db.execute("INSERT INTO coaches (coach_name, team_name) VALUES ('C', 'T')")
        cid = db.execute("SELECT id FROM coaches LIMIT 1").fetchone()["id"]
        db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name) VALUES (?, 'Skeledirge')", (cid,))
    client.post("/admin/board-templates/load",
                data={"template_id": tid, "confirm": ""})   # no confirm
    with app_mod.get_db() as db:
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert names == {"Skeledirge"}                     # unchanged — needed confirm
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates_routes.py -k load -v`
Expected: FAIL (404).

- [ ] **Step 3: Add the route to `app.py`**

```python
@app.route("/admin/board-templates/load", methods=["POST"])
@admin_required
def admin_board_template_load():
    tid = request.form["template_id"]
    with get_db() as db:
        active = db.execute(
            "SELECT COUNT(*) FROM draft_sessions WHERE status='active'").fetchone()[0]
        if active:
            flash("A draft session is active — cannot replace the board now.", "warning")
            return redirect(url_for("admin_board_templates"))
        rosters = db.execute("SELECT COUNT(*) FROM pokemon_roster").fetchone()[0]
        if rosters and request.form.get("confirm") != "yes":
            flash("Rosters already exist — re-confirm to replace the board.", "warning")
            return redirect(url_for("admin_board_templates"))
        save_board_template(db, f"Auto-backup before load {_now_iso()}", kind="autobackup")
        prune_autobackups(db)
        try:
            n = load_board_template(db, tid)
            flash(f"Loaded {n} Pokemon onto the live board (previous board saved as a restore point).", "success")
        except ValueError:
            flash("Template not found.", "warning")
    return redirect(url_for("admin_board_templates"))
```

(The whole body runs in one `with get_db()` block, so a failure rolls the transaction back — board + autobackup are all-or-nothing.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates_routes.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_board_templates_routes.py
git commit -m "feat: load board template to live with safety guards + restore point"
```

---

## Task 5: Download template as JSON

**Files:**
- Modify: `app.py` (new route `admin_board_template_download`)
- Test: `tests/test_board_templates_routes.py`

**Interfaces:**
- Produces: route `admin_board_template_download` at `/admin/board-templates/<int:tid>/download` (GET).

- [ ] **Step 1: Write the failing test**

```python
def test_download_returns_json_board(client, app_mod):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Garchomp', 18)")
        tid = app_mod.save_board_template(db, "DL Test")
    resp = client.get(f"/admin/board-templates/{tid}/download")
    import json as _j
    assert resp.status_code == 200
    assert any(m["name"] == "Garchomp" for m in _j.loads(resp.data))
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates_routes.py::test_download_returns_json_board -v`
Expected: FAIL (404).

- [ ] **Step 3: Add the route to `app.py`**

```python
@app.route("/admin/board-templates/<int:tid>/download")
@admin_required
def admin_board_template_download(tid):
    with get_db() as db:
        row = db.execute(
            "SELECT name, board_json FROM draft_board_templates WHERE id=?", (tid,)).fetchone()
    if not row:
        flash("Template not found.", "warning")
        return redirect(url_for("admin_board_templates"))
    from flask import make_response          # local import (matches existing usage in app.py)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", row["name"])[:40] or "board"
    resp = make_response(row["board_json"])
    resp.headers["Content-Type"] = "application/json"
    resp.headers["Content-Disposition"] = f'attachment; filename="{safe}.json"'
    return resp
```

(`make_response` is not in the top-level imports, so import it locally as shown — the same way the existing recap route does.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates_routes.py::test_download_returns_json_board -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_board_templates_routes.py
git commit -m "feat: download board template as JSON"
```

---

## Task 6: Edit a template in place

Edit a template's rows without touching the live board. The editor renders each row's human-editable fields (name, points, tier_label, is_banned, is_tera_banned, is_mega) and preserves every other column (stats/abilities/moves) by index. On save, the page serializes all rows to a hidden JSON field.

**Files:**
- Modify: `app.py` (route `admin_board_template_edit`)
- Create: `templates/admin/board_template_edit.html`
- Test: `tests/test_board_templates_routes.py`

**Interfaces:**
- Produces: route `admin_board_template_edit` at `/admin/board-templates/<int:tid>/edit` (GET form; POST `board_json` + `name` + `notes`). Does **not** modify `draft_tiers`.

- [ ] **Step 1: Write failing tests**

```python
def test_edit_get_renders_rows(client, app_mod):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Garchomp', 18)")
        tid = app_mod.save_board_template(db, "Edit Me")
    resp = client.get(f"/admin/board-templates/{tid}/edit")
    assert resp.status_code == 200 and b"Garchomp" in resp.data


def test_edit_post_saves_blob_without_touching_live(client, app_mod):
    import json as _j
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('LiveMon', 5)")
        tid = app_mod.save_board_template(db, "T")
    new_board = _j.dumps([{"name": "EditedMon", "points": 22}])
    client.post(f"/admin/board-templates/{tid}/edit",
                data={"name": "T", "notes": "", "board_json": new_board},
                follow_redirects=True)
    with app_mod.get_db() as db:
        tpl = _j.loads(db.execute(
            "SELECT board_json FROM draft_board_templates WHERE id=?", (tid,)).fetchone()["board_json"])
        live = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert tpl[0]["name"] == "EditedMon"   # template updated
    assert live == {"LiveMon"}             # live board untouched
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates_routes.py -k edit -v`
Expected: FAIL (404).

- [ ] **Step 3: Add the route to `app.py`**

```python
@app.route("/admin/board-templates/<int:tid>/edit", methods=["GET", "POST"])
@admin_required
def admin_board_template_edit(tid):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM draft_board_templates WHERE id=?", (tid,)).fetchone()
        if not row:
            flash("Template not found.", "warning")
            return redirect(url_for("admin_board_templates"))
        if request.method == "POST":
            try:
                board = json.loads(request.form.get("board_json") or "[]")
                assert isinstance(board, list)
            except Exception:
                flash("Could not parse the edited board.", "warning")
                return redirect(url_for("admin_board_template_edit", tid=tid))
            db.execute(
                "UPDATE draft_board_templates SET name=?, notes=?, board_json=?, updated_at=? WHERE id=?",
                ((request.form.get("name") or row["name"]).strip(),
                 request.form.get("notes", ""), json.dumps(board), _now_iso(), tid))
            flash("Template saved.", "success")
            return redirect(url_for("admin_board_templates"))
        board = json.loads(row["board_json"])
    return render_template("admin/board_template_edit.html",
                           tpl=dict(row), board=board,
                           league_name=get_setting("league_name", "Pokemon Draft League"))
```

- [ ] **Step 4: Create `templates/admin/board_template_edit.html`**

```html
{% extends "base.html" %}
{% block title %}Edit Board Template – Admin{% endblock %}
{% block content %}
<div class="flex items-center gap-3 mb-4">
  <a href="/admin/board-templates" class="text-gray-400 hover:text-white">← Templates</a>
  <h1 class="text-2xl font-bold text-white">Edit: {{ tpl.name }}</h1>
</div>
<p class="text-xs text-gray-400 mb-4">Editing this template does <b>not</b> change the live draft board. Other columns (stats, abilities, moves) are preserved.</p>

<form method="POST" id="tplForm">
  <div class="flex flex-wrap gap-2 mb-4">
    <input name="name" value="{{ tpl.name }}" class="bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm">
    <input name="notes" value="{{ tpl.notes }}" placeholder="Notes" class="flex-1 bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm">
    <button type="button" onclick="addRow()" class="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm">+ Row</button>
    <button class="px-4 py-2 bg-green-600 hover:bg-green-500 rounded text-sm font-semibold">Save template</button>
  </div>
  <input type="hidden" name="board_json" id="board_json">
  <table class="w-full text-sm"><thead class="text-gray-400 text-xs">
    <tr><th class="text-left p-1">Name</th><th class="p-1">Pts</th><th class="p-1">Tier label</th>
        <th class="p-1">Ban</th><th class="p-1">T-Ban</th><th class="p-1">Mega</th><th></th></tr>
  </thead><tbody id="rows"></tbody></table>
</form>

<script>
const BOARD = {{ board|tojson }};
const KEYS = ['name','points','tier_label','is_banned','is_tera_banned','is_mega'];
function cell(v){ const td=document.createElement('td'); td.className='p-1'; td.appendChild(v); return td; }
function inp(val, w){ const i=document.createElement('input'); i.value=(val==null?'':val); i.className='bg-gray-900 border border-gray-700 rounded px-2 py-1 text-white text-xs '+(w||'w-full'); return i; }
function chk(val){ const i=document.createElement('input'); i.type='checkbox'; i.checked=!!Number(val); return i; }
function makeRow(mon){
  const tr=document.createElement('tr'); tr.className='border-b border-gray-800'; tr._mon=mon;
  tr._name=inp(mon.name); tr._pts=inp(mon.points,'w-16'); tr._tier=inp(mon.tier_label);
  tr._ban=chk(mon.is_banned); tr._tban=chk(mon.is_tera_banned); tr._mega=chk(mon.is_mega);
  tr.appendChild(cell(tr._name)); tr.appendChild(cell(tr._pts)); tr.appendChild(cell(tr._tier));
  tr.appendChild(cell(tr._ban)); tr.appendChild(cell(tr._tban)); tr.appendChild(cell(tr._mega));
  const del=document.createElement('button'); del.type='button'; del.textContent='✕';
  del.className='text-red-400 px-2'; del.onclick=()=>tr.remove();
  tr.appendChild(cell(del));
  return tr;
}
function addRow(){ document.getElementById('rows').appendChild(makeRow({})); }
const tbody=document.getElementById('rows');
BOARD.forEach(m=>tbody.appendChild(makeRow(m)));
document.getElementById('tplForm').addEventListener('submit', e=>{
  const out=[];
  for(const tr of tbody.children){
    const mon=Object.assign({}, tr._mon||{});   // preserve stats/abilities/moves
    mon.name=tr._name.value.trim();
    mon.points=parseInt(tr._pts.value)||0;
    mon.tier_label=tr._tier.value.trim();
    mon.is_banned=tr._ban.checked?1:0;
    mon.is_tera_banned=tr._tban.checked?1:0;
    mon.is_mega=tr._mega.checked?1:0;
    delete mon.id;
    if(mon.name) out.push(mon);
  }
  document.getElementById('board_json').value=JSON.stringify(out);
});
</script>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_board_templates_routes.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py templates/admin/board_template_edit.html tests/test_board_templates_routes.py
git commit -m "feat: edit board template in place (preserves all columns; live board untouched)"
```

---

## Task 7: DB backup / restore helpers

**Files:**
- Modify: `app.py` (helpers after the board helpers; ensure `import shutil` near top imports)
- Test: `tests/test_backups.py`

**Interfaces:**
- Produces:
  - `_backups_dir() -> str`
  - `create_db_backup(label="") -> str` (filename)
  - `list_db_backups() -> list[str]`
  - `restore_db_backup(filename) -> None` (raises `ValueError` if missing)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_backups.py
def test_create_lists_and_restore_roundtrip(app_mod):
    # baseline state
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Baseline', 7)")
    fn = app_mod.create_db_backup("manual")
    assert fn in app_mod.list_db_backups()

    # mutate after backup
    with app_mod.get_db() as db:
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('AfterBackup', 9)")

    app_mod.restore_db_backup(fn)               # roll back to the snapshot

    with app_mod.get_db() as db:
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert names == {"Baseline"}                # AfterBackup gone


def test_restore_makes_pre_restore_backup(app_mod):
    before = len(app_mod.list_db_backups())
    fn = app_mod.create_db_backup("a")
    app_mod.restore_db_backup(fn)
    assert len(app_mod.list_db_backups()) >= before + 2   # the 'a' backup + a pre-restore one


def test_restore_missing_raises(app_mod):
    import pytest
    with pytest.raises(ValueError):
        app_mod.restore_db_backup("does-not-exist.db")
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_backups.py -v`
Expected: FAIL (helpers not defined).

- [ ] **Step 3: Add the helpers to `app.py`**

`shutil` is **not** currently imported — add `import shutil` to the top imports (next to `import os`). `datetime` is the class (`from datetime import datetime`), so use `datetime.now()`. Then:

```python
def _backups_dir():
    d = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")
    os.makedirs(d, exist_ok=True)
    return d


def create_db_backup(label=""):
    safe = re.sub(r"[^A-Za-z0-9_-]+", "", label)[:40]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    fn = f"league-{ts}{('-' + safe) if safe else ''}.db"
    shutil.copy2(DB_PATH, os.path.join(_backups_dir(), fn))
    return fn


def list_db_backups():
    return sorted([f for f in os.listdir(_backups_dir()) if f.endswith(".db")], reverse=True)


def restore_db_backup(filename):
    # No open connection to DB_PATH may be held here (Windows file lock on swap).
    src = os.path.join(_backups_dir(), os.path.basename(filename))
    if not os.path.isfile(src):
        raise ValueError("backup not found")
    create_db_backup("prerestore")                 # safety snapshot of current state
    tmp = DB_PATH + ".restoring"
    shutil.copy2(src, tmp)
    os.replace(tmp, DB_PATH)                        # atomic swap
```

The microsecond (`%f`) in the timestamp keeps filenames unique within a test/second.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_backups.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py tests/test_backups.py
git commit -m "feat: DB backup/restore helpers (atomic swap, pre-restore safety)"
```

---

## Task 8: Backups admin route + page

**Files:**
- Modify: `app.py` (route `admin_backups` + download route)
- Create: `templates/admin/backups.html`
- Test: `tests/test_backups.py`

**Interfaces:**
- Consumes: `create_db_backup`, `list_db_backups`, `restore_db_backup`, `_backups_dir` (Task 7).
- Produces: routes `admin_backups` (`/admin/backups`, GET/POST `create`/`restore`/`delete`) and `admin_backup_download` (`/admin/backups/<name>/download`).

- [ ] **Step 1: Write failing tests**

```python
# add to tests/test_backups.py
def test_create_via_route_then_list_page(client, app_mod):
    client.post("/admin/backups", data={"action": "create", "label": "manual"}, follow_redirects=True)
    resp = client.get("/admin/backups")
    assert resp.status_code == 200 and b"league-" in resp.data


def test_restore_via_route(client, app_mod):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Snap', 4)")
    fn = app_mod.create_db_backup("x")
    with app_mod.get_db() as db:
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Later', 6)")
    client.post("/admin/backups", data={"action": "restore", "filename": fn}, follow_redirects=True)
    with app_mod.get_db() as db:
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert names == {"Snap"}
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_backups.py -k route -v`
Expected: FAIL (404).

- [ ] **Step 3: Add the routes to `app.py`**

```python
@app.route("/admin/backups", methods=["GET", "POST"])
@admin_required
def admin_backups():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            fn = create_db_backup(request.form.get("label", ""))
            flash(f"Backup created: {fn}", "success")
        elif action == "restore":
            try:
                restore_db_backup(request.form["filename"])
                flash("Database restored (a pre-restore backup was saved first).", "success")
            except ValueError:
                flash("Backup file not found.", "warning")
        elif action == "delete":
            target = os.path.join(_backups_dir(), os.path.basename(request.form["filename"]))
            if os.path.isfile(target):
                os.remove(target)
                flash("Backup deleted.", "warning")
        return redirect(url_for("admin_backups"))
    backups = list_db_backups()
    return render_template("admin/backups.html", backups=backups,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/admin/backups/<name>/download")
@admin_required
def admin_backup_download(name):
    return send_from_directory(_backups_dir(), os.path.basename(name), as_attachment=True)
```

(`send_from_directory` is already imported in `app.py`.)

- [ ] **Step 4: Create `templates/admin/backups.html`**

```html
{% extends "base.html" %}
{% block title %}Database Backups – Admin{% endblock %}
{% block content %}
<div class="flex items-center gap-3 mb-6">
  <a href="/admin" class="text-gray-400 hover:text-white">← Admin</a>
  <h1 class="text-2xl font-bold text-white">Database Backups</h1>
</div>

<form method="POST" class="bg-gray-800 border border-gray-700 rounded-xl p-4 mb-6 flex gap-2 items-end">
  <input type="hidden" name="action" value="create">
  <div class="flex-1">
    <label class="block text-xs text-gray-400 mb-1">Create a snapshot of the entire database now</label>
    <input name="label" placeholder="Label (optional, e.g. before-draft)"
           class="w-full bg-gray-900 border border-gray-600 rounded px-3 py-2 text-white text-sm">
  </div>
  <button class="px-4 py-2 bg-green-600 hover:bg-green-500 rounded text-sm font-semibold">Create backup</button>
</form>

<div class="space-y-2">
  {% for b in backups %}
  <div class="bg-gray-800 border border-gray-700 rounded-lg p-3 flex items-center gap-2">
    <div class="flex-1 min-w-0 font-mono text-sm text-gray-200 truncate">{{ b }}</div>
    <a href="/admin/backups/{{ b }}/download" class="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-xs">Download</a>
    <form method="POST" class="inline" onsubmit="return confirm('Restore this backup? The current database will be overwritten (a pre-restore backup is saved first).')">
      <input type="hidden" name="action" value="restore"><input type="hidden" name="filename" value="{{ b }}">
      <button class="px-3 py-1.5 bg-yellow-600 hover:bg-yellow-500 rounded text-xs font-semibold">Restore</button>
    </form>
    <form method="POST" class="inline" onsubmit="return confirm('Delete this backup file?')">
      <input type="hidden" name="action" value="delete"><input type="hidden" name="filename" value="{{ b }}">
      <button class="px-3 py-1.5 bg-red-800 hover:bg-red-700 rounded text-xs">Delete</button>
    </form>
  </div>
  {% else %}
  <div class="text-gray-500 text-sm">No backups yet.</div>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_backups.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd "D:/Yuri Draft League"
git add app.py templates/admin/backups.html tests/test_backups.py
git commit -m "feat: admin DB backup/restore page"
```

---

## Task 9: Admin nav links, .gitignore, build marker; full suite + smoke

**Files:**
- Modify: `templates/admin/index.html` (two new nav cards)
- Modify: `.gitignore` (ignore `backups/`)
- Modify: `templates/base.html` (build marker)

**Interfaces:** none new.

- [ ] **Step 1: Add nav cards to `templates/admin/index.html`**

Add two cards next to the existing `/admin/tiers` card (copy the existing card markup pattern — `bg-gray-800 border border-gray-700 hover:border-yellow-500 rounded-xl p-6` anchor):

```html
    <a href="/admin/board-templates" class="bg-gray-800 border border-gray-700 hover:border-yellow-500 rounded-xl p-6 transition-all hover:scale-[1.02]">
      <div class="font-bold text-lg text-white">Board Templates</div>
      <div class="text-sm text-gray-400">Save, reuse, and edit draft boards</div>
    </a>
    <a href="/admin/backups" class="bg-gray-800 border border-gray-700 hover:border-yellow-500 rounded-xl p-6 transition-all hover:scale-[1.02]">
      <div class="font-bold text-lg text-white">Database Backups</div>
      <div class="text-sm text-gray-400">Snapshot and restore the whole database</div>
    </a>
```

- [ ] **Step 2: Ignore the backups dir**

Append to `.gitignore`:
```
backups/
```
(Confirm `*.db` is already ignored; if not, add it.)

- [ ] **Step 3: Bump the build marker in `templates/base.html`**

Change the `console.log("YDL build: …")` line to:
```javascript
  console.log("YDL build: board-templates-backups-v27");
```

- [ ] **Step 4: Run the full test suite**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 5: Manual smoke (local dev server)**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe app.py` then in a browser (logged in as admin):
- `/admin/board-templates` → Save current board → appears in "Saved templates".
- Edit → change a point value → Save → reopen Edit shows the change; `/admin/tiers` (live) unchanged.
- Load to live → confirm dialog → board replaced; a "Restore point" row appears.
- `/admin/backups` → Create backup → appears; Download works.
Expected: all behave as described. Stop the server (Ctrl-C).

- [ ] **Step 6: Commit**

```bash
cd "D:/Yuri Draft League"
git add templates/admin/index.html templates/base.html .gitignore
git commit -m "feat: admin nav links + ignore backups/ + build marker board-templates-backups-v27"
```

- [ ] **Step 7: Deploy (when the user approves the push)**

```bash
cd "D:/Yuri Draft League" && git push origin HEAD:master
```
Then on PythonAnywhere: `cd ~/yuri-draft-league && git fetch origin && git reset --hard origin/master`, clear `__pycache__`, **Reload via the Web tab**, confirm `board-templates-backups-v27` in the browser console, and smoke-test the two new admin pages.

---

## Notes for the implementer
- This plan is **Phase 1A + 1C** only. Phase 1B (the configuration-driven settings page) and Phase 2 (per-season settings, multi-coach teams) are separate plans per the spec.
- Defaults and existing behavior are untouched: no draft-logic, standings, or settings code changes here — these are purely additive admin features.
- If `tests/` import fails because `app.py` does import-time work that needs other env vars, set them in `conftest.py` alongside `DB_PATH` before the `import app`.
