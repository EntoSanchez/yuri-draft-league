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


import json as _json


def _count_roster(app_mod):
    with app_mod.get_db() as db:
        return db.execute("SELECT COUNT(*) FROM pokemon_roster").fetchone()[0]


def _setup_single_coach_draft(app_mod, mons):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM draft_tiers")
        db.execute("DELETE FROM pokemon_roster"); db.execute("DELETE FROM draft_sessions")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (1,'C','T','A')")
        for name, pts in mons:
            db.execute("INSERT INTO draft_tiers (name, points) VALUES (?,?)", (name, pts))
        db.execute("INSERT INTO draft_sessions (name, status, snake_order, current_pick_a) "
                   "VALUES ('S','active',?,1)", (_json.dumps([1]),))
        db.execute("""CREATE TABLE IF NOT EXISTS draft_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            pick_number INTEGER NOT NULL,
            round_number INTEGER NOT NULL,
            slot_name TEXT DEFAULT '',
            coach_id INTEGER NOT NULL,
            pokemon_name TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            picked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ticket_used TEXT
        )""")


def test_roster_cap_uses_setting(client, app_mod):
    _setup_single_coach_draft(app_mod, [("Garchomp", 18)])
    with app_mod.get_db() as db:
        db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name, points) VALUES (1,'A',1),(1,'B',1)")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('roster_size','2')")
    before = _count_roster(app_mod)
    client.post("/draft/live/pick", data={"pokemon_name": "Garchomp", "pick_pool": "A"})
    assert _count_roster(app_mod) == before  # cap hit at 2 -> pick rejected


def test_first_pick_rule_on_blocks_zero_point(client, app_mod):
    _setup_single_coach_draft(app_mod, [("ZeroMon", 0)])   # first_pick_regular defaults ON
    client.post("/draft/live/pick", data={"pokemon_name": "ZeroMon", "pick_pool": "A"})
    assert _count_roster(app_mod) == 0  # 0-pt first pick blocked by the (default-on) rule


def test_first_pick_rule_off_allows_zero_point(client, app_mod):
    _setup_single_coach_draft(app_mod, [("ZeroMon", 0)])
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('first_pick_regular','0')")
    client.post("/draft/live/pick", data={"pokemon_name": "ZeroMon", "pick_pool": "A"})
    assert _count_roster(app_mod) == 1  # rule OFF -> 0-pt first pick allowed
