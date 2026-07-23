"""Tests for _display_current_week — the home/standings week tracker.

Regression: the old display used completed_weeks+1, where a week only counted
once EVERY match in it was scored. A single unplayed straggler in week 1 froze
the tracker at "WEEK 01 / 0%" all season even as later weeks were played.
"""


def _add_match(db, week, s1=None, s2=None):
    db.execute(
        "INSERT INTO schedule (week, coach1_id, coach2_id, score1, score2) VALUES (?,?,?,?,?)",
        (week, 1, 2, s1, s2),
    )


def test_no_schedule_returns_week_1(app_mod):
    with app_mod.get_db() as db:
        assert app_mod._display_current_week(db) == 1


def test_no_results_no_setting_returns_first_week(app_mod):
    with app_mod.get_db() as db:
        for w in (1, 2, 3):
            _add_match(db, w)
            _add_match(db, w)
        assert app_mod._display_current_week(db) == 1


def test_straggler_does_not_freeze_tracker(app_mod):
    # Week 1 has an unplayed straggler, but week 2 already has a result:
    # the tracker must show week 2 (old completed_weeks logic showed week 1).
    with app_mod.get_db() as db:
        _add_match(db, 1, 2, 0)
        _add_match(db, 1)          # straggler — never scored
        _add_match(db, 2, 2, 1)    # week 2 activity
        _add_match(db, 2)
        _add_match(db, 3)
        assert app_mod._display_current_week(db) == 2


def test_admin_setting_wins_over_activity(app_mod):
    with app_mod.get_db() as db:
        _add_match(db, 1, 2, 0)
        _add_match(db, 2)
        _add_match(db, 3)
        db.execute(
            "INSERT OR REPLACE INTO league_settings (key, value) VALUES ('current_week', '3')"
        )
        assert app_mod._display_current_week(db) == 3


def test_setting_clamped_to_schedule_range(app_mod):
    with app_mod.get_db() as db:
        _add_match(db, 1)
        _add_match(db, 2)
        db.execute(
            "INSERT OR REPLACE INTO league_settings (key, value) VALUES ('current_week', '99')"
        )
        assert app_mod._display_current_week(db) == 2


def test_home_and_standings_routes_render(client):
    # Regression: the helper was once inserted between @app.route("/") and
    # def index(), silently stealing the homepage route and 500ing "/".
    assert client.get("/").status_code == 200
    assert client.get("/standings").status_code == 200
