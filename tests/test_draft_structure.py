"""B2: configurable roster size / first-pick / draft-order, defaults reproduce today."""


def test_defaults_reproduce_current_behavior(app_mod):
    with app_mod.get_db() as db:
        assert app_mod.get_roster_size(db) == 10
        assert app_mod.get_first_pick_regular(db) is True
    assert app_mod.get_draft_order_method() == "snake"


def test_accessors_read_stored_values(app_mod):
    with app_mod.get_db() as db:
        for k, v in [("roster_size", "12"), ("first_pick_regular", "0"),
                     ("draft_order_method", "linear")]:
            db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)", (k, v))
    with app_mod.get_db() as db:
        assert app_mod.get_roster_size(db) == 12
        assert app_mod.get_first_pick_regular(db) is False
    assert app_mod.get_draft_order_method() == "linear"


def test_roster_size_bad_value_falls_back_to_10(app_mod):
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('roster_size', 'oops')")
        assert app_mod.get_roster_size(db) == 10
