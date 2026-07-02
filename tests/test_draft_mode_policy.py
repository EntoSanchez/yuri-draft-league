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
