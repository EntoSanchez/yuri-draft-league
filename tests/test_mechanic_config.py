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
