"""Regression tests for the Showdown replay parser (replay_utils.parse_log).

Covers accuracy bugs found by auditing against real replays:
  B2 — a nicknamed Pokémon's kills/deaths attribute to the SPECIES (switch-line
       parts[3]), not the nickname.
  Indirect KOs — a faint from an entry hazard or poison/burn is credited to the
       Pokémon RESPONSIBLE (the hazard setter / status applier), while a purely
       self-inflicted faint (Life Orb, recoil) is credited to no one.
"""
import replay_utils as R


def test_nickname_attributes_to_species():
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Chompy|Garchomp, M|100/100",
        "|switch|p2a: Pikachu|Pikachu, F|100/100",
        "|move|p1a: Chompy|Earthquake|p2a: Pikachu",
        "|-damage|p2a: Pikachu|0 fnt",
        "|faint|p2a: Pikachu",
        "|win|Alice",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p1"] == {"Garchomp": 1}
    assert "Chompy" not in p["kills"]["p1"]
    assert p["deaths"]["p2"] == {"Pikachu": 1}
    assert "Garchomp" in p["p1"]["pokemon_used"]


def test_stealth_rock_kill_credits_the_setter():
    # p2's Bronzong sets Stealth Rock on p1's side; p1's Mamoswine later switches
    # in and faints to it. Bronzong should get that KO.
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Slowking|Slowking, M|100/100",
        "|switch|p2a: Bronzong|Bronzong, M|100/100",
        "|move|p2a: Bronzong|Stealth Rock|p1a: Slowking",
        "|-sidestart|p1: Alice|move: Stealth Rock",
        "|switch|p1a: Mamoswine|Mamoswine, M|5/100",
        "|-damage|p1a: Mamoswine|0 fnt|[from] Stealth Rock",
        "|faint|p1a: Mamoswine",
        "|win|Bob",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p2"] == {"Bronzong": 1}  # setter credited
    assert p["deaths"]["p1"] == {"Mamoswine": 1}
    assert sum(p["kills"]["p2"].values()) == sum(p["deaths"]["p1"].values())  # balanced


def test_burn_kill_credits_the_status_applier():
    # p1's Rotom burns p2's Tauros with Will-O-Wisp; Tauros later faints to burn.
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Rotom|Rotom-Wash|100/100",
        "|switch|p2a: Tauros|Tauros, M|100/100",
        "|move|p1a: Rotom|Will-O-Wisp|p2a: Tauros",
        "|-status|p2a: Tauros|brn",
        "|-damage|p2a: Tauros|0 fnt|[from] brn",
        "|faint|p2a: Tauros",
        "|win|Alice",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p1"] == {"Rotom-Wash": 1}  # burn-applier credited
    assert p["deaths"]["p2"] == {"Tauros": 1}


def test_life_orb_self_ko_credits_no_one():
    # A mon faints to its own Life Orb recoil — no opponent earned that.
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Chomp|Garchomp, M|1/100",
        "|switch|p2a: Blissey|Blissey, F|100/100",
        "|move|p1a: Chomp|Earthquake|p2a: Blissey",
        "|-damage|p2a: Blissey|80/100",
        "|-damage|p1a: Chomp|0 fnt|[from] item: Life Orb",
        "|faint|p1a: Chomp",
        "|win|Bob",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p2"] == {}              # Blissey did NOT KO Garchomp
    assert p["deaths"]["p1"] == {"Garchomp": 1}


def test_rocky_helmet_of_credits_opponent():
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Ferro|Ferrothorn, M|100/100",
        "|switch|p2a: Weakmon|Rattata, F|1/100",
        "|move|p2a: Weakmon|Tackle|p1a: Ferro",
        "|-damage|p2a: Weakmon|0 fnt|[from] item: Rocky Helmet|[of] p1a: Ferro",
        "|faint|p2a: Weakmon",
        "|win|Alice",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p1"] == {"Ferrothorn": 1}
    assert p["deaths"]["p2"] == {"Rattata": 1}


