# Settings Rework + Draft Board Templates — Design

- **Date:** 2026-06-30
- **Status:** Approved direction; revised after scope additions; pending written-spec re-review
- **Project:** Yuri Draft League (Flask/SQLite, PythonAnywhere)

## 1. Problem

1. **Reusable draft board.** The draft pool lives in one global `draft_tiers`
   table. There's no way to save it as a named base, reuse it, or edit a saved
   copy. The only adjacent feature is the read-only season archive.

2. **Cohesive, configurable settings.** League config is "mashed together" in a
   global key/value `league_settings` table feeding a loosely-grouped page. Many
   real season mechanics are **hardcoded** (regular tier thresholds 16/13/9/5,
   ticket allocation T1:1…T5:2, uber points 27–30, 10-pick cap, 2 uber slots,
   first-pick rule) or **have no UI** (`mega_*_pts`; `draft_round_structure`).
   `uber_combination` is editable but unenforced. Captains are display-only.
   There is no per-season scoping, so settings go stale across seasons. The admin
   wants the draft and battle mechanics themselves to be configurable.

3. **Teams vs. coaches.** The `coaches` table conflates a coach and a team in one
   row, so a team cannot have multiple coaches.

## 2. Goals / Non-goals

**Goals**
- Save / reuse / edit the draft board as named templates, with safe loading and
  automatic restore points.
- One cohesive settings page that surfaces **and makes configurable** the
  season-specific mechanics:
  - **Draft mode policy:** only-points / only-tickets / combination; with
    configurable **points budget**, **picks-per-tier (ticket allocation)**, and
    **number of tiers**.
  - **Tier definitions:** explicitly assign which point columns belong to which
    tier (non-contiguous allowed); add/remove tiers.
  - **Battle mechanics:** Mega / Tera / Z-Move / **Dynamax** (new), any combination,
    each with a **usage mode** — off / anyone / captains / specific tiers / **tax** —
    and a **league-level tax** (flat or multiplier) where applicable.
  - **Uber picks** on/off + combination.
  - **Draft structure:** roster size (max picks/team), uber picks per team,
    first-pick-must-be-regular toggle, draft order (snake / linear) + a randomize helper.
  - **Transactions:** trade rules (allow on/off + deadline week), free-agency rules
    (pickup limit, open/lock weeks, waiver order).
  - **Standings scoring:** point values for win/loss/tie + tiebreaker order.
  - Friendly **round-structure** editor.
- Manual **DB backup/restore** safety net.
- A vetted, safeguarded *design* for **per-season settings** and **multiple coaches
  per team**, both built later.

**Behavior-preservation principle.** Every newly-configurable mechanic ships with a
**default that reproduces this season's current behavior exactly**. The draft logic
is refactored to *read settings* instead of hardcoded constants, but with absent/
default values the computed results are byte-for-byte identical. Enforcement that
doesn't exist today (captain restrictions, tax surcharges, `uber_combination`)
defaults to **off / non-enforcing** and is strictly opt-in.

**Non-goals (this pass)**
- **Uber point values (27–30 → Bronze/Silver/Gold/Platinum) stay fixed.** Documented,
  not yet editable. (Roster size, uber-picks-per-team, and the first-pick rule are now
  *in scope* as settings — see Goals.)
- **Tax is league-level** (one number per mechanic), **not** per-Pokémon double
  pricing.
- **No live-draft pick clock** this pass.
- **Multiple coaches per team** is deferred to Phase 2 (data-model change).
- **Per-season settings scoping** is deferred to Phase 2.

## 3. Phasing

- **Phase 1A** — Draft Board Templates + restore points (build now)
- **Phase 1B** — Cohesive, configuration-driven settings page (build now; defaults
  reproduce current behavior; equivalence-tested)
- **Phase 1C** — Manual DB backup/restore (build now)
- **Phase 2** — Per-season settings scoping **and** multiple coaches per team
  (design now, build later, heavily safeguarded)

Each phase is independently shippable and reversible.

---

## 4. Phase 1A — Draft Board Templates

### 4.1 Data model
Additive migration in `_migrate_db`:

