# tests/test_settings_page.py
"""B1: the settings page must keep every existing key editable and persist it.
Guards the section reorg against silently dropping a field."""
import json as _json

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
        "fa_limit": "3",
        "num_players": "18", "num_pools": "2", "current_week": "5",
        "format": "Gen 9 NatDex", "match_format": "BO3",
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


def test_tier_field_rows_not_stored_raw(client, app_mod):
    # The per-tier form fields are assembled into tier_definitions, not persisted raw.
    client.post("/admin/settings", data={
        "league_name": "X", "tier_cols_1": "16,17", "tier_alloc_1": "2",
    })
    with app_mod.get_db() as db:
        keys = {r["key"] for r in db.execute("SELECT key FROM league_settings")}
    assert "tier_cols_1" not in keys and "tier_alloc_1" not in keys
    assert "tier_definitions" in keys


def test_has_draft_mode_policy(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "Draft Mode Policy" in html
    assert 'name="draft_mode_policy"' in html


def test_draft_mode_policy_persists(client, app_mod):
    client.post("/admin/settings", data={"league_name": "X", "draft_mode_policy": "only_points"})
    with app_mod.get_db() as db:
        got = db.execute("SELECT value FROM league_settings WHERE key='draft_mode_policy'").fetchone()["value"]
    assert got == "only_points"
