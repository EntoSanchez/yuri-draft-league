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


def test_snake_sequence_default_matches_current(app_mod):
    # default (no setting) resolves to snake -> reproduces existing reversal behavior.
    seq = app_mod._get_snake_pick_sequence([1, 2, 3], [{"name": "R1", "picks_per_coach": 2}])
    coaches = [c for (_pn, _ri, _sn, c) in seq]
    assert coaches == [1, 2, 3, 3, 2, 1]  # pass0 forward, pass1 reversed


def test_linear_sequence_no_reversal(app_mod):
    seq = app_mod._get_snake_pick_sequence([1, 2, 3], [{"name": "R1", "picks_per_coach": 2}], "linear")
    coaches = [c for (_pn, _ri, _sn, c) in seq]
    assert coaches == [1, 2, 3, 1, 2, 3]  # every pass forward


def test_sequence_resolves_setting_when_method_none(app_mod):
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('draft_order_method', 'linear')")
    seq = app_mod._get_pool_sequence([1, 2, 3, 4], {1, 3}, [{"name": "R1", "picks_per_coach": 2}])
    coaches = [c for (_pn, _ri, _sn, c) in seq]
    assert coaches == [1, 3, 1, 3]  # linear resolved from the setting, no reversal
