# Battle Mechanics & Captains Config (Phase 1B-5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four bare battle-mechanic toggles with a single `mechanic_config` JSON (enable / captain designation / tier restriction / point cap / count / schema-only tax) and add server-side captain-eligibility enforcement, while keeping the current season byte-for-byte unchanged.

**Architecture:** A new `get_mechanic_config(db)` accessor derives the config from the legacy `mechanic_*` keys when absent (migration = current effective rules). The settings POST assembles the config from per-mechanic form cards and **dual-writes** the legacy keys so ~40 template sites never change. A `_captain_eligibility_error(...)` helper gates `/draft/live/set_captain` (coach-facing only) using the config. The pick-cost path and admin routes are untouched.

**Tech Stack:** Python 3 / Flask monolith (`app.py`), SQLite (`league_settings` key/value + `pokemon_roster`), Jinja2 + Tailwind CDN templates, pytest (temp-DB harness in `tests/conftest.py`).

Design spec: `docs/superpowers/specs/2026-07-05-battle-mechanics-captains-config-b5-design.md`.
Ground-truth line numbers: `scratchpad/b5_plan_groundtruth.md`.

## Global Constraints

- **Behavior preservation is the top priority.** Every new setting defaults to reproduce current behavior. Absent `mechanic_config` → the migrated config equals today's effective rules; every captain already designated stays valid.
- **The pick-cost path MUST be untouched:** `draft_live_pick` budget check, ticket check, uber branch. `tax.type` stays `"none"`; no surcharge is computed anywhere in B5.
- **Dual-write is mandatory:** saving settings writes `mechanic_config` AND the legacy keys `mechanic_mega`/`mechanic_tera`/`mechanic_zmove`/`mechanic_uber` (`"1"`/`"0"`). The ~40 template sites keep reading the legacy keys — do NOT edit them.
- **`mechanic_uber`'s `enabled` continues to come from the Uber section's own checkbox** — its handling and `uber_combination` assembly are unchanged.
- **Admin roster routes stay ungated** (`admin_roster` add/edit, app.py ~2878/2894) — admin override preserved.
- **Captain columns:** only `is_tera_captain` and `is_zmove_captain` exist. Do NOT add `is_mega_captain`/`is_dynamax_captain`. Preserve `'is_zmove_captain' in r.keys()` guards elsewhere.
- **Only tera & zmove are captain mechanics** by default. Mega/Dynamax carry the schema but default `is_captain_mechanic=false` (no designation UI/columns in B5).
- **The one intentional behavior change:** the combined tera+zmove ≤18 cross-cap is dropped. Only per-mechanic `max_pts` caps are enforced.
- **Deep-copy list fields** (`restrict_tiers`) in the accessor to avoid mutating module-level defaults (the B3 shallow-copy footgun).
- **Branch:** `feat/mechanic-config-b5`. Do NOT work on `main`/`master`.
- **Python env:** use `./.venv/Scripts/python.exe` (Windows). Run tests with `./.venv/Scripts/python.exe -m pytest`.
- **Never** `git add -A` (embedded `damage-calc/` repo + DB files). Add explicit paths only. Never commit `*.db` or `backups/`.

### Test harness reference (from `tests/conftest.py`, built in Phase 1A)

- `app_mod` — the imported app module (temp DB, `init_db` run).
- `db_path` — the temp DB path.
- `client` — admin-authenticated Flask test client. **CSRF:** POSTs need `headers={"X-CSRFToken": "testtoken"}`.
- `app_mod.get_db()` is a context manager yielding a connection. **`get_setting()` opens its OWN connection**, so when a test writes a setting and then calls code that reads it via `get_setting`, the write must be COMMITTED first — use a separate `with app_mod.get_db() as db:` block to write, exit it, then call the code under test in a new block. (This bit B3/B4 — see their tests.)
- `init_db` does NOT create `draft_picks`; route tests that touch it must `CREATE TABLE IF NOT EXISTS draft_picks (...)` (see `tests/test_draft_mode_policy.py` for the exact DDL).

---

## Task 1: `get_mechanic_config(db)` accessor + migration/defaults

**Files:**
- Create: `tests/test_mechanic_config.py`
- Modify: `app.py` — add `DEFAULT_MECHANIC_CONFIG` constant + `get_mechanic_config(db)` near the other config accessors (after `get_tier_definitions`, ~app.py:4793).

**Interfaces:**
- Consumes: `get_setting(key, default="")` (app.py:635); `json` (already imported).
- Produces:
  - `DEFAULT_MECHANIC_CONFIG` — module-level dict, one block per mechanic (`mega`/`tera`/`zmove`/`dynamax`).
  - `get_mechanic_config(db)` — returns `dict[str, dict]`. When the `mechanic_config` setting is present and valid JSON, returns it (normalized). When absent, DERIVES it: `enabled` from the legacy `mechanic_<name>` key read off `db`; captain defaults hardcoded (tera/zmove → captain, Tier 4/5, ≤13, count 1); all `tax` → `{"type":"none","value":0}`. Deep-copies `restrict_tiers`.

**Reference pattern (existing `get_tier_definitions`, app.py:4775-4793) — mirror its validate-or-fallback shape and the `list(...)` deep-copy of list fields.**

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mechanic_config.py`:

```python
"""B5: get_mechanic_config — migration reproduces the current season's effective rules."""


