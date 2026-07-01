"""Uber-combination validation must be order-independent (symmetric)."""


def test_legal_uber_pairs_allowed_in_both_orders(app_mod):
    can = app_mod._can_add_uber
    legal = [("Gold", "Bronze"), ("Silver", "Bronze"), ("Silver", "Silver"), ("Bronze", "Bronze")]
    for a, b in legal:
        assert can([a], b), f"{a} then {b} should be allowed"
        assert can([b], a), f"{b} then {a} should be allowed (draft order must not matter)"


def test_bronze_then_gold_is_allowed(app_mod):
    # The exact reported bug: a Bronze uber drafted first, then a Gold.
    assert app_mod._can_add_uber(["Bronze"], "Gold")


def test_illegal_uber_pairs_rejected_both_orders(app_mod):
    can = app_mod._can_add_uber
    for a, b in [("Gold", "Gold"), ("Gold", "Silver"), ("Silver", "Gold")]:
        assert not can([a], b)
        assert not can([b], a)


def test_platinum_uses_both_slots(app_mod):
    assert not app_mod._can_add_uber(["Platinum"], "Bronze")


def test_any_single_uber_is_a_valid_first_pick(app_mod):
    for t in ["Platinum", "Gold", "Silver", "Bronze"]:
        assert app_mod._can_add_uber([], t)


def test_valid_second_choices_symmetric_with_can_add(app_mod):
    for first in ["Gold", "Silver", "Bronze"]:
        choices = app_mod._valid_uber_second_choices([first])
        for c in choices:
            assert app_mod._can_add_uber([first], c)
