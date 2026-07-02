"""B3: configurable tier columns + ticket allocation; defaults reproduce today."""


def test_defaults_equal_current_constants(app_mod):
    assert app_mod.get_ticket_alloc() == {"T1": 1, "T2": 1, "T3": 2, "T4": 2, "T5": 2}
    assert app_mod.get_ticket_rank() == {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}
    assert app_mod.get_tier_to_ticket() == {
        "Tier 1": "T1", "Tier 2": "T2", "Tier 3": "T3", "Tier 4": "T4", "Tier 5": "T5"}


def test_default_columns_partition_0_to_30(app_mod):
    defs = app_mod.get_tier_definitions()
    assert [d["name"] for d in defs] == ["Tier 1", "Tier 2", "Tier 3", "Tier 4", "Tier 5"]
    seen = sorted(c for d in defs for c in d["columns"])
    assert seen == list(range(0, 31))  # every point 0..30 assigned exactly once


def test_stored_definitions_override_and_derive(app_mod):
    import json
    stored = [
        {"name": "Tier 1", "columns": [20, 21], "ticket_alloc": 3},
        {"name": "Tier 2", "columns": [10, 11], "ticket_alloc": 1},
        {"name": "Tier 3", "columns": [0, 1], "ticket_alloc": 1},
        {"name": "Tier 4", "columns": [2, 3], "ticket_alloc": 1},
        {"name": "Tier 5", "columns": [4, 5], "ticket_alloc": 1},
    ]
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('tier_definitions', ?)",
                   (json.dumps(stored),))
    assert app_mod.get_ticket_alloc()["T1"] == 3
    assert app_mod.get_tier_to_ticket()["Tier 1"] == "T1"


def _old_regular_tier_label(pts):
    if pts >= 16: return "Tier 1"
    if pts >= 13: return "Tier 2"
    if pts >= 9:  return "Tier 3"
    if pts >= 5:  return "Tier 4"
    if pts >= 0:  return "Tier 5"
    return ""


def test_regular_tier_label_matches_old_for_0_to_30(app_mod):
    for pts in range(0, 31):
        assert app_mod._regular_tier_label(pts) == _old_regular_tier_label(pts), f"diff at {pts}"


def test_regular_tier_label_honors_custom_columns(app_mod):
    import json
    # Inverted columns (low pts -> Tier 1, high pts -> Tier 5) so results DIFFER from
    # the old thresholds — the test must fail against old code and pass after the refactor.
    stored = [
        {"name": "Tier 1", "columns": [0, 1], "ticket_alloc": 1},     # old would call 0 -> Tier 5
        {"name": "Tier 2", "columns": [2, 3], "ticket_alloc": 1},
        {"name": "Tier 3", "columns": [4, 5], "ticket_alloc": 1},
        {"name": "Tier 4", "columns": [6, 7], "ticket_alloc": 1},
        {"name": "Tier 5", "columns": [16, 17], "ticket_alloc": 1},   # old would call 16 -> Tier 1
    ]
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('tier_definitions', ?)",
                   (json.dumps(stored),))
    assert app_mod._regular_tier_label(0) == "Tier 1"    # old code: "Tier 5"
    assert app_mod._regular_tier_label(16) == "Tier 5"   # old code: "Tier 1"