def test_default_config_shape(app_mod):
    with app_mod.get_db() as db:
        cfg = app_mod.get_mechanic_config(db)
    assert set(cfg.keys()) == {"mega", "tera", "zmove", "dynamax"}
    for name in ("mega", "tera", "zmove", "dynamax"):
        b = cfg[name]
        assert set(b.keys()) == {
            "enabled", "is_captain_mechanic", "restrict_tiers",
            "max_pts", "captain_count", "tax",
        }
        assert b["tax"] == {"type": "none", "value": 0}


def test_migration_enabled_follows_legacy_keys(app_mod):
    # legacy mechanic_* keys drive `enabled` when mechanic_config is absent
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_mega','1')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_tera','1')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_zmove','0')")
    with app_mod.get_db() as db:
        cfg = app_mod.get_mechanic_config(db)
    assert cfg["mega"]["enabled"] is True
    assert cfg["tera"]["enabled"] is True
    assert cfg["zmove"]["enabled"] is False
    assert cfg["dynamax"]["enabled"] is False  # dynamax always defaults off


def test_migration_captain_defaults_reproduce_current_rules(app_mod):
    with app_mod.get_db() as db:
        cfg = app_mod.get_mechanic_config(db)
    for name in ("tera", "zmove"):
        b = cfg[name]
        assert b["is_captain_mechanic"] is True
        assert b["restrict_tiers"] == ["Tier 4", "Tier 5"]
        assert b["max_pts"] == 13
        assert b["captain_count"] == 1
    # mega/dynamax are NOT captain mechanics by default
    assert cfg["mega"]["is_captain_mechanic"] is False
    assert cfg["dynamax"]["is_captain_mechanic"] is False


