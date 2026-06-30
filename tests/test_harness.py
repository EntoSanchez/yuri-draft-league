def test_admin_can_reach_tiers_page(client):
    resp = client.get("/admin/tiers")
    assert resp.status_code == 200


def test_temp_db_has_draft_tiers_table(app_mod):
    with app_mod.get_db() as db:
        cols = [r["name"] for r in db.execute("PRAGMA table_info(draft_tiers)")]
    assert "points" in cols and "is_mega" in cols