```sql
CREATE TABLE IF NOT EXISTS draft_board_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'manual',   -- 'manual' | 'autobackup'
    notes       TEXT DEFAULT '',
    board_json  TEXT NOT NULL,                    -- JSON array of full draft_tiers rows
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

`board_json` captures every `draft_tiers` column (schema-flexible JSON blob).

### 4.2 Editing model ("Both")
Library page `/admin/board-templates`:
- **Save current board** → snapshot live `draft_tiers` to a new `manual` template.
- Per-template: **Load to live**, **Edit in place**, **Duplicate**, **Rename**,
  **Delete**, **Download JSON**.
- **Edit in place** loads `board_json` into the existing tiers-editing UI; the page
  edits the in-memory blob and POSTs the whole updated board back to the template,
  **without touching the live board** (whole-blob save; board edits are infrequent).

### 4.3 Load safety
"Load to live" replaces all of `draft_tiers` in one transaction:
1. **Block** if any `draft_sessions.status = 'active'`.
2. If any `pokemon_roster` rows exist, require an explicit second confirm.
3. **Always** snapshot the current board to an `autobackup` template first.
4. `DELETE` + bulk-insert from the template, transactional (rolls back on error).

### 4.4 Restore points
`autobackup` templates are created before every destructive board op, shown in a
"Restore points" group, auto-pruned to the most recent 10.

### 4.5 Routes
`GET/POST /admin/board-templates`; `GET/POST /admin/board-templates/<id>/edit`;
`GET /admin/board-templates/<id>/download`. POST actions: `save_current`, `load`,
`duplicate`, `rename`, `delete`, `restore`.

---

## 5. Phase 1B — Cohesive, configuration-driven settings

Rebuild `templates/admin/settings.html` into titled cards. **No existing setting
keys are renamed**; new config is stored under new keys (mostly JSON), each with a
default that reproduces current behavior.

### 5.1 Sections
1. **League Identity** — `league_name`, `season`, `format`, `mechanic` label, `num_pools`, `num_players`
2. **Schedule & Matches** — `current_week` (existing set-week route), `match_format`, `fa_limit`, `discord_webhook_url`
3. **Battle Mechanics & Captains** — see §5.3
4. **Draft Mode** — see §5.4
5. **Tier Definitions** — see §5.5
6. **Draft Structure** — see §5.6
7. **Uber Picks** — `mechanic_uber` toggle + `uber_combination` (surfaced; enforcement opt-in, default off → unchanged)
8. **Draft Round Structure** — friendly editor for `draft_round_structure` (reorderable rows of name / tier_filter / picks_per_coach; `tier_filter` dropdown of `uber`, the configured tier names, and `any`; serializes to the exact JSON the draft logic reads; `DEFAULT_ROUND_STRUCTURE` fallback if unset)
9. **Transactions** — see §5.7
10. **Standings & Scoring** — see §5.8
11. **Playoffs** — surface `playoff_*` read-only with a link to `/admin/playoffs` (route stays authoritative)

### 5.2 "Still fixed this season" panel
Read-only documentation of what remains hardcoded after this pass: **uber point
values 27–30 → Bronze/Silver/Gold/Platinum**, and the Uber 1 / Uber 2 slot-assignment
order. (Roster size, uber-picks-per-team, and the first-pick rule are now editable —
see §5.6.) Labeled "configurable in a later phase."

### 5.3 Battle Mechanics & Captains
New setting `mechanic_config` (JSON), one block per mechanic:

```json
{
  "mega":    {"enabled": true,  "usage": "anyone", "captain_count": 1,
              "captain_budget": 0, "allowed_tiers": [], "tax_type": "flat", "tax_value": 0},
  "tera":    {"enabled": true,  "usage": "anyone", ...},
  "zmove":   {"enabled": false, "usage": "anyone", ...},
  "dynamax": {"enabled": false, "usage": "off",    ...}
}
```

- `usage` ∈ `off | anyone | captains | specific_tiers | tax`.
- **captains:** designate up to `captain_count` Pokémon (optional `captain_budget`
  side-pool); only captains may use the mechanic. Uses the existing
  `is_tera_captain` / `is_zmove_captain` flags (plus new `is_mega_captain` /
  `is_dynamax_captain` columns as needed).
- **specific_tiers:** only Pokémon whose tier ∈ `allowed_tiers` may use it.
- **tax:** any Pokémon may use it but pays a surcharge — `tax_type` flat (`+tax_value`
  points) or multiplier (`points × tax_value`), applied at pick/designation time.
  Tax targets points-based drafting; for ticket coaches, prefer captains/tiers/anyone.
- **Migration / default:** derive `enabled` from existing `mechanic_mega/tera/zmove`;
  add `dynamax` default off; set every `usage` to **`anyone`** and taxes to **0** so
  nothing is newly enforced → **current season unchanged.** Enforcement is opt-in.
- The legacy `mechanic_tax` key is preserved; the new per-mechanic taxes supersede it
  going forward (legacy value migrated into the relevant mechanic's `tax_value` if set).

### 5.4 Draft Mode
- `draft_mode_policy` ∈ `combination` (default) | `only_points` | `only_tickets`.
  - **combination:** per-coach `coaches.draft_mode` decides (today's behavior).
  - **only_points / only_tickets:** force all coaches to that mode (overrides the
    per-coach column at read time; the column is untouched).
- `points_budget_griffin` (existing) — points budget when points-drafting.
- **Ticket allocation** lives inside Tier Definitions (§5.5), since picks-per-tier is
  per-tier. Default reproduces `TICKET_ALLOC` (T1:1, T2:1, T3:2, T4:2, T5:2).

### 5.5 Tier Definitions (explicit point-column assignment)
New setting `tier_definitions` (JSON), an ordered list:

```json
[
  {"name": "Tier 1", "columns": [26,25,...,16], "ticket_alloc": 1},
  {"name": "Tier 2", "columns": [15,14,13],     "ticket_alloc": 1},
  {"name": "Tier 3", "columns": [12,11,10,9],   "ticket_alloc": 2},
  {"name": "Tier 4", "columns": [8,7,6,5],       "ticket_alloc": 2},
  {"name": "Tier 5", "columns": [4,3,2,1,0],     "ticket_alloc": 2}
]
```

- Editor: a grid of the **distinct point values present on the board**, each assigned
  to a tier (drag or dropdown); add/remove tiers; set each tier's `ticket_alloc`.
  Non-contiguous columns allowed.
- **Precedence:** the uber system (points 27–30, or `tier_label`/mega-uber) takes
  precedence; `tier_definitions` covers the remaining (non-uber) columns. A point
  value not listed falls through to the lowest tier (documented).
- **Refactor:** `_regular_tier_label(pts)` and `TICKET_ALLOC`/`TIER_TO_TICKET`/
  `TICKET_RANK` become functions of `tier_definitions`. **Default `tier_definitions`
  reproduces 16/13/9/5 thresholds and the current ticket allocation exactly** →
  identical results when unset.

### 5.6 Draft Structure
New keys, each defaulting to current behavior:
- `roster_size` (int, default **10**) — replaces the hardcoded 10-pick cap in
  `draft_live_pick` and the chain-makeup "room" check.
- `uber_picks_per_team` (int, default **2**) — replaces the hardcoded 2-uber-slot
  limit and the Uber 1 / Uber 2 assignment count.
- `first_pick_regular` (bool, default **on**) — toggles the "first overall pick must
  be a regular-tier Pokémon (not Mega / 0-pt)" rule.
- `draft_order_method` (`snake` default | `linear`) — `snake` reverses each pass as
  today; `linear` keeps the same order every round. Plus a **"randomize order"** admin
  helper that fills `draft_sessions.snake_order` with a server-side `random.shuffle`
  of the coach IDs.

### 5.7 Transactions
New key `transaction_rules` (JSON), defaulting to current behavior:
```json
{"trades_enabled": true, "trade_deadline_week": null,
 "fa_limit": 3, "fa_open_week": null, "fa_lock_week": null, "waiver_order": "none"}