def test_stored_config_is_returned_and_lists_deepcopied(app_mod):
    import json
    stored = {
        "mega": {"enabled": True, "is_captain_mechanic": False, "restrict_tiers": [],
                 "max_pts": 0, "captain_count": 0, "tax": {"type": "none", "value": 0}},
        "tera": {"enabled": True, "is_captain_mechanic": True, "restrict_tiers": ["Tier 5"],
                 "max_pts": 10, "captain_count": 2, "tax": {"type": "none", "value": 0}},
        "zmove": {"enabled": False, "is_captain_mechanic": True, "restrict_tiers": ["Tier 4", "Tier 5"],
                  "max_pts": 13, "captain_count": 1, "tax": {"type": "none", "value": 0}},
        "dynamax": {"enabled": False, "is_captain_mechanic": False, "restrict_tiers": [],
                    "max_pts": 0, "captain_count": 0, "tax": {"type": "none", "value": 0}},
    }
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_config', ?)",
                   (json.dumps(stored),))
    with app_mod.get_db() as db:
        cfg = app_mod.get_mechanic_config(db)
    assert cfg["tera"]["restrict_tiers"] == ["Tier 5"] and cfg["tera"]["max_pts"] == 10
    # mutating the returned config must not corrupt a later read (deep copy)
    cfg["tera"]["restrict_tiers"].append("MUT")
    with app_mod.get_db() as db:
        cfg2 = app_mod.get_mechanic_config(db)
    assert cfg2["tera"]["restrict_tiers"] == ["Tier 5"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute 'get_mechanic_config'`.

- [ ] **Step 3: Add `DEFAULT_MECHANIC_CONFIG` + `get_mechanic_config(db)`**

In `app.py`, immediately AFTER `get_tier_definitions()` (ends at app.py:4793), add:

```python
DEFAULT_MECHANIC_CONFIG = {
    "mega":    {"enabled": False, "is_captain_mechanic": False,
                "restrict_tiers": [], "max_pts": 0, "captain_count": 0,
                "tax": {"type": "none", "value": 0}},
    "tera":    {"enabled": False, "is_captain_mechanic": True,
                "restrict_tiers": ["Tier 4", "Tier 5"], "max_pts": 13,
                "captain_count": 1, "tax": {"type": "none", "value": 0}},
    "zmove":   {"enabled": False, "is_captain_mechanic": True,
                "restrict_tiers": ["Tier 4", "Tier 5"], "max_pts": 13,
                "captain_count": 1, "tax": {"type": "none", "value": 0}},
    "dynamax": {"enabled": False, "is_captain_mechanic": False,
                "restrict_tiers": [], "max_pts": 0, "captain_count": 0,
                "tax": {"type": "none", "value": 0}},
}

_MECHANIC_NAMES = ("mega", "tera", "zmove", "dynamax")


def _mechanic_block(d):
    """Normalize one stored/derived mechanic block into the canonical shape,
    deep-copying the list field so the caller can't mutate a shared default."""
    tax = d.get("tax") or {}
    return {
        "enabled": bool(d.get("enabled", False)),
        "is_captain_mechanic": bool(d.get("is_captain_mechanic", False)),
        "restrict_tiers": [str(t) for t in (d.get("restrict_tiers") or [])],
        "max_pts": int(d.get("max_pts", 0) or 0),
        "captain_count": int(d.get("captain_count", 0) or 0),
        "tax": {"type": str(tax.get("type", "none") or "none"),
                "value": int(tax.get("value", 0) or 0)},
    }


def get_mechanic_config(db):
    """Per-mechanic config {mega,tera,zmove,dynamax} → block. When the
    'mechanic_config' setting is absent, DERIVE it so behavior is preserved:
    `enabled` comes from the legacy mechanic_<name> key; captain rules default
    to today's effective client rules (tera/zmove: Tier 4/5, <=13 pts, count 1).
    Lists are deep-copied. Malformed stored JSON falls back to the derived form."""
    row = db.execute("SELECT value FROM league_settings WHERE key='mechanic_config'").fetchone()
    if row and row["value"]:
        try:
            data = json.loads(row["value"])
            if isinstance(data, dict):
                return {name: _mechanic_block(data.get(name, DEFAULT_MECHANIC_CONFIG[name]))
                        for name in _MECHANIC_NAMES}
        except Exception:
            pass
    # Derive from legacy keys.
    out = {}
    for name in _MECHANIC_NAMES:
        block = _mechanic_block(DEFAULT_MECHANIC_CONFIG[name])
        if name != "dynamax":
            leg = db.execute("SELECT value FROM league_settings WHERE key=?",
                             (f"mechanic_{name}",)).fetchone()
            block["enabled"] = bool(leg and leg["value"] == "1")
        out[name] = block
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (77 = prior 73 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_mechanic_config.py
git commit -m "feat: get_mechanic_config accessor + migration defaults (B5 T1)"
```

---

## Task 2: Dual-write in `admin_settings` POST (assemble config, write legacy keys)

**Files:**
- Modify: `app.py` — `admin_settings` POST handler (app.py:2738-2778).
- Modify: `tests/test_settings_page.py` — remove `mechanic`/`mechanic_tax` from the persisted-scalars form and add dual-write assertions (lockstep; more in T3).
- Test: add cases to `tests/test_mechanic_config.py`.

**Interfaces:**
- Consumes: `get_mechanic_config(db)` (T1); `json`; `request.form`.
- Produces: on POST, `league_settings['mechanic_config']` is written as JSON assembled from `mech_<name>_*` form fields, AND the legacy `mechanic_mega/tera/zmove` keys are written `"1"`/`"0"` from each block's `enabled`. (`mechanic_uber` is NOT touched by this assembly — it stays with the existing Uber handling.)

**Form field naming (produced by the T3 UI; the assembly must read exactly these):**
- `mech_<name>_enabled` — checkbox (`"1"` when checked; absent when not) for `<name>` in `mega,tera,zmove,dynamax`.
- `mech_<name>_captain` — checkbox, `is_captain_mechanic`.
- `mech_<name>_count` — number, `captain_count`.
- `mech_<name>_maxpts` — number, `max_pts`.
- `mech_<name>_tiers` — multi-checkbox (`getlist`), `restrict_tiers` (tier names).
- Tax fields are NOT read in B5 (always written `{"type":"none","value":0}`).

**Important:** `mechanic_uber` and `uber_combination` handling is unchanged. In the force-zero loop (app.py:2756), `mechanic_uber` and `first_pick_regular` STAY; but `mechanic_mega/tera/zmove` are now written by the dual-write, so REMOVE those three from the force-zero tuple to avoid a double-write race (the dual-write is authoritative for them).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mechanic_config.py`:

```python
def _mech_form(**over):
    """Minimal settings POST form with the mechanic-card fields. Defaults: all
    four disabled, no captain fields. Override per test."""
    f = {"league_name": "X"}
    f.update(over)
    return f


def test_post_assembles_mechanic_config(client, app_mod):
    client.post("/admin/settings", data=_mech_form(
        mech_tera_enabled="1", mech_tera_captain="1",
        mech_tera_count="1", mech_tera_maxpts="13",
        mech_tera_tiers=["Tier 4", "Tier 5"],
        mech_mega_enabled="1",
    ), headers={"X-CSRFToken": "testtoken"})
    with app_mod.get_db() as db:
        raw = db.execute("SELECT value FROM league_settings WHERE key='mechanic_config'").fetchone()["value"]
    import json
    cfg = json.loads(raw)
    assert cfg["tera"]["enabled"] is True and cfg["tera"]["is_captain_mechanic"] is True
    assert cfg["tera"]["restrict_tiers"] == ["Tier 4", "Tier 5"]
    assert cfg["tera"]["max_pts"] == 13 and cfg["tera"]["captain_count"] == 1
    assert cfg["mega"]["enabled"] is True
    assert cfg["zmove"]["enabled"] is False
    assert cfg["tera"]["tax"] == {"type": "none", "value": 0}


def test_post_dual_writes_legacy_keys(client, app_mod):
    client.post("/admin/settings", data=_mech_form(
        mech_tera_enabled="1", mech_mega_enabled="0",  # mega omitted-as-off below
    ), headers={"X-CSRFToken": "testtoken"})
    with app_mod.get_db() as db:
        got = {r["key"]: r["value"] for r in db.execute("SELECT key,value FROM league_settings")}
    assert got.get("mechanic_tera") == "1"
    assert got.get("mechanic_mega") == "0"   # unchecked → dual-written 0
    assert got.get("mechanic_zmove") == "0"


def test_post_does_not_store_mech_field_rows_raw(client, app_mod):
    client.post("/admin/settings", data=_mech_form(mech_tera_enabled="1", mech_tera_count="1"),
                headers={"X-CSRFToken": "testtoken"})
    with app_mod.get_db() as db:
        keys = {r["key"] for r in db.execute("SELECT key FROM league_settings")}
    assert not any(k.startswith("mech_") for k in keys)  # assembled, not stored raw
    assert "mechanic_config" in keys
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py -k post -v`
Expected: FAIL — `mechanic_config` not written / `mech_*` rows stored raw.

- [ ] **Step 3: Skip `mech_*` fields in the generic loop**

In `app.py`, in the generic form loop (app.py:2743), extend the skip condition:

```python
            for key, value in request.form.items():
                if key == "uber_combination":
                    continue  # handled separately below
                if key.startswith("tier_cols_") or key.startswith("tier_alloc_"):
                    continue  # assembled into tier_definitions below, not stored raw
                if key.startswith("mech_"):
                    continue  # assembled into mechanic_config below, not stored raw
                db.execute(
                    "INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)",
                    (key, value)
                )
```

- [ ] **Step 4: Remove mega/tera/zmove from the force-zero tuple**

In `app.py` (app.py:2756), change the tuple so the dual-write owns those three:

```python
            # Checkboxes not submitted when unchecked — force to '0' if missing.
            # mechanic_mega/tera/zmove are written by the mechanic_config dual-write
            # below (authoritative), so only mechanic_uber + first_pick_regular here.
            for checkbox_key in ("mechanic_uber", "first_pick_regular"):
                if checkbox_key not in request.form:
                    db.execute(
                        "INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)",
                        (checkbox_key, "0")
                    )
```

- [ ] **Step 5: Add the config assembly + dual-write**

In `app.py`, AFTER the tier_definitions assembly block (app.py:2762-2772) and BEFORE `flash("Settings saved!", ...)`, add:

```python
            # Assemble mechanic_config from the per-mechanic card fields and dual-write
            # the legacy mechanic_<name> keys so the ~40 template sites keep working.
            mcfg = {}
            for name in ("mega", "tera", "zmove", "dynamax"):
                enabled = request.form.get(f"mech_{name}_enabled") == "1"
                mcfg[name] = {
                    "enabled": enabled,
                    "is_captain_mechanic": request.form.get(f"mech_{name}_captain") == "1",
                    "restrict_tiers": request.form.getlist(f"mech_{name}_tiers"),
                    "max_pts": int(request.form.get(f"mech_{name}_maxpts", "0") or 0),
                    "captain_count": int(request.form.get(f"mech_{name}_count", "0") or 0),
                    "tax": {"type": "none", "value": 0},
                }
            db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('mechanic_config', ?)",
                       (json.dumps(mcfg),))
            # Dual-write legacy keys (mechanic_uber stays owned by the Uber section).
            for name in ("mega", "tera", "zmove"):
                db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)",
                           (f"mechanic_{name}", "1" if mcfg[name]["enabled"] else "0"))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py -v`
Expected: PASS (all T1 + T2 tests).

- [ ] **Step 7: Update `test_settings_page.py` for the removed raw fields**

The existing `test_post_persists_scalar_keys` (tests/test_settings_page.py:22-39) posts `"mechanic": "Terastallization"` and `"mechanic_tax": "0"` and asserts they persist. Since those inputs are removed in T3, and to keep this task self-consistent, remove those two keys from the form dict and the assertions now:

In `tests/test_settings_page.py`, in `test_post_persists_scalar_keys`, delete the `"mechanic": "Terastallization",` and `"mechanic_tax": "0",` entries from the `form` dict (lines within 23-32). Leave the rest.

- [ ] **Step 8: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (80 = 77 + 3 new; `test_settings_page.py` still green after the edit).

- [ ] **Step 9: Commit**

```bash
git add app.py tests/test_mechanic_config.py tests/test_settings_page.py
git commit -m "feat: dual-write mechanic_config + legacy keys on settings save (B5 T2)"
```

---

## Task 3: Settings UI — per-mechanic cards + tier-restriction + disabled tax

**Files:**
- Modify: `templates/admin/settings.html` — replace the "Battle Mechanics" section (settings.html:65-92) with per-mechanic cards; remove the `mechanic` label input (settings.html:27) and the `mechanic_tax` input (settings.html:41); update "At a Glance" (settings.html:238-248).
- Modify: `app.py` — pass `mechanic_config` + `tier_defs` to the settings GET render (app.py:2775-2778).
- Modify: `tests/test_settings_page.py` — update `EDITABLE_FIELDS`, section-heading assertions, add card/persistence assertions.

**Interfaces:**
- Consumes: `get_mechanic_config(db)` (T1); `get_tier_definitions()` (app.py:4775) for the tier-restriction checkbox list; the assembly in `admin_settings` POST (T2, reads `mech_<name>_*`).
- Produces: the per-mechanic card form fields named exactly `mech_<name>_enabled`, `mech_<name>_captain`, `mech_<name>_count`, `mech_<name>_maxpts`, `mech_<name>_tiers` (matching T2).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settings_page.py` (new tests; do not remove existing):

```python
def test_has_mechanic_cards(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "Battle Mechanics & Captains" in html
    for name in ("mega", "tera", "zmove", "dynamax"):
        assert f'name="mech_{name}_enabled"' in html
        assert f'name="mech_{name}_captain"' in html
        assert f'name="mech_{name}_maxpts"' in html
        assert f'name="mech_{name}_count"' in html
        assert f'name="mech_{name}_tiers"' in html


def test_removed_dead_inputs(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    # the inert free-text label + dead tax input are gone
    assert 'name="mechanic"' not in html
    assert 'name="mechanic_tax"' not in html


def test_tera_card_reflects_stored_config(client, app_mod):
    import json
    stored = {n: {"enabled": n == "tera", "is_captain_mechanic": n in ("tera", "zmove"),
                  "restrict_tiers": ["Tier 5"] if n == "tera" else [],
                  "max_pts": 11 if n == "tera" else 0, "captain_count": 2 if n == "tera" else 0,
                  "tax": {"type": "none", "value": 0}}
              for n in ("mega", "tera", "zmove", "dynamax")}
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_config', ?)",
                   (json.dumps(stored),))
    html = client.get("/admin/settings").get_data(as_text=True)
    assert 'value="11"' in html  # tera max_pts prefilled
```

Also UPDATE `EDITABLE_FIELDS` (tests/test_settings_page.py:7-13): remove `"mechanic"` and `"mechanic_tax"` from the list. And UPDATE `test_has_section_headings` (tests/test_settings_page.py:52-57): the section is renamed — replace `"Battle Mechanics"` with `"Battle Mechanics & Captains"` in the heading list.

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -v`
Expected: FAIL — new `mech_*` names absent; `mechanic`/`mechanic_tax` still present; heading missing.

- [ ] **Step 3: Pass `mechanic_config` to the settings render**

In `app.py`, the settings GET builds `settings` and renders (app.py:2775-2778). Add `mechanic_config`. Change the render call to:

```python
    with get_db() as db:
        mechanic_config = get_mechanic_config(db)
    return render_template("admin/settings.html",
                           settings=settings,
                           tier_defs=get_tier_definitions(),
                           mechanic_config=mechanic_config,
                           league_name=settings.get("league_name", "Pokemon Draft League"))
```

(Note: `settings` is already built earlier in the handler from a `with get_db()` block; add the `mechanic_config` fetch right before the `return render_template(...)`.)

- [ ] **Step 4: Remove the dead `mechanic` label input**

In `templates/admin/settings.html`, delete line 27:

```jinja
    {{ txt('mechanic', 'Battle Mechanic (label)', 'text', 'e.g. Terastallization') }}
```

- [ ] **Step 5: Remove the dead `mechanic_tax` input**

In `templates/admin/settings.html`, delete line 41:

```jinja
    {{ txt('mechanic_tax', 'Mechanic Tax (pts)', 'number', 'e.g. 0') }}
```

- [ ] **Step 6: Replace the Battle Mechanics section with per-mechanic cards**

In `templates/admin/settings.html`, replace the whole "Battle Mechanics" section (settings.html:65-92) with the card grid below. It mirrors the B3 tier-defs `{% for %}` card pattern and uses `mechanic_config` + `tier_defs`:

```jinja
  <!-- ── Battle Mechanics & Captains ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-4">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Battle Mechanics &amp; Captains</h2>
    <p class="text-xs text-gray-500">Enable each mechanic and (for captain mechanics) set how many captains, a point cap, and which tiers may be captains. Tax is coming in a later phase.</p>
    {% for m in [
        {'key':'mega','label':'Mega Evolution','accent':'blue'},
        {'key':'tera','label':'Tera','accent':'purple'},
        {'key':'zmove','label':'Z-Move','accent':'yellow'},
        {'key':'dynamax','label':'Dynamax','accent':'red'}] %}
    {% set b = mechanic_config[m.key] %}
    <div class="border border-gray-700 rounded-lg p-4 space-y-3">
      <div class="flex items-center justify-between">
        <span class="text-sm font-semibold text-white">{{ m.label }}</span>
        <label class="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
          <input type="checkbox" name="mech_{{ m.key }}_enabled" value="1"
                 {% if b.enabled %}checked{% endif %} class="w-4 h-4 accent-{{ m.accent }}-500">
          Enabled
        </label>
      </div>
      <label class="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
        <input type="checkbox" name="mech_{{ m.key }}_captain" value="1"
               {% if b.is_captain_mechanic %}checked{% endif %} class="w-4 h-4 accent-cyan-500">
        Captain mechanic (designate specific Pokémon)
      </label>
      <div class="grid grid-cols-2 gap-3">
        <label class="text-xs text-gray-400 space-y-1 block">Captains per team
          <input type="number" name="mech_{{ m.key }}_count" value="{{ b.captain_count }}" min="0"
                 class="w-full bg-gray-800 border border-gray-600 rounded px-2 py-2 text-white text-sm">
        </label>
        <label class="text-xs text-gray-400 space-y-1 block">Max points (0 = no cap)
          <input type="number" name="mech_{{ m.key }}_maxpts" value="{{ b.max_pts }}" min="0"
                 class="w-full bg-gray-800 border border-gray-600 rounded px-2 py-2 text-white text-sm">
        </label>
      </div>
      <div class="text-xs text-gray-400 space-y-1">
        <span>Restrict to tiers (none checked = any tier)</span>
        <div class="flex flex-wrap gap-3">
          {% for t in tier_defs %}
          <label class="flex items-center gap-1 cursor-pointer text-gray-300">
            <input type="checkbox" name="mech_{{ m.key }}_tiers" value="{{ t.name }}"
                   {% if t.name in b.restrict_tiers %}checked{% endif %} class="w-4 h-4 accent-cyan-500">
            {{ t.name }}
          </label>
          {% endfor %}
        </div>
      </div>
      <div class="flex items-center gap-2 opacity-40 pointer-events-none text-xs text-gray-500">
        <span>Tax</span>
        <select disabled class="bg-gray-800 border border-gray-600 rounded px-2 py-1"><option>none</option></select>
        <input type="number" disabled value="0" class="w-16 bg-gray-800 border border-gray-600 rounded px-2 py-1">
        <span class="italic">— coming in a later phase</span>
      </div>
    </div>
    {% endfor %}
  </section>
```

- [ ] **Step 7: Add config-driven captain bullets to "At a Glance"**

The At-a-Glance panel (settings.html:238-248) is a `<ul>` of hardcoded bullets (tier thresholds, uber points, ticket allocation, uber slots) — it has NO captain-rule line today. APPEND config-driven captain bullets to that `<ul>`. In `templates/admin/settings.html`, insert the following immediately AFTER the `<li>Uber slots per team: 2</li>` line (settings.html:246) and BEFORE the closing `</ul>` (settings.html:247):

```jinja
      {% for m in [{'key':'tera','label':'Tera'}, {'key':'zmove','label':'Z-Move'}] %}
      {% set b = mechanic_config[m.key] %}
      {% if b.enabled and b.is_captain_mechanic %}
      <li>{{ m.label }} captains: {{ b.captain_count }} per team{% if b.max_pts %}, ≤{{ b.max_pts }} pts{% endif %}{% if b.restrict_tiers %}, {{ b.restrict_tiers | join('/') }} only{% endif %}.</li>
      {% endif %}
      {% endfor %}
```

Leave the existing bullets (tier thresholds, uber points, ticket allocation, uber slots) unchanged.

- [ ] **Step 8: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py tests/test_mechanic_config.py -v`
Expected: PASS.

- [ ] **Step 9: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (83 = 80 + 3 new).

- [ ] **Step 10: Commit**

```bash
git add app.py templates/admin/settings.html tests/test_settings_page.py
git commit -m "feat: per-mechanic settings cards + tier restriction (B5 T3)"
```

---

## Task 4: `_captain_eligibility_error(...)` helper

**Files:**
- Modify: `app.py` — add `_captain_eligibility_error(db, mechanic, coach_id, pokemon_name, session_id)` near the captain/uber helpers (after `_regular_tier_label`, ~app.py:2611, or near the other Griffin helpers — place it before `draft_live_set_captain`).
- Test: add cases to `tests/test_mechanic_config.py`.

**Interfaces:**
- Consumes: `get_mechanic_config(db)` (T1); `_regular_tier_label(pts)` (app.py:2599); `pokemon_roster` (cols `points`, `is_tera_captain`, `is_zmove_captain`).
- Produces: `_captain_eligibility_error(db, mechanic, coach_id, pokemon_name, session_id) -> str | None`. `mechanic` is `"tera"` or `"zmove"`. Returns a flash message string if illegal, else `None`. `session_id` is accepted for signature stability but not required for the queries (roster is not session-scoped); pass it through for future use.

**Check order (return the FIRST failure):**
1. block `enabled` is False → `"<Label> is not enabled this season."`
2. `restrict_tiers` non-empty and the mon's `_regular_tier_label(points)` ∉ list → `"Only <tiers> Pokémon can be a <Label> captain."`
3. `max_pts` > 0 and `points > max_pts` → `"<Label> captain must be ≤<max_pts> pts."`
4. count: coach already has `captain_count` OTHER captains of this type (exclude the mon being toggled) → `"You already have <captain_count> <Label> captain(s)."`

`<Label>` = `"Tera"`/`"Z-Move"`. The mon's `points` come from `pokemon_roster` for `(coach_id, pokemon_name)`; if the row is missing, treat points as 0.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mechanic_config.py`:

```python
def _seed_captain_case(app_mod, cfg_overrides=None, roster=None):
    """Seed coaches + roster + optional mechanic_config; return nothing (uses id 1)."""
    import json
    with app_mod.get_db() as db:
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM pokemon_roster")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (1,'C','T','A')")
        for name, pts, tera, zmove in (roster or []):
            db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name, points, tier, is_tera_captain, is_zmove_captain, is_free_pick) VALUES (1,?,?,?,?,?,0)",
                       (name, pts, "", tera, zmove))
        if cfg_overrides is not None:
            db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_config', ?)",
                       (json.dumps(cfg_overrides),))
        # enable tera by default so the 'enabled' check passes unless overridden
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_tera','1')")


def _cfg(**tera):
    base = {"enabled": True, "is_captain_mechanic": True, "restrict_tiers": ["Tier 4", "Tier 5"],
            "max_pts": 13, "captain_count": 1, "tax": {"type": "none", "value": 0}}
    base.update(tera)
    other = {"enabled": False, "is_captain_mechanic": False, "restrict_tiers": [],
             "max_pts": 0, "captain_count": 0, "tax": {"type": "none", "value": 0}}
    return {"mega": dict(other), "tera": base, "zmove": dict(other), "dynamax": dict(other)}


def test_eligibility_accepts_tier5_lowpts(app_mod):
    _seed_captain_case(app_mod, _cfg(), roster=[("Weakmon", 5, 0, 0)])
    with app_mod.get_db() as db:
        err = app_mod._captain_eligibility_error(db, "tera", 1, "Weakmon", 1)
    assert err is None  # Tier 5 (5 pts), <=13, count ok


def test_eligibility_rejects_wrong_tier(app_mod):
    _seed_captain_case(app_mod, _cfg(), roster=[("Bigmon", 20, 0, 0)])
    with app_mod.get_db() as db:
        err = app_mod._captain_eligibility_error(db, "tera", 1, "Bigmon", 1)
    assert err and "Tier" in err  # 20 pts → Tier 1, not in Tier 4/5


def test_eligibility_rejects_over_maxpts(app_mod):
    _seed_captain_case(app_mod, _cfg(restrict_tiers=[], max_pts=13), roster=[("Midmon", 14, 0, 0)])
    with app_mod.get_db() as db:
        err = app_mod._captain_eligibility_error(db, "tera", 1, "Midmon", 1)
    assert err and "13" in err


def test_eligibility_rejects_over_count(app_mod):
    # count=1; one OTHER mon is already a tera captain
    _seed_captain_case(app_mod, _cfg(restrict_tiers=[], max_pts=0, captain_count=1),
                       roster=[("Cap", 5, 1, 0), ("New", 5, 0, 0)])
    with app_mod.get_db() as db:
        err = app_mod._captain_eligibility_error(db, "tera", 1, "New", 1)
    assert err and "captain" in err.lower()


def test_eligibility_reaffirm_existing_not_over_count(app_mod):
    # toggling a mon that is ALREADY the captain must not trip the count cap
    _seed_captain_case(app_mod, _cfg(restrict_tiers=[], max_pts=0, captain_count=1),
                       roster=[("Cap", 5, 1, 0)])
    with app_mod.get_db() as db:
        err = app_mod._captain_eligibility_error(db, "tera", 1, "Cap", 1)
    assert err is None


def test_eligibility_rejects_disabled(app_mod):
    _seed_captain_case(app_mod, _cfg(enabled=False), roster=[("Weakmon", 5, 0, 0)])
    with app_mod.get_db() as db:
        err = app_mod._captain_eligibility_error(db, "tera", 1, "Weakmon", 1)
    assert err and "not enabled" in err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py -k eligibility -v`
Expected: FAIL — `_captain_eligibility_error` not defined.

- [ ] **Step 3: Implement the helper**

In `app.py`, add (place it just before `draft_live_set_captain`, ~app.py:5752):

```python
_CAPTAIN_LABELS = {"tera": "Tera", "zmove": "Z-Move"}


def _captain_eligibility_error(db, mechanic, coach_id, pokemon_name, session_id):
    """Return a flash message if designating `pokemon_name` as a `mechanic`
    captain for `coach_id` is illegal per mechanic_config, else None. Checks:
    enabled → restrict_tiers → max_pts → captain_count (excluding this mon)."""
    cfg = get_mechanic_config(db)
    block = cfg.get(mechanic)
    label = _CAPTAIN_LABELS.get(mechanic, mechanic)
    if not block:
        return None
    if not block["enabled"]:
        return f"{label} is not enabled this season."

    row = db.execute(
        "SELECT points FROM pokemon_roster WHERE coach_id=? AND pokemon_name=?",
        (coach_id, pokemon_name),
    ).fetchone()
    pts = (row["points"] if row and row["points"] is not None else 0)

    tiers = block["restrict_tiers"]
    if tiers:
        tier = _regular_tier_label(pts)
        if tier not in tiers:
            return f"Only {' / '.join(tiers)} Pokémon can be a {label} captain."

    if block["max_pts"] and pts > block["max_pts"]:
        return f"{label} captain must be ≤{block['max_pts']} pts."

    cap = block["captain_count"]
    if cap:
        col = "is_tera_captain" if mechanic == "tera" else "is_zmove_captain"
        others = db.execute(
            f"SELECT COUNT(*) FROM pokemon_roster WHERE coach_id=? AND {col}=1 AND pokemon_name != ?",
            (coach_id, pokemon_name),
        ).fetchone()[0]
        if others >= cap:
            return f"You already have {cap} {label} captain(s)."
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py -k eligibility -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (89 = 83 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_mechanic_config.py
git commit -m "feat: _captain_eligibility_error helper (B5 T4)"
```

---

## Task 5: Wire the helper into `/draft/live/set_captain` (coach-facing only)

**Files:**
- Modify: `app.py` — `draft_live_set_captain` (app.py:5753-5787): gate on `value == 1`.
- Test: add route tests to `tests/test_mechanic_config.py`.

**Interfaces:**
- Consumes: `_captain_eligibility_error(...)` (T4); the route's existing `flash`/`redirect(url_for("draft_live"))` pattern.
- Produces: when `value == 1`, an illegal designation is rejected (flash + redirect, no UPDATE). `value == 0` (un-designation) always proceeds. Admin roster routes remain ungated.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_mechanic_config.py`. NOTE: `set_captain` operates on `pokemon_roster` directly (no session lookup), and the `client` fixture is admin-authenticated — but the eligibility check applies to ALL users (admin included on THIS route; only the *admin roster* route is exempt). Seed a roster and post:

```python
def test_set_captain_rejects_illegal_designation(client, app_mod):
    import json
    cfg = _cfg(restrict_tiers=["Tier 4", "Tier 5"], max_pts=13, captain_count=1)
    with app_mod.get_db() as db:
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM pokemon_roster")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (1,'C','T','A')")
        db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name, points, tier, is_tera_captain, is_zmove_captain, is_free_pick) VALUES (1,'Bigmon',20,'',0,0,0)")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_config', ?)", (json.dumps(cfg),))
    client.post("/draft/live/set_captain",
                data={"pokemon_name": "Bigmon", "captain_type": "tera", "value": "1", "coach_id": "1"},
                headers={"X-CSRFToken": "testtoken"})
    with app_mod.get_db() as db:
        flag = db.execute("SELECT is_tera_captain FROM pokemon_roster WHERE pokemon_name='Bigmon'").fetchone()[0]
    assert flag == 0  # Tier-1 mon rejected → flag NOT set


