# Phase 1B-1: Cohesive Settings Page (Reorg + Surface) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `admin/settings.html` into clearly-titled sections and surface every existing setting — including the currently-invisible mega tier thresholds — plus a read-only "mechanics at a glance" panel and a playoffs cross-link, **with zero behavior change**.

**Architecture:** Pure template rebuild. The `admin_settings` POST handler already writes every submitted form field, so surfacing new inputs (the `mega_*_pts` numbers) needs no route change; the reorg only rewrites `templates/admin/settings.html`, preserving every existing input `name` so nothing becomes uneditable. A regression contract test locks the editable-field set before the rewrite.

**Tech Stack:** Flask/Jinja2 + Tailwind (CDN), pytest (existing harness from `tests/conftest.py`).

This is slice **B1** of Phase 1B (spec: `docs/superpowers/specs/2026-06-30-settings-rework-and-draft-board-templates-design.md`, §5.1/§5.2/§5.9, the "reorg + surface, no behavior change" portion). Later slices (B2 tiers/draft-mode/structure, B3 mechanics/captains, B4 standings/transactions) add the configurable logic and their editor sections.

## Global Constraints

- Run Python only through the venv: `D:/Yuri Draft League/.venv/Scripts/python.exe` (Windows). Never base python.
- **No existing setting key is renamed or dropped.** Every input `name` present today must still be present after the rebuild.
- **No route/logic change** — this slice only edits `templates/admin/settings.html` and adds tests. Draft/standings/settings behavior is byte-for-byte unchanged.
- **Never** `git add -A`; stage explicit paths only. Never commit `*.db` or `backups/`.
- Match the existing admin template style: `{% extends "base.html" %}` + Tailwind, a `← Admin` back link, `gray-800`/`gray-700` cards, `yellow-400` headings.
- Bump the `base.html` build marker on the deploy commit (not required per task).

## File Structure

- `templates/admin/settings.html` — rebuilt into titled sections (only file with real changes).
- `tests/test_settings_page.py` — NEW: regression contract test + new-section/mega-input tests.

---

## Task 1: Regression contract test (safety net for the rebuild)

Locks in that the settings page persists every current key and exposes every current editable field. Passes against the *current* template; it must still pass after the rebuild.

**Files:**
- Create: `tests/test_settings_page.py`

