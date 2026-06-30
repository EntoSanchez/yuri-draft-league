# tests/test_board_templates.py
def test_board_templates_table_exists(app_mod):
    with app_mod.get_db() as db:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(draft_board_templates)")}
    assert {"id", "name", "kind", "notes", "board_json", "created_at", "updated_at"} <= cols


def _seed_board(db):
    db.execute("DELETE FROM draft_tiers")
    db.execute("INSERT INTO draft_tiers (name, points, tier_label, is_mega) VALUES (?,?,?,?)",
               ("Garchomp", 18, "Tier 1", 0))
    db.execute("INSERT INTO draft_tiers (name, points, is_mega) VALUES (?,?,?)",
               ("Mega Garchomp", 24, 1))


def test_save_then_load_roundtrips_board(app_mod):
    with app_mod.get_db() as db:
        _seed_board(db)
        tid = app_mod.save_board_template(db, "Base S8")
        db.execute("DELETE FROM draft_tiers")           # wipe live board
        n = app_mod.load_board_template(db, tid)
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert n == 2 and names == {"Garchomp", "Mega Garchomp"}


def test_load_missing_template_raises(app_mod):
    import pytest
    with app_mod.get_db() as db:
        with pytest.raises(ValueError):
            app_mod.load_board_template(db, 99999)


def test_load_skips_unknown_columns(app_mod):
    import json as _j
    with app_mod.get_db() as db:
        ts = app_mod._now_iso()
        board = _j.dumps([{"name": "X", "points": 5, "bogus_col": "zzz"}])
        cur = db.execute(
            "INSERT INTO draft_board_templates (name, kind, notes, board_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            ("Has bogus col", "manual", "", board, ts, ts))
        tid = cur.lastrowid
        db.execute("DELETE FROM draft_tiers")
        n = app_mod.load_board_template(db, tid)   # must NOT raise on unknown key
        row = db.execute(
            "SELECT name, points FROM draft_tiers WHERE name='X'").fetchone()
    assert n == 1
    assert row is not None and row["name"] == "X" and row["points"] == 5


def test_prune_keeps_only_recent_autobackups(app_mod):
    with app_mod.get_db() as db:
        _seed_board(db)
        for _ in range(13):
            app_mod.save_board_template(db, "auto", kind="autobackup")
        app_mod.prune_autobackups(db, keep=10)
        cnt = db.execute(
            "SELECT COUNT(*) FROM draft_board_templates WHERE kind='autobackup'").fetchone()[0]
    assert cnt == 10