def test_set_captain_allows_legal_designation(client, app_mod):
    import json
    cfg = _cfg(restrict_tiers=["Tier 4", "Tier 5"], max_pts=13, captain_count=1)
    with app_mod.get_db() as db:
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM pokemon_roster")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (1,'C','T','A')")
        db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name, points, tier, is_tera_captain, is_zmove_captain, is_free_pick) VALUES (1,'Weakmon',5,'',0,0,0)")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_config', ?)", (json.dumps(cfg),))
    client.post("/draft/live/set_captain",
                data={"pokemon_name": "Weakmon", "captain_type": "tera", "value": "1", "coach_id": "1"},
                headers={"X-CSRFToken": "testtoken"})
    with app_mod.get_db() as db:
        flag = db.execute("SELECT is_tera_captain FROM pokemon_roster WHERE pokemon_name='Weakmon'").fetchone()[0]
    assert flag == 1  # Tier-5 5pt mon accepted


def test_set_captain_undesignation_always_allowed(client, app_mod):
    import json
    cfg = _cfg(enabled=False)  # even disabled, un-designating must work
    with app_mod.get_db() as db:
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM pokemon_roster")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (1,'C','T','A')")
        db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name, points, tier, is_tera_captain, is_zmove_captain, is_free_pick) VALUES (1,'Cap',5,'',1,0,0)")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_config', ?)", (json.dumps(cfg),))
    client.post("/draft/live/set_captain",
                data={"pokemon_name": "Cap", "captain_type": "tera", "value": "0", "coach_id": "1"},
                headers={"X-CSRFToken": "testtoken"})
    with app_mod.get_db() as db:
        flag = db.execute("SELECT is_tera_captain FROM pokemon_roster WHERE pokemon_name='Cap'").fetchone()[0]
    assert flag == 0  # cleared regardless of config
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py -k set_captain -v`
Expected: FAIL — `test_set_captain_rejects_illegal_designation` fails (flag gets set, == 1) because no gate yet.

- [ ] **Step 3: Add the gate**

In `app.py`, in `draft_live_set_captain`, insert the check right before the UPDATE block (app.py:5780-5785), so the final section reads:

```python
    col = "is_tera_captain" if captain_type == "tera" else "is_zmove_captain"
    with get_db() as db:
        if value == 1:
            err = _captain_eligibility_error(db, captain_type, target_coach_id, pokemon_name, None)
            if err:
                flash(err, "warning")
                return redirect(url_for("draft_live"))
        db.execute(
            f"UPDATE pokemon_roster SET {col}=? WHERE coach_id=? AND pokemon_name=?",
            (value, target_coach_id, pokemon_name)
        )

    return redirect(url_for("draft_live"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py -k set_captain -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Mutation check (prove the gate is load-bearing)**

Temporarily change `if value == 1:` to `if False:` and re-run:
Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py::test_set_captain_rejects_illegal_designation -q`
Expected: FAIL (flag becomes 1). Then REVERT the change and re-run to confirm PASS.

- [ ] **Step 6: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (92 = 89 + 3 new).

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_mechanic_config.py
git commit -m "feat: enforce captain eligibility on set_captain (B5 T5)"
```

---

## Task 6: Behavior-preservation sweep + build marker

**Files:**
- Create: `tests/test_mechanic_config.py` — add an equivalence test proving the current season is unchanged.
- Modify: `templates/base.html` — bump the build marker.
- Docs: none required.

**Interfaces:**
- Consumes: everything from T1–T5.
- Produces: an equivalence test asserting that with NO `mechanic_config` stored (a current DB), saving the settings page with the migrated defaults re-emits the same legacy keys, and that a captain that was legal under the old client rules is still legal.

- [ ] **Step 1: Write the equivalence test**

Add to `tests/test_mechanic_config.py`:

```python
def test_current_season_unchanged_end_to_end(client, app_mod):
    """A DB with no mechanic_config (today's state): the migrated config's captain
    rules match the old effective client rules, and legacy keys round-trip."""
    # legacy keys as a live season would have them
    with app_mod.get_db() as db:
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM pokemon_roster")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (1,'C','T','A')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_tera','1')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('mechanic_zmove','1')")
        # a Tier-5 5pt mon — legal captain under the old ≤13 + Tier4/5 rule
        db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name, points, tier, is_tera_captain, is_zmove_captain, is_free_pick) VALUES (1,'Weakmon',5,'',0,0,0)")
    # migrated config must accept that mon as a tera captain
    with app_mod.get_db() as db:
        assert app_mod._captain_eligibility_error(db, "tera", 1, "Weakmon", 1) is None
    # and a Tier-1 20pt mon must be rejected (old rule)
    with app_mod.get_db() as db:
        db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name, points, tier, is_tera_captain, is_zmove_captain, is_free_pick) VALUES (1,'Bigmon',20,'',0,0,0)")
    with app_mod.get_db() as db:
        assert app_mod._captain_eligibility_error(db, "tera", 1, "Bigmon", 1) is not None
```

- [ ] **Step 2: Run it to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/test_mechanic_config.py::test_current_season_unchanged_end_to_end -v`
Expected: PASS (the helper + migration already implement this; this is a guard against future regressions).

- [ ] **Step 3: Bump the build marker**

In `templates/base.html`, find the `console.log("YDL build: ...")` line and bump it to:

```html
  console.log("YDL build: mechanic-config-b5-v47");
```

(If a later hotfix already advanced the version past v46, use the next integer above the current marker.)

- [ ] **Step 4: Run the full suite**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (93 = 92 + 1 new).

- [ ] **Step 5: Commit**

```bash
git add templates/base.html tests/test_mechanic_config.py
git commit -m "test: current-season equivalence + build marker (B5 T6)"
```

---

## Post-plan: finishing the branch

After all six tasks pass and the whole-branch review is clean, use
`superpowers:finishing-a-development-branch` to merge `feat/mechanic-config-b5`
into `main` (`--no-ff`), verify the suite on the merged result, delete the
branch. Then the controller offers to push (`git push origin HEAD:master`) and
deploy (PythonAnywhere reload) on the user's approval — do not auto-push.
