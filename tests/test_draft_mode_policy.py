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


def test_effective_mode_default_unchanged(app_mod):
    coach = {"draft_mode": "tier_tickets"}
    assert app_mod._effective_draft_mode(coach, "griffin") == "tier_tickets"   # default policy
    assert app_mod._effective_draft_mode({"draft_mode": None}, "griffin") == "tier_tickets"
    assert app_mod._effective_draft_mode({"draft_mode": "points"}, "") == "legacy"  # non-griffin


def test_effective_mode_forced_by_policy(app_mod):
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('draft_mode_policy','only_points')")
    assert app_mod._effective_draft_mode({"draft_mode": "tier_tickets"}, "griffin") == "points"
    assert app_mod._effective_draft_mode({"draft_mode": "tier_tickets"}, "") == "legacy"  # legacy fmt untouched


def test_coach_draft_state_respects_policy(app_mod):
    # Under only_points + griffin, a tier_tickets coach's state is the POINTS branch (has 'remaining').
    with app_mod.get_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS draft_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            pick_number INTEGER NOT NULL DEFAULT 1,
            round_number INTEGER NOT NULL DEFAULT 1,
            slot_name TEXT DEFAULT '',
            coach_id INTEGER NOT NULL,
            pokemon_name TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            picked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ticket_used TEXT
        )""")
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM draft_sessions")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool, draft_mode) VALUES (1,'C','T','A','tier_tickets')")
        db.execute("INSERT INTO draft_sessions (id, name, status) VALUES (1,'S','active')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('draft_format','griffin')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('draft_mode_policy','only_points')")
    # Call in a separate connection so get_setting sees the committed values.
    with app_mod.get_db() as db:
        st = app_mod._get_coach_draft_state(db, 1, 1)
    assert st["mode"] == "points" and "remaining" in st and "remaining_tickets" not in st


def test_draft_live_pick_write_path_forced_to_points(client, app_mod):
    """The draft_live_pick validation branch honors the policy override.

    A tier_tickets coach under only_points+griffin picking a 20pt mon against a
    5pt budget is REJECTED by the points-budget branch. Without the override the
    same pick lands in the ticket branch (a T1 ticket is available) and would be
    ACCEPTED — so the roster count discriminates the two paths.
    """
    import json as _json

    with app_mod.get_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS draft_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            pick_number INTEGER NOT NULL DEFAULT 1,
            round_number INTEGER NOT NULL DEFAULT 1,
            slot_name TEXT DEFAULT '',
            coach_id INTEGER NOT NULL,
            pokemon_name TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            picked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ticket_used TEXT
        )""")
        db.execute("DELETE FROM coaches"); db.execute("DELETE FROM draft_sessions")
        db.execute("DELETE FROM draft_tiers"); db.execute("DELETE FROM pokemon_roster")
        db.execute("DELETE FROM draft_picks")
        db.execute("INSERT INTO coaches (id, coach_name, team_name, pool, draft_mode) VALUES (1,'C','T','A','tier_tickets')")
        # A single Tier-1 round so pick #1 is a normal (non-uber) pick on coach 1.
        db.execute(
            "INSERT INTO draft_sessions (id, name, status, snake_order, current_pick_a) VALUES (1,'S','active',?,1)",
            (_json.dumps([1]),),
        )
        # A 20pt regular mon -> Tier 1 (>=16); not an uber (< 27).
        db.execute("INSERT INTO draft_tiers (name, points, tier_label) VALUES ('Bigmon', 20, '')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('draft_format','griffin')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('draft_mode_policy','only_points')")
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) VALUES ('points_budget_griffin','5')")
        db.execute(
            "INSERT OR REPLACE INTO league_settings (key,value) VALUES ('draft_round_structure',?)",
            (_json.dumps([{"name": "Tier 1", "tier_filter": "Tier 1", "picks_per_coach": 2}]),),
        )

    client.post(
        "/draft/live/pick",
        data={"pokemon_name": "Bigmon", "pick_pool": "A"},
        headers={"X-CSRFToken": "testtoken"},
    )

    with app_mod.get_db() as db:
        cnt = db.execute("SELECT COUNT(*) FROM pokemon_roster").fetchone()[0]
    # Rejected by the points-budget branch => nothing drafted. (Ticket branch would accept.)
    assert cnt == 0
