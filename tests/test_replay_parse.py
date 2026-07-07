"""Regression tests for the Showdown replay parser (replay_utils.parse_log).

Covers two accuracy bugs found by auditing against real replays:
  B2 — a nicknamed Pokémon's kills/deaths must attribute to the SPECIES
       (from the switch line's parts[3]), not the nickname.
  B3 — a Pokémon that faints to an INDIRECT source (entry hazards / status /
       recoil, i.e. `[from] ...` with no `[of]` attacker) must credit the KO
       to NO ONE, not to whoever last hit the slot's previous occupant.
"""
import replay_utils as R


def test_nickname_attributes_to_species():
    # p1's "Chompy" is really Garchomp; it KOs p2's Pikachu.
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
    # kill credited to Garchomp, not "Chompy"
    assert p["kills"]["p1"] == {"Garchomp": 1}
    assert "Chompy" not in p["kills"]["p1"]
    assert p["deaths"]["p2"] == {"Pikachu": 1}
    assert "Garchomp" in p["p1"]["pokemon_used"]


def test_hazard_faint_credits_no_one():
    # p2's Pikachu directly KOs nothing; p1's Mamoswine faints to Stealth Rock
    # on switch-in — no opponent should get that kill.
    log = "\n".join([
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Ninjask|Ninjask, M|100/100",
        "|switch|p2a: Pikachu|Pikachu, F|100/100",
        "|move|p2a: Pikachu|Thunderbolt|p1a: Ninjask",
        "|-damage|p1a: Ninjask|0 fnt",
        "|faint|p1a: Ninjask",
        "|switch|p1a: Mamoswine|Mamoswine, M|100/100",
        "|-damage|p1a: Mamoswine|0 fnt|[from] Stealth Rock",
        "|faint|p1a: Mamoswine",
        "|win|Bob",
    ])
    p = R.parse_log(log)
    # Pikachu earned exactly the Ninjask KO — NOT the Mamoswine hazard faint.
    assert p["kills"]["p2"] == {"Pikachu": 1}
    # both p1 mons fainted; Mamoswine's death is recorded but credited to no one
    assert p["deaths"]["p1"] == {"Ninjask": 1, "Mamoswine": 1}
    # total kills (1) < total deaths (2): the hazard KO is correctly uncredited
    assert sum(p["kills"]["p2"].values()) == 1


def test_rocky_helmet_of_credits_opponent():
    # Indirect damage WITH an [of] attacker (Rocky Helmet) still credits them.
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