**Interfaces:**
- Consumes: `client` fixture (admin-authenticated Flask test client, from `tests/conftest.py`).
- Produces: `CURRENT_KEYS` list of the settings keys the page must keep editable (used conceptually by Task 2's reviewer).

- [ ] **Step 1: Write the contract test**

```python
# tests/test_settings_page.py
"""B1: the settings page must keep every existing key editable and persist it.
Guards the section reorg against silently dropping a field."""

# Every editable input name currently on /admin/settings.
EDITABLE_FIELDS = [
    "league_name", "season", "points_budget", "fa_limit", "mechanic",
    "mechanic_tax", "num_players", "num_pools", "current_week", "format",
    "match_format", "mechanic_mega", "mechanic_tera", "mechanic_zmove",
    "mechanic_uber", "uber_combination", "draft_format",
    "draft_free_pick_type", "points_budget_griffin", "discord_webhook_url",
]


def test_get_exposes_every_editable_field(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    missing = [f for f in EDITABLE_FIELDS if f'name="{f}"' not in html]
    assert not missing, f"settings page dropped fields: {missing}"


def test_post_persists_scalar_keys(client, app_mod):
    form = {
        "league_name": "Yuri Cup S9", "season": "9", "points_budget": "45",
        "fa_limit": "3", "mechanic": "Terastallization", "mechanic_tax": "0",
        "num_players": "18", "num_pools": "2", "current_week": "5",
        "format": "Gen 9 NatDex", "match_format": "BO3",
        "mechanic_mega": "1", "mechanic_tera": "1",
        "draft_format": "griffin", "draft_free_pick_type": "four_any",
        "points_budget_griffin": "70", "discord_webhook_url": "",
        "uber_combination": "2_bronze",
    }
    client.post("/admin/settings", data=form)
    with app_mod.get_db() as db:
        got = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM league_settings")}
    for k, v in form.items():
        if k == "uber_combination":
            continue  # joined list, checked separately
        assert got.get(k) == v, f"{k} not persisted (got {got.get(k)!r})"
    assert got.get("uber_combination") == "2_bronze"


def test_unchecked_mechanic_checkboxes_force_zero(client, app_mod):
    # mechanic_mega omitted from the form -> handler must store "0"
    client.post("/admin/settings", data={"league_name": "X"})
    with app_mod.get_db() as db:
        got = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM league_settings")}
    assert got.get("mechanic_mega") == "0"
    assert got.get("mechanic_uber") == "0"
```

- [ ] **Step 2: Run it against the current template — must PASS**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -v`
Expected: 3 passed (the page/route already satisfy this contract).

- [ ] **Step 3: Commit**

```bash
cd "D:/Yuri Draft League"
git add tests/test_settings_page.py
git commit -m "test: settings-page editable-field + persistence contract"
```

---

## Task 2: Rebuild settings.html into cohesive sections (+ mega tiers, at-a-glance, playoffs link)

Reorganize all existing controls into titled sections, surface the `mega_*_pts` thresholds (previously no UI), add a read-only "mechanics at a glance" panel and a playoffs cross-link. No control is removed; the JS toggles are preserved.

**Files:**
- Modify: `templates/admin/settings.html` (full rewrite of the body)
- Test: `tests/test_settings_page.py` (add section/mega tests)

**Interfaces:**
- Consumes: the same `settings` dict the route already passes; no new route inputs.
- Produces: inputs `mega_platinum_pts`, `mega_gold_pts`, `mega_silver_pts`, `mega_bronze_pts` (persisted by the unchanged POST loop).

- [ ] **Step 1: Write the new-section + mega tests (fail first)**

```python
# add to tests/test_settings_page.py
def test_has_section_headings(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    for heading in ["League Identity", "Schedule & Matches", "Battle Mechanics",
                    "Uber Picks", "Draft Format", "Mega Tiers", "Playoffs",
                    "At a Glance"]:
        assert heading in html, f"missing section: {heading}"


def test_surfaces_mega_tier_inputs(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    for f in ["mega_platinum_pts", "mega_gold_pts", "mega_silver_pts", "mega_bronze_pts"]:
        assert f'name="{f}"' in html, f"missing mega input: {f}"


def test_mega_tiers_persist(client, app_mod):
    client.post("/admin/settings", data={
        "league_name": "X", "mega_platinum_pts": "30", "mega_gold_pts": "29",
        "mega_silver_pts": "28", "mega_bronze_pts": "27",
    })
    with app_mod.get_db() as db:
        got = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM league_settings")}
    assert got.get("mega_platinum_pts") == "30" and got.get("mega_bronze_pts") == "27"
```

- [ ] **Step 2: Run to confirm the section/mega tests FAIL**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -k "section or mega" -v`
Expected: FAIL (`missing section: League Identity`, `missing mega input: mega_platinum_pts`).

- [ ] **Step 3: Replace `templates/admin/settings.html` with the sectioned version**

Write the whole file exactly as below:

```html
{% extends "base.html" %}
{% block title %}Settings – Admin{% endblock %}
{% block content %}

{% macro txt(key, label, type='text', placeholder='', hint='') %}
<div>
  <label class="block text-sm font-semibold text-gray-300 mb-1">{{ label }}</label>
  <input type="{{ type }}" name="{{ key }}" value="{{ settings.get(key, '') }}" placeholder="{{ placeholder }}"
         class="w-full bg-gray-800 border border-gray-600 rounded-lg px-4 py-2.5 text-white focus:border-yellow-500 focus:outline-none transition-colors">
  {% if hint %}<p class="text-xs text-gray-500 mt-1">{{ hint }}</p>{% endif %}
</div>
{% endmacro %}

<div class="flex items-center gap-3 mb-6">
    <a href="/admin" class="text-gray-400 hover:text-white">← Admin</a>
    <h1 class="text-2xl font-bold text-yellow-400">League Settings</h1>
</div>

<form method="POST" class="max-w-2xl space-y-5">

  <!-- ── League Identity ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-4">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">League Identity</h2>
    {{ txt('league_name', 'League Name', 'text', 'e.g. Yuri Cup Season 8') }}
    {{ txt('season', 'Season Number', 'text', 'e.g. 8') }}
    {{ txt('format', 'Battle Format', 'text', 'e.g. Gen 9 National Dex Ubers') }}
    {{ txt('mechanic', 'Battle Mechanic (label)', 'text', 'e.g. Terastallization') }}
    <div class="grid grid-cols-2 gap-4">
      {{ txt('num_pools', 'Number of Pools', 'number', 'e.g. 2') }}
      {{ txt('num_players', 'Number of Players', 'number', 'e.g. 18') }}
    </div>
  </section>

  <!-- ── Schedule & Matches ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-4">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Schedule & Matches</h2>
    <div class="grid grid-cols-2 gap-4">
      {{ txt('current_week', 'Current Week', 'number', 'e.g. 7') }}
      {{ txt('fa_limit', 'FA Limit per season', 'number', 'e.g. 3') }}
    </div>
    {{ txt('mechanic_tax', 'Mechanic Tax (pts)', 'number', 'e.g. 0') }}
    <div>
      <label class="block text-sm font-semibold text-gray-300 mb-1">Match Format</label>
      <div class="flex gap-3">
        <label class="flex items-center gap-2 cursor-pointer px-4 py-2.5 rounded-lg border transition-colors
                      {% if settings.get('match_format','BO1') == 'BO1' %}border-yellow-500 bg-yellow-500/10{% else %}border-gray-600 bg-gray-800{% endif %}">
          <input type="radio" name="match_format" value="BO1" {% if settings.get('match_format','BO1') == 'BO1' %}checked{% endif %} class="accent-yellow-500">
          <span class="text-white font-semibold">Best of 1</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer px-4 py-2.5 rounded-lg border transition-colors
                      {% if settings.get('match_format') == 'BO3' %}border-yellow-500 bg-yellow-500/10{% else %}border-gray-600 bg-gray-800{% endif %}">
          <input type="radio" name="match_format" value="BO3" {% if settings.get('match_format') == 'BO3' %}checked{% endif %} class="accent-yellow-500">
          <span class="text-white font-semibold">Best of 3</span>
        </label>
      </div>
      <p class="text-xs text-gray-500 mt-1">BO3 allows up to 3 games per match.</p>
    </div>
    {{ txt('discord_webhook_url', 'Discord Webhook URL', 'url', 'https://discord.com/api/webhooks/...',
           'When set, match results auto-post to this Discord channel.') }}
    {% if settings.get('discord_webhook_url') %}
    <p class="text-xs text-green-500">✓ Webhook configured — results will post to Discord</p>
    {% endif %}
  </section>

  <!-- ── Battle Mechanics ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-3">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Battle Mechanics</h2>
    <p class="text-xs text-gray-500">Which special mechanics are in use this season. (Per-mechanic captain / tax rules arrive in a later phase.)</p>
    <div class="flex flex-wrap gap-3">
      <label class="flex items-center gap-2 cursor-pointer px-4 py-2.5 rounded-lg border transition-colors
                    {% if settings.get('mechanic_mega','0') == '1' %}border-blue-500 bg-blue-500/10{% else %}border-gray-600 bg-gray-800{% endif %}">
        <input type="checkbox" name="mechanic_mega" value="1" {% if settings.get('mechanic_mega','0') == '1' %}checked{% endif %} class="w-4 h-4 accent-blue-500">
        <span class="text-white font-semibold">Mega Evolution</span>
      </label>
      <label class="flex items-center gap-2 cursor-pointer px-4 py-2.5 rounded-lg border transition-colors
                    {% if settings.get('mechanic_tera','0') == '1' %}border-purple-500 bg-purple-500/10{% else %}border-gray-600 bg-gray-800{% endif %}">
        <input type="checkbox" name="mechanic_tera" value="1" {% if settings.get('mechanic_tera','0') == '1' %}checked{% endif %} class="w-4 h-4 accent-purple-500">
        <span class="text-white font-semibold">Tera Captain</span>
      </label>
      <label class="flex items-center gap-2 cursor-pointer px-4 py-2.5 rounded-lg border transition-colors
                    {% if settings.get('mechanic_zmove','0') == '1' %}border-yellow-500 bg-yellow-500/10{% else %}border-gray-600 bg-gray-800{% endif %}">
        <input type="checkbox" name="mechanic_zmove" value="1" {% if settings.get('mechanic_zmove','0') == '1' %}checked{% endif %} class="w-4 h-4 accent-yellow-500">
        <span class="text-white font-semibold">Z-Move Captain</span>
      </label>
      <label class="flex items-center gap-2 cursor-pointer px-4 py-2.5 rounded-lg border transition-colors
                    {% if settings.get('mechanic_uber','0') == '1' %}border-red-500 bg-red-500/10{% else %}border-gray-600 bg-gray-800{% endif %}">
        <input type="checkbox" name="mechanic_uber" value="1" id="mechanic_uber_chk" {% if settings.get('mechanic_uber','0') == '1' %}checked{% endif %}
               class="w-4 h-4 accent-red-500" onchange="document.getElementById('uber_combo_row').style.display=this.checked?'block':'none'">
        <span class="text-white font-semibold">Uber Picks</span>
      </label>
    </div>
  </section>

  <!-- ── Uber Picks ── -->
  <section id="uber_combo_row" class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-3" {% if settings.get('mechanic_uber','0') != '1' %}style="display:none"{% endif %}>
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Uber Picks</h2>
    <p class="text-xs text-gray-500">Allowed uber combinations. Point values: Platinum 30 · Gold 29 · Silver 28 · Bronze 27. <span class="text-gray-600">(Enforcement is opt-in in a later phase.)</span></p>
    {% set combo_list = settings.get('uber_combination', '2_bronze').split(',') %}
    <div class="flex flex-col gap-2">
      <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" name="uber_combination" value="1_platinum"        class="w-4 h-4 accent-red-500" {% if '1_platinum'        in combo_list %}checked{% endif %}><span class="text-sm text-gray-300">1 Platinum (30) — 1 slot</span></label>
      <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" name="uber_combination" value="1_gold_1_bronze"   class="w-4 h-4 accent-red-500" {% if '1_gold_1_bronze'   in combo_list %}checked{% endif %}><span class="text-sm text-gray-300">1 Gold (29) + 1 Bronze (27) — 2 slots</span></label>
      <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" name="uber_combination" value="1_silver_1_bronze" class="w-4 h-4 accent-red-500" {% if '1_silver_1_bronze' in combo_list %}checked{% endif %}><span class="text-sm text-gray-300">1 Silver (28) + 1 Bronze (27) — 2 slots</span></label>
      <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" name="uber_combination" value="2_silver"          class="w-4 h-4 accent-red-500" {% if '2_silver'          in combo_list %}checked{% endif %}><span class="text-sm text-gray-300">2 Silver (28 each) — 2 slots</span></label>
      <label class="flex items-center gap-2 cursor-pointer"><input type="checkbox" name="uber_combination" value="2_bronze"          class="w-4 h-4 accent-red-500" {% if '2_bronze'          in combo_list %}checked{% endif %}><span class="text-sm text-gray-300">2 Bronze (27 each) — 2 slots</span></label>
    </div>
  </section>

  <!-- ── Draft Format & Budget ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-4">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Draft Format & Budget</h2>
    <div class="flex flex-col gap-2">
      <label class="flex items-center gap-3 cursor-pointer px-4 py-3 rounded-lg border transition-colors
                    {% if settings.get('draft_format','') != 'griffin' %}border-gray-500 bg-gray-700/50{% else %}border-gray-700 bg-gray-800{% endif %}">
        <input type="radio" name="draft_format" value="" {% if settings.get('draft_format','') != 'griffin' %}checked{% endif %} class="accent-gray-400" onchange="updateDraftFormat(this.value)">
        <div><span class="text-white font-semibold block">Legacy</span><span class="text-xs text-gray-500">Standard tiered draft with optional free-pick rules.</span></div>
      </label>
      <label class="flex items-center gap-3 cursor-pointer px-4 py-3 rounded-lg border transition-colors
                    {% if settings.get('draft_format','') == 'griffin' %}border-yellow-500 bg-yellow-500/10{% else %}border-gray-700 bg-gray-800{% endif %}">
        <input type="radio" name="draft_format" value="griffin" {% if settings.get('draft_format','') == 'griffin' %}checked{% endif %} class="accent-yellow-500" onchange="updateDraftFormat(this.value)">
        <div><span class="text-white font-semibold block">Plan Griffin</span><span class="text-xs text-gray-500">Coaches draft via Tier Tickets or a Points budget. Per-coach format in <a href="/admin/teams" class="text-yellow-400 hover:underline">Admin → Teams</a>.</span></div>
      </label>
    </div>
    <div id="legacy-options" class="pl-2 {% if settings.get('draft_format','') == 'griffin' %}hidden{% endif %}">
      <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Free Pick Rule</label>
      <div class="flex flex-col gap-2">
        <label class="flex items-center gap-3 cursor-pointer px-4 py-2.5 rounded-lg border border-gray-700/60 bg-gray-800/60">
          <input type="radio" name="draft_free_pick_type" value="none" {% if settings.get('draft_free_pick_type','none') == 'none' %}checked{% endif %} class="accent-gray-400">
          <div><span class="text-white font-semibold block text-sm">No free picks</span></div>
        </label>
        <label class="flex items-center gap-3 cursor-pointer px-4 py-2.5 rounded-lg border border-gray-700/60 bg-gray-800/60">
          <input type="radio" name="draft_free_pick_type" value="one_per_tier" {% if settings.get('draft_free_pick_type') == 'one_per_tier' %}checked{% endif %} class="accent-green-500">
          <div><span class="text-white font-semibold block text-sm">One free pick per tier</span></div>
        </label>
        <label class="flex items-center gap-3 cursor-pointer px-4 py-2.5 rounded-lg border border-gray-700/60 bg-gray-800/60">
          <input type="radio" name="draft_free_pick_type" value="four_any" {% if settings.get('draft_free_pick_type') == 'four_any' %}checked{% endif %} class="accent-green-500">
          <div><span class="text-white font-semibold block text-sm">Four free picks (any tier)</span></div>
        </label>
      </div>
    </div>
    <div id="griffin-options" class="pl-2 {% if settings.get('draft_format','') != 'griffin' %}hidden{% endif %}">
      <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Points Budget (Griffin "Points" coaches)</label>
      <input type="number" name="points_budget_griffin" min="1" max="999" value="{{ settings.get('points_budget_griffin', '70') }}" placeholder="70"
             class="w-40 bg-gray-800 border border-gray-600 rounded-lg px-4 py-2.5 text-white focus:border-yellow-500 focus:outline-none">
    </div>
    {{ txt('points_budget', 'Points Budget (Legacy)', 'number', 'e.g. 45') }}
  </section>

  <!-- ── Mega Tiers (NEW: previously invisible) ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-3">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Mega Tiers</h2>
    <p class="text-xs text-gray-500">Minimum points at which a Mega counts as each uber tier (feeds <code>_mega_tier_label</code>). 0 = disabled.</p>
    <div class="grid grid-cols-2 gap-4">
      {{ txt('mega_platinum_pts', 'Platinum ≥', 'number', '0') }}
      {{ txt('mega_gold_pts', 'Gold ≥', 'number', '0') }}
      {{ txt('mega_silver_pts', 'Silver ≥', 'number', '0') }}
      {{ txt('mega_bronze_pts', 'Bronze ≥', 'number', '0') }}
    </div>
  </section>

  <!-- ── Playoffs (read-only surface + link) ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-2">
    <h2 class="text-sm font-bold text-yellow-400 uppercase tracking-wide">Playoffs</h2>
    <p class="text-xs text-gray-500">Managed in <a href="/admin/playoffs" class="text-yellow-400 hover:underline">Admin → Playoffs</a>.</p>
    <ul class="text-sm text-gray-300 space-y-1">
      <li>Format: <b>{{ settings.get('playoff_format') or '—' }}</b></li>
      <li>Teams: <b>{{ settings.get('playoff_players') or '—' }}</b> · Byes: <b>{{ settings.get('playoff_byes') or '—' }}</b></li>
      <li>Match format: <b>{{ settings.get('playoff_match_format') or '—' }}</b></li>
    </ul>
  </section>

  <!-- ── At a Glance (read-only: still-hardcoded rules) ── -->
  <section class="bg-gray-900/40 border border-gray-700 rounded-xl p-5 space-y-2">
    <h2 class="text-sm font-bold text-gray-300 uppercase tracking-wide">This Season's Mechanics · At a Glance</h2>
    <p class="text-xs text-gray-600">Fixed this season — configurable in a later phase.</p>
    <ul class="text-sm text-gray-400 space-y-1 list-disc list-inside">
      <li>Regular tiers: T1 ≥16 · T2 ≥13 · T3 ≥9 · T4 ≥5 · T5 ≥0 pts</li>
      <li>Uber points: 27 Bronze · 28 Silver · 29 Gold · 30 Platinum</li>
      <li>Ticket allocation: T1:1 · T2:1 · T3:2 · T4:2 · T5:2</li>
      <li>Roster cap: 10 picks · Uber slots: 2 · First pick must be regular-tier</li>
    </ul>
  </section>

  <div class="pt-2">
    <button type="submit" class="px-6 py-3 bg-yellow-500 hover:bg-yellow-400 text-gray-900 font-bold rounded-lg transition-colors">Save Settings</button>
  </div>
</form>

<script>
function updateDraftFormat(val) {
  const isGriffin = val === 'griffin';
  document.getElementById('legacy-options').classList.toggle('hidden', isGriffin);
  document.getElementById('griffin-options').classList.toggle('hidden', !isGriffin);
}
</script>

{% endblock %}
```

- [ ] **Step 4: Run the full settings-page test file — all pass**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/test_settings_page.py -v`
Expected: all pass (contract from Task 1 still green; new section + mega tests now green).

- [ ] **Step 5: Run the whole suite (nothing else regressed)**

Run: `cd "D:/Yuri Draft League" && ./.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 6: Manual smoke (optional but recommended)**

Run the dev server (`./.venv/Scripts/python.exe app.py`), open `/admin/settings` as admin: confirm the sectioned layout, that toggling Uber Picks shows/hides the Uber combinations card, that switching Legacy/Plan Griffin toggles the sub-options, and that Save persists (reload shows values). Stop the server.

- [ ] **Step 7: Commit**

```bash
cd "D:/Yuri Draft League"
git add templates/admin/settings.html tests/test_settings_page.py
git commit -m "feat: cohesive settings page reorg + surface mega tiers/playoffs/at-a-glance (no behavior change)"
```

---

## Notes for the implementer
- This slice changes **only** the template + tests. If any test needs a route change, stop — that would violate the no-behavior-change constraint for B1.
- `current_week` is also editable via the separate set-week route; keeping it here is intentional (both write the same key).
- Later slices (B2–B4) will add editor sections for tier definitions, mechanic/captain config, draft structure, standings, and transactions into this same page.
