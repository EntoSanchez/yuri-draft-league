# tests/test_board_templates.py
def test_board_templates_table_exists(app_mod):
    with app_mod.get_db() as db:
        cols = {r["name"] for r in db.execute("PRAGMA table_info(draft_board_templates)")}
    assert {"id", "name", "kind", "notes", "board_json", "created_at", "updated_at"} <= cols
