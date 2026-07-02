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
