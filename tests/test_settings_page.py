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
