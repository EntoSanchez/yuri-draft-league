def _seed(app_mod):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Garchomp', 18)")


def test_save_current_creates_template(client, app_mod):
    _seed(app_mod)
    resp = client.post("/admin/board-templates",
                       data={"action": "save_current", "name": "Base S8"},
                       follow_redirects=True)
    assert resp.status_code == 200
    with app_mod.get_db() as db:
        n = db.execute("SELECT COUNT(*) FROM draft_board_templates WHERE name='Base S8'").fetchone()[0]
    assert n == 1


def test_rename_and_delete(client, app_mod):
    _seed(app_mod)
    with app_mod.get_db() as db:
        tid = app_mod.save_board_template(db, "Old Name")
    resp = client.post("/admin/board-templates",
                       data={"action": "rename", "template_id": tid, "name": "New Name"})
    assert resp.status_code in (200, 302), f"rename returned {resp.status_code}"
    with app_mod.get_db() as db:
        row = db.execute(
            "SELECT name FROM draft_board_templates WHERE id=?", (tid,)
        ).fetchone()
    assert row is not None and row["name"] == "New Name", (
        f"expected name='New Name' after rename, got {row}"
    )
    client.post("/admin/board-templates",
                data={"action": "delete", "template_id": tid})
    with app_mod.get_db() as db:
        cnt = db.execute("SELECT COUNT(*) FROM draft_board_templates WHERE id=?", (tid,)).fetchone()[0]
    assert cnt == 0


def test_duplicate_creates_copy(client, app_mod):
    _seed(app_mod)
    with app_mod.get_db() as db:
        tid = app_mod.save_board_template(db, "Original")
    client.post("/admin/board-templates",
                data={"action": "duplicate", "template_id": tid},
                follow_redirects=True)
    with app_mod.get_db() as db:
        copies = db.execute(
            "SELECT COUNT(*) FROM draft_board_templates WHERE name LIKE '% (copy)'"
        ).fetchone()[0]
    assert copies == 1


def test_list_page_renders(client, app_mod):
    _seed(app_mod)
    with app_mod.get_db() as db:
        app_mod.save_board_template(db, "Visible Template")
    resp = client.get("/admin/board-templates")
    assert resp.status_code == 200 and b"Visible Template" in resp.data


# ─── Task 4: Load-to-live route tests ─────────────────────────────────────────

def _template_with(app_mod, name, mon):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES (?, 10)", (mon,))
        return app_mod.save_board_template(db, name)


def test_load_replaces_board_and_makes_autobackup(client, app_mod):
    tid = _template_with(app_mod, "Template A", "Dragapult")
    with app_mod.get_db() as db:                       # make live board different
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Skeledirge', 12)")
    client.post("/admin/board-templates/load",
                data={"template_id": tid, "confirm": "yes"}, follow_redirects=True)
    with app_mod.get_db() as db:
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
        autos = db.execute(
            "SELECT COUNT(*) FROM draft_board_templates WHERE kind='autobackup'").fetchone()[0]
    assert names == {"Dragapult"} and autos == 1       # board swapped + restore point made


def test_load_bogus_id_makes_no_autobackup(client, app_mod):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('LiveMon', 7)")
    client.post("/admin/board-templates/load",
                data={"template_id": 999999, "confirm": "yes"}, follow_redirects=True)
    with app_mod.get_db() as db:
        autos = db.execute(
            "SELECT COUNT(*) FROM draft_board_templates WHERE kind='autobackup'").fetchone()[0]
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert autos == 0                 # no orphan restore point created
    assert names == {"LiveMon"}       # live board unchanged


def test_load_blocked_during_active_session(client, app_mod):
    tid = _template_with(app_mod, "Template B", "Dragapult")
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Skeledirge', 12)")
        db.execute("INSERT INTO draft_sessions (name, status) VALUES ('S8', 'active')")
    client.post("/admin/board-templates/load",
                data={"template_id": tid, "confirm": "yes"})
    with app_mod.get_db() as db:
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert names == {"Skeledirge"}                     # unchanged — load refused


def test_load_requires_confirm_when_rosters_exist(client, app_mod):
    tid = _template_with(app_mod, "Template C", "Dragapult")
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Skeledirge', 12)")
        db.execute("INSERT INTO coaches (coach_name, team_name) VALUES ('C', 'T')")
        cid = db.execute("SELECT id FROM coaches LIMIT 1").fetchone()["id"]
        db.execute("INSERT INTO pokemon_roster (coach_id, pokemon_name) VALUES (?, 'Skeledirge')", (cid,))
    client.post("/admin/board-templates/load",
                data={"template_id": tid, "confirm": ""})   # no confirm
    with app_mod.get_db() as db:
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert names == {"Skeledirge"}                     # unchanged — needed confirm


def test_download_returns_json_board(client, app_mod):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Garchomp', 18)")
        tid = app_mod.save_board_template(db, "DL Test")
    resp = client.get(f"/admin/board-templates/{tid}/download")
    import json as _j
    assert resp.status_code == 200
    assert any(m["name"] == "Garchomp" for m in _j.loads(resp.data))
    assert resp.headers["Content-Type"] == "application/json"
    assert "attachment" in resp.headers["Content-Disposition"]


# ─── Task 6: Edit template in place ───────────────────────────────────────────

def test_edit_get_renders_rows(client, app_mod):
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Garchomp', 18)")
        tid = app_mod.save_board_template(db, "Edit Me")
    resp = client.get(f"/admin/board-templates/{tid}/edit")
    assert resp.status_code == 200 and b"Garchomp" in resp.data


def test_edit_post_saves_blob_without_touching_live(client, app_mod):
    import json as _j
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('LiveMon', 5)")
        tid = app_mod.save_board_template(db, "T")
    new_board = _j.dumps([{"name": "EditedMon", "points": 22}])
    client.post(f"/admin/board-templates/{tid}/edit",
                data={"name": "T", "notes": "", "board_json": new_board},
                follow_redirects=True)
    with app_mod.get_db() as db:
        tpl = _j.loads(db.execute(
            "SELECT board_json FROM draft_board_templates WHERE id=?", (tid,)).fetchone()["board_json"])
        live = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert tpl[0]["name"] == "EditedMon"   # template updated
    assert live == {"LiveMon"}             # live board untouched
