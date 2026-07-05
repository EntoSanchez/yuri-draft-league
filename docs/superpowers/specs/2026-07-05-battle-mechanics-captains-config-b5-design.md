# Battle Mechanics & Captains Config (Phase 1B-5) — Design

**Status:** Approved design; ready for implementation planning.
**Parent spec:** `docs/superpowers/specs/2026-06-30-settings-rework-and-draft-board-templates-design.md` §5.3
**Predecessors merged/deployed:** B1 (settings reorg), B2 (draft structure), B3 (tier definitions), B4 (draft-mode policy).
**Ground-truth surface map:** `scratchpad/b5_map_digest.md` (regenerable) and memory `project_ydl_mechanic_surface`.

---

## 1. Goal

Replace the four bare battle-mechanic toggles (`mechanic_mega/tera/zmove/uber`) and the
inert `mechanic`/`mechanic_tax` fields with a single configuration-driven
`mechanic_config` JSON that captures every per-mechanic rule the league uses — enable,
captain designation, tier restriction, point cap, captain count, and (schema-only for
now) tax. Add **server-side enforcement** of captain eligibility, closing the current
client-only-limits bypass hole, while keeping the **current season byte-for-byte
unchanged**.

## 2. Core constraints (from the surface map — MUST respect)

These are verified facts about the current code. Violating them breaks behavior
preservation.

- **`mechanic_tax` is INERT.** The string "tax" appears nowhere in `app.py`. No surcharge
  is applied at pick time today. Any tax system is greenfield → **deferred to B6**.
- **`mechanic_*` toggles are UI-visibility gates only.** None gate pick/roster logic.
  `mechanic_uber` is never read in `draft_live_pick` (uber routing is structural via
  tier_label / points 27–30 / mega thresholds). `mechanic_mega` only shows/hides a
  draftboard column. `mechanic_tera`/`mechanic_zmove` only show/hide captain UI.
- **~40 template sites read `mechanic_tera/zmove/mega`** (team.html ×12, roster.html ×8,
  draftboard.html tera-mark ×7 bands + JS, draft_live.html, draft_prep.html,
  season_archive.html, draft.html roster-cap math). These MUST NOT change → dual-write.
- **Captain columns:** `is_tera_captain` (base schema), `is_zmove_captain` (ALTER
  migration, app.py:61). No `is_mega_captain`/`is_dynamax_captain`. Reads use
  `'is_zmove_captain' in r.keys()` guards — preserve them.
- **Captain limits are client-side only.** `/draft/live/set_captain` (app.py:5753) is a
  raw single-column UPDATE with no checks. Admin roster route also unchecked.
- **Dynamax has ZERO runtime presence** — greenfield, config-only in B5.
- **`draft_live_pick` pick-cost path** (budget check 5541–5556, ticket check 5558–5584,
  uber branch 5530–5539) MUST be untouched in B5.

## 3. Data model

### 3.1 The `mechanic_config` setting

One JSON blob stored under `league_settings` key `mechanic_config`. One block per
mechanic. **Constraints stack** — each mechanic is a set of independent, composable
fields, not a single mode enum.

```jsonc
{
  "mega":    { "enabled": true,  "is_captain_mechanic": false,
               "restrict_tiers": [], "max_pts": 0, "captain_count": 0,
               "tax": {"type": "none", "value": 0} },
  "tera":    { "enabled": true,  "is_captain_mechanic": true,
               "restrict_tiers": ["Tier 4", "Tier 5"], "max_pts": 13,
               "captain_count": 1, "tax": {"type": "none", "value": 0} },
  "zmove":   { "enabled": false, "is_captain_mechanic": true,
               "restrict_tiers": ["Tier 4", "Tier 5"], "max_pts": 13,
               "captain_count": 1, "tax": {"type": "none", "value": 0} },
  "dynamax": { "enabled": false, "is_captain_mechanic": false,
               "restrict_tiers": [], "max_pts": 0, "captain_count": 0,
               "tax": {"type": "none", "value": 0} }
}
```

Field semantics:

| Field | Meaning | "no constraint" value |
|-------|---------|-----------------------|
| `enabled` | on/off (drives the legacy `mechanic_<name>` key on save) | `false` |
| `is_captain_mechanic` | mechanic uses per-Pokémon captain designation | `false` |
| `restrict_tiers` | only Pokémon whose tier ∈ list may use it | `[]` (any) |
| `max_pts` | designated/eligible Pokémon must cost ≤ this | `0` (no cap) |
| `captain_count` | max captains of this type per team | `0` (n/a for non-captain mechanics) |
| `tax` | `{type: none\|flat\|multiplier, value}` — **schema-only in B5** | `{"type":"none","value":0}` |

