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


def test_list_page_renders(client, app_mod):
    _seed(app_mod)
    with app_mod.get_db() as db:
        app_mod.save_board_template(db, "Visible Template")
    resp = client.get("/admin/board-templates")
    assert resp.status_code == 200 and b"Visible Template" in resp.data