```
- `fa_limit` migrates the existing top-level key in. Trades default enabled with no
  deadline; FA open/lock unset; waiver `none` → **transactions behave exactly as today**.
- Read by the trade/free-agency routes; with defaults, no new restriction applies.

### 5.8 Standings & Scoring
New key `standings_scoring` (JSON), defaulting to current behavior:
```json
{"win": 1, "loss": 0, "tie": 0, "tiebreakers": ["diff"]}
```
- `get_standings` ranks by total points (= Σ win/loss/tie values) then the tiebreaker
  list. **Default win:1/loss:0/tie:0 + tiebreak `diff`** reproduces today's "rank by
  wins, break ties by differential" exactly. Tiebreaker options: `diff`,
  `head_to_head`, `kills`.

### 5.9 Backward-compatibility & POST handler
- Reorganized `admin_settings` POST writes the same legacy keys plus the new JSON/
  scalar keys (`mechanic_config`, `draft_mode_policy`, `tier_definitions`,
  `roster_size`, `uber_picks_per_team`, `first_pick_regular`, `draft_order_method`,
  `transaction_rules`, `standings_scoring`). Unknown/absent keys fall back to
  behavior-preserving defaults in code.
- `mega_*_pts` get real number inputs (previously invisible).

---

## 6. Phase 1C — Manual DB backup/restore

- `GET/POST /admin/backups` (`create`, `restore`, `delete`); `GET /admin/backups/<name>/download`.
- Back up / restore **whatever DB the app uses (`DB_PATH`)** — handles the nested-prod-
  DB trap. Backups live in a git-ignored `backups/` dir next to that DB. Restore
  creates a fresh pre-restore backup, writes to a temp file, then atomically swaps.
  Never commit `*.db`.

---

## 7. Phase 2 — Per-season settings + multiple coaches per team (design only)

Built **only after Phase 1 ships and is validated in prod**, with the full safeguard
suite.

### 7.1 Per-season settings
- `season_settings(season_id, key, value)` (or per-season `settings_json`).
  `league_settings` remains the active season's working set; a resolver
  (`get_setting`) reads the active season's scope. Migration copies current globals
  in so resolved values are identical day one.
- **Read-path first, then write-path:** ship the resolver returning identical values,
  verify, then switch writes to per-season.

### 7.2 Multiple coaches per team
- Introduce a `teams` table; `coaches` reference a `team_id` (N coaches → 1 team).
  Migration creates one team per existing coach row and links it (1:1), so current
  data and every page behave identically at first.
- Then incrementally update standings, schedule, rosters, draft attribution, team
  pages, and matchups to be team-centric where appropriate. The exact attribution
  model (does a team draft once or per-coach? standings per team or per coach?) is
  finalized during Phase 2 design.

### 7.3 Safeguards (the "reviews / debugging / save states" requirement)
- Full **DB file backup** (Phase 1C) before any migration; one-click restore.
- **Save states / restore points** for settings and board.
- **Dry-run diff** before applying any season-affecting change.
- **Adversarial-review workflow** over each migration and every read site touched.
- **Equivalence tests** on a scratch DB copy: resolved settings == current globals
  byte-for-byte; draft/standings/derived outputs unchanged; one-team-per-coach
  mapping leaves every page identical before any team-centric change.

---

## 8. Testing & rollback

All tests run on a **scratch copy** of `league.db`, never the live DB.

- **Phase 1B equivalence (critical):** with no new settings stored, assert the
  refactored draft logic produces identical output to today for a battery of cases —
  `_regular_tier_label` for every point value 0–30; ticket allocation/rank per tier;
  mechanic gating (all `usage="anyone"`, tax 0 → no surcharge, no restriction);
  `draft_mode_policy="combination"` == per-coach behavior; `roster_size`=10,
  `uber_picks_per_team`=2, `first_pick_regular`=on reproduce the hardcoded caps/rule;
  `standings_scoring` default reproduces today's wins-then-diff ranking on real
  schedule data; `transaction_rules` defaults impose no new restriction. Then assert
  that *changing* a setting changes results as intended (thresholds, tax, captains,
  tiers, roster cap, scoring, trade deadline).
- **Settings round-trip:** load page, POST unchanged → every legacy key byte-for-byte
  identical; new JSON keys parse and re-serialize stably.
- **Board templates:** save → load → save preserves all rows/columns; load-safety
  guards fire (active session blocks; rosters warn; autobackup created).
- **Backups:** create → restore round-trip restores identical data.
- Every destructive action backs up first.
- **Deploy:** bump `base.html` build marker; PythonAnywhere `git reset --hard`, clear
  `__pycache__`, **Reload via Web tab**; smoke-test; confirm marker in console.

## 9. File-level change list (Phase 1)

- `app.py` — migrations (`draft_board_templates`; new captain columns if needed);
  routes for board-templates and backups; reorganized `admin_settings`;
  refactor `_regular_tier_label` / ticket constants / mechanic gating / roster-cap /
  uber-slot count / first-pick rule / `get_standings` ranking / trade & FA routes to
  read `tier_definitions`, `draft_mode_policy`, `mechanic_config`, `roster_size`,
  `uber_picks_per_team`, `first_pick_regular`, `draft_order_method`,
  `transaction_rules`, `standings_scoring` — all with behavior-preserving defaults;
  helper accessors for the new settings; a "randomize draft order" admin action.
- `templates/admin/settings.html` — full sectioned rebuild incl. mechanics+captains,
  draft-mode, tier-definitions grid, round-structure editor, mega thresholds, fixed-
  rules panel.
- `templates/admin/board_templates.html` — NEW (library + editor).
- `templates/admin/backups.html` — NEW.
- `templates/admin/index.html` / nav — links to new pages.
- `.gitignore` — ensure `backups/` and `*.db` ignored.
- `templates/base.html` — build marker.

## 10. Open questions

None blocking. Phase 2 specifics (per-season storage shape; team attribution model)
are finalized during Phase 2 design, after Phase 1 lands and is validated.