def test_flame_orb_self_burn_ko_credits_no_one():
    # A mon burned by its OWN Flame Orb, then fainting to burn, credits no one —
    # even though the opponent moved last that turn.
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Torkoal|Torkoal, M|10/100",
        "|switch|p2a: Pikachu|Pikachu, F|100/100",
        "|move|p2a: Pikachu|Thunderbolt|p1a: Torkoal",   # opponent moved last
        "|-damage|p1a: Torkoal|8/100",
        "|-status|p1a: Torkoal|brn|[from] item: Flame Orb",
        "|-damage|p1a: Torkoal|0 fnt|[from] brn",
        "|faint|p1a: Torkoal",
        "|win|Bob",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p2"] == {}   # Pikachu did NOT earn this KO
    assert p["deaths"]["p1"] == {"Torkoal": 1}


def test_flame_body_ability_burn_credits_the_of_mon():
    # Contact-move burn via Flame Body: [of] names the ability holder — credit it,
    # not whoever moved last.
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p2a: Volcarona|Volcarona, F|100/100",
        "|switch|p1a: Arcanine|Arcanine, M|10/100",
        "|move|p1a: Arcanine|Extreme Speed|p2a: Volcarona",
        "|-status|p1a: Arcanine|brn|[from] ability: Flame Body|[of] p2a: Volcarona",
        "|-damage|p1a: Arcanine|0 fnt|[from] brn",
        "|faint|p1a: Arcanine",
        "|win|Bob",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p2"] == {"Volcarona": 1}
    assert p["deaths"]["p1"] == {"Arcanine": 1}


def test_zoroark_illusion_kills_reattributed_on_reveal():
    # Zoroark disguised as Garchomp KOs Pikachu, then is revealed on faint. Its
    # kill must land on Zoroark, and the disguise must not appear in used.
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Garchomp|Garchomp, M|100/100",     # Zoroark disguised
        "|switch|p2a: Pikachu|Pikachu, F|100/100",
        "|move|p1a: Garchomp|Sucker Punch|p2a: Pikachu",
        "|-damage|p2a: Pikachu|0 fnt",
        "|faint|p2a: Pikachu",
        "|switch|p2a: Snorlax|Snorlax, M|100/100",
        "|move|p2a: Snorlax|Body Slam|p1a: Garchomp",
        "|-damage|p1a: Garchomp|0 fnt",
        "|replace|p1a: Zoroark|Zoroark, M|0 fnt",         # revealed
        "|faint|p1a: Zoroark",
        "|win|Bob",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p1"] == {"Zoroark": 1}      # kill moved off the disguise
    assert "Garchomp" not in p["kills"]["p1"]
    assert p["deaths"]["p1"] == {"Zoroark": 1}
    assert "Garchomp" not in p["p1"]["pokemon_used"]
    assert "Zoroark" in p["p1"]["pokemon_used"]


def test_toxic_spikes_kill_credits_the_setter():
    # p2's Glimmora sets Toxic Spikes; p1's mon switches in, is poisoned, and later
    # faints to it. Credit Glimmora (the setter), not whoever moved last.
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Lead|Skarmory, M|100/100",
        "|switch|p2a: Glimmora|Glimmora, M|100/100",
        "|move|p2a: Glimmora|Toxic Spikes|p1a: Lead",
        "|-sidestart|p1: Alice|move: Toxic Spikes",
        "|move|p2a: Glimmora|Power Gem|p1a: Lead",         # a later, unrelated move
        "|switch|p1a: Togekiss|Togekiss, F|30/100",
        "|-status|p1a: Togekiss|psn|[from] move: Toxic Spikes",
        "|-damage|p1a: Togekiss|0 fnt|[from] psn",
        "|faint|p1a: Togekiss",
        "|win|Bob",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p2"] == {"Glimmora": 1}
    assert p["deaths"]["p1"] == {"Togekiss": 1}


def test_future_sight_credits_the_user_even_after_it_leaves():
    # Slowking uses Future Sight, then switches out; 2 turns later it lands and KOs
    # Kingambit. Slowking must still get the KO.
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Slowking|Slowking-Galar|100/100",
        "|switch|p2a: Kingambit|Kingambit, M|50/100",
        "|move|p1a: Slowking|Future Sight|p2a: Kingambit",
        "|-start|p1a: Slowking|move: Future Sight",
        "|switch|p1a: Ferrothorn|Ferrothorn, M|100/100",
        "|turn|3",
        "|-end|p2a: Kingambit|move: Future Sight",
        "|-damage|p2a: Kingambit|0 fnt|[from] move: Future Sight",
        "|faint|p2a: Kingambit",
        "|win|Alice",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p1"] == {"Slowking-Galar": 1}
    assert p["deaths"]["p2"] == {"Kingambit": 1}