Only `tera` and `zmove` are captain mechanics by default. `mega`/`dynamax` carry the
full schema for uniformity but default `is_captain_mechanic=false`.

### 3.2 Migration / defaults (behavior-preservation lever)

`get_mechanic_config(db)` is the single read path. When the `mechanic_config` key is
absent (every current DB), it **derives** the config:

- `enabled` for each of mega/tera/zmove ← the current legacy key
  (`settings.get("mechanic_<name>", "0") == "1"`); dynamax ← `false`.
- Captain defaults hard-coded to reproduce today's **effective** client rules:
  tera & zmove → `is_captain_mechanic=true`, `restrict_tiers=["Tier 4","Tier 5"]`,
  `max_pts=13`, `captain_count=1`.
- All `tax` → `{"type":"none","value":0}`.

The dropped combined tera+zmove ≤18 cross-cap (see §5) is simply not represented.
Because the migrated defaults equal the current effective rules, **every captain the
current draft already designated remains valid.** The accessor always deep-copies list
fields (`restrict_tiers`) to avoid the shallow-copy footgun hit in B3.

### 3.3 Dual-write (zero template churn)

Saving the settings page:
1. assembles `mechanic_config` JSON from the form and writes it, AND
2. writes the legacy keys `mechanic_mega`, `mechanic_tera`, `mechanic_zmove`,
   `mechanic_uber` as `"1"`/`"0"` derived from each block's `enabled`.

All ~40 template sites keep reading the legacy keys unchanged. No template edits for
mechanic-visibility gating. (Uber keeps its existing separate settings section and its
`uber_combination` handling untouched.)

## 4. Server-side enforcement

### 4.1 The eligibility helper

New function:

```
_captain_eligibility_error(db, mechanic, coach_id, pokemon_name, session_id) -> str | None
```

Returns a user-facing flash message if the designation is illegal, else `None`. Reads
the mechanic's block from `get_mechanic_config(db)` and checks, in order:

1. **enabled** — false → `"<Mechanic> is not enabled this season."`
2. **restrict_tiers** — non-empty and the Pokémon's regular tier ∉ list →
   `"Only <tiers> Pokémon can be <Mechanic> captains."`
3. **max_pts** — >0 and Pokémon points > cap →
   `"<Mechanic> captain must be ≤<max_pts> pts."`
4. **captain_count** — coach already has `captain_count` OTHER captains of this type
   (the Pokémon being toggled is excluded from the count, so re-affirming an existing
   captain never spuriously trips the cap) → `"You already have <n> <Mechanic> captain(s)."`

The Pokémon's tier is resolved from its points via the existing `_regular_tier_label`
(configurable tier definitions from B3). Points come from the roster/draft row. Note:
uber/mega Pokémon whose points fall outside the regular-tier columns resolve to an
empty tier label and therefore FAIL a non-empty `restrict_tiers` check — which is the
desired behavior for a Tier-4/5-restricted captain mechanic (an uber mon cannot be a
Tier-4/5 captain).

### 4.2 Wiring

