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