- `/draft/live/set_captain` (app.py:5753): call the helper **only when `value=='1'`**
  (designating). Un-designating (`value=='0'`) is always allowed. On error, flash and
  redirect (matching the route's existing error style).
- `mechanic` param maps to `captain_type` (`"tera"`/`"zmove"`), unchanged.
- **Admin roster route** (`/admin/roster`, app.py:2880/2898): **no gate** — admin
  override preserved, matching today's admin-can-do-anything behavior.
- **Pick-cost path untouched.** `tax.type` stays `"none"`; no surcharge computed
  anywhere. `draft_live_pick`, uber routing, `_auto_slot`, budgets — all unchanged.

## 5. Intentional behavior change (approved)

The current client JS enforces a **combined tera+zmove ≤18** cross-mechanic point cap.
Per the design decision, this combined cap is **dropped**. Only per-mechanic `max_pts`
caps are enforced going forward. Consequence: two 13-pt captains (26 total) is now
allowed. This is the sole intentional behavior change in B5; everything else is
preserved.

## 6. UI (settings page)

The `/admin/settings` "Battle Mechanics" section is rebuilt as **one card per mechanic**
(Mega, Tera, Z-Move, Dynamax). Uber keeps its existing separate section.

Each card:
- **Enable** toggle → `enabled` (dual-writes the legacy `mechanic_<name>` key).
- **"Captain mechanic"** toggle → `is_captain_mechanic`; when on, reveals:
  - **Captain count** (number) → `captain_count`.
  - **Max points** (number, 0 = no cap) → `max_pts`.
  - **Tier restriction** (checkbox list of tier names from the B3 tier definitions) →
    `restrict_tiers`.
- **Tax** (type dropdown none/flat/multiplier + value) — **rendered but disabled/greyed**
  with a "coming in B6" note. Persisted as `{"type":"none","value":0}` regardless in B5.

Removed from the page:
- the free-text **`mechanic` label** field (never read anywhere), and
- the inert **`mechanic_tax`** number input (dead).

The "At a Glance" read-only panel updates to reflect config-driven captain values
instead of hardcoded text.

**Persistence:** `admin_settings` POST assembles `mechanic_config` from the per-card
fields (same pattern as B3's `tier_definitions` assembly — skip the raw `mech_*` field
names in the generic loop; build + write the JSON; then dual-write the legacy keys).
The four legacy `mechanic_mega/tera/zmove/uber` keys are written from the assembled
config's `enabled` flags (not from raw form checkboxes); the rest of the existing
force-zero loop — notably `first_pick_regular` — is unchanged. (`mechanic_uber`'s
`enabled` continues to come from the Uber section's own checkbox, preserving its
current handling.)

## 7. Testing

Equivalence + enforcement tests are the spine (pytest harness from Phase 1A):

1. **Migration reproduces defaults.** Absent `mechanic_config` → `get_mechanic_config`
   yields the default blocks; `enabled` flags match the legacy keys; captain defaults =
   Tier 4/5, ≤13, count 1.
2. **Dual-write.** Saving config with `tera.enabled=true, mega.enabled=false` writes
   `mechanic_tera='1'`, `mechanic_mega='0'` (legacy strings) alongside the JSON.
3. **Eligibility helper.** Accepts a Tier-4 ≤13pt Pokémon; rejects over-cap,
   wrong-tier, over-count, and disabled-mechanic designations (one assertion each).
4. **Route enforcement (mutation-style).** POST to `/draft/live/set_captain` with an
   illegal designation (e.g. a Tier-1 mon as tera captain) is rejected — the flag is
   NOT set — proving the server now blocks what previously slipped through. Mirrors the
   B4 write-path test; mutation-verified (removing the helper call makes it fail).
5. **Un-designation always allowed.** POST `value='0'` succeeds regardless of config.
6. **Settings page in lockstep.** `test_settings_page.py` updated: `mechanic`/
   `mechanic_tax` removed from `EDITABLE_FIELDS`; new "Battle Mechanics & Captains"
   heading asserted; `mechanic_config` persistence asserted; legacy dual-written keys
   asserted.

Full suite must stay green (73 currently) plus the new B5 tests.

## 8. Slicing (subagent-driven execution)

Ordered sub-tasks on a `feat/mechanic-config-b5` branch, each implemented → reviewed →
conditionally fixed, then a whole-branch Opus review before merge (same pattern as
B1–B4):

- **T1** — `get_mechanic_config()` accessor + migration/defaults (deep-copied lists) +
  unit tests (migration reproduces defaults).
- **T2** — dual-write in `admin_settings` POST: assemble `mechanic_config`, write legacy
  keys from it; remove `mechanic`/`mechanic_tax` handling + tests.
- **T3** — settings UI: per-mechanic cards + tax(disabled) + tier-restriction checkboxes;
  update "At a Glance" + `test_settings_page.py`.
- **T4** — `_captain_eligibility_error()` helper + unit tests (accept/reject matrix).
- **T5** — wire the helper into `/draft/live/set_captain` (value=='1' only) + route
  enforcement test + un-designation test.
- **T6** — test sweep / equivalence pass: confirm current season unchanged (default
  config, all legacy keys still emitted, existing captains valid); build marker bump.

## 9. Out of scope (explicitly deferred)

- **Tax surcharge math** (flat/multiplier applied at pick time) → **B6**. B5 stores the
  tax schema only, always `type:"none"`.
- **Standings scoring + transaction rules** → B6.
- **Uber-slot count configurability**, add/remove/rename tiers, per-season settings,
  multiple coaches per team → Phase 2.
- **Mega/Dynamax as captain mechanics** (they carry the schema but default
  `is_captain_mechanic=false`; no designation UI/columns added in B5).
- The two divergent seed paths (init_db.py vs import_excel.py) are noted but **not
  reconciled** here — B5 relies on `get_mechanic_config`'s migration, which is
  independent of which seed path initialized the DB.
