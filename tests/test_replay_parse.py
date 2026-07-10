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


# ── Mega evolution / primal reversion attribution ──────────────────────────────
# A mega/primal is a SEPARATELY-DRAFTED pick ("Mega Gardevoir", "Primal Kyogre").
# Kills/deaths after |detailschange| must attribute to the mega/primal name, and
# resolve_poke_name must bridge Showdown suffix form → roster prefix form. Battle
# formes (Aegislash-Blade, etc.) fire the SAME |detailschange| but must stay
# unified. Real fixtures: tests/fixtures/yuricup_s9_58.log, _59.log.

def test_mega_same_trip_kill_attributes_to_mega():
    """A kill before AND after the mega evolves both land on '-Mega'."""
    log = "\n".join([
        "|player|p1|Alice", "|player|p2|Bob",
        "|switch|p1a: Gardy|Gardevoir, F|100/100",
        "|switch|p2a: Foe1|Pikachu, M|100/100",
        "|move|p1a: Gardy|Moonblast|p2a: Foe1",          # kill as BASE
        "|faint|p2a: Foe1",
        "|switch|p2a: Foe2|Snorlax, M|100/100",
        "|detailschange|p1a: Gardy|Gardevoir-Mega, F",   # mega now
        "|-mega|p1a: Gardy|Gardevoir|Gardevoirite",
        "|move|p1a: Gardy|Moonblast|p2a: Foe2",          # kill as MEGA
        "|faint|p2a: Foe2",
        "|win|Alice",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p1"] == {"Gardevoir-Mega": 2}
    assert "Gardevoir" not in p["kills"]["p1"]


def test_mega_death_same_trip_attributes_to_mega():
    log = "\n".join([
        "|player|p1|Alice", "|player|p2|Bob",
        "|switch|p1a: Sw|Swampert, M|100/100",
        "|switch|p2a: F1|Pikachu, M|100/100",
        "|detailschange|p1a: Sw|Swampert-Mega, M",
        "|-mega|p1a: Sw|Swampert|Swampertite",
        "|move|p2a: F1|Thunder|p1a: Sw",
        "|faint|p1a: Sw",
        "|win|Bob",
    ])
    p = R.parse_log(log)
    assert p["deaths"]["p1"] == {"Swampert-Mega": 1}


def test_battle_forme_toggle_stays_unified():
    """Aegislash Blade<->Shield fires |detailschange| but is ONE drafted pick."""
    log = "\n".join([
        "|player|p1|Alice", "|player|p2|Bob",
        "|switch|p1a: Aeg|Aegislash, M|100/100",
        "|switch|p2a: F1|Pikachu, M|100/100",
        "|detailschange|p1a: Aeg|Aegislash-Blade, M",
        "|move|p1a: Aeg|Shadow Sneak|p2a: F1",
        "|faint|p2a: F1",
        "|switch|p2a: F2|Snorlax, M|100/100",
        "|detailschange|p1a: Aeg|Aegislash-Shield, M",
        "|move|p1a: Aeg|Shadow Ball|p2a: F2",
        "|faint|p2a: F2",
        "|win|Alice",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p1"] == {"Aegislash": 2}


def test_primal_attributes_to_primal():
    log = "\n".join([
        "|player|p1|Alice", "|player|p2|Bob",
        "|switch|p1a: Kyo|Kyogre|100/100",
        "|switch|p2a: F1|Pikachu, M|100/100",
        "|detailschange|p1a: Kyo|Kyogre-Primal",
        "|-primal|p1a: Kyo",
        "|move|p1a: Kyo|Water Spout|p2a: F1",
        "|faint|p2a: F1",
        "|win|Alice",
    ])
    p = R.parse_log(log)
    assert p["kills"]["p1"] == {"Kyogre-Primal": 1}


def test_resolve_suffix_to_prefix_roster():
    r = ["Mega Gardevoir", "Gardevoir", "Mega Charizard X", "Mega Charizard Y",
         "Primal Kyogre", "Kyogre", "Mega Absol Z"]
    assert R.resolve_poke_name("Gardevoir-Mega", r) == "Mega Gardevoir"
    assert R.resolve_poke_name("Charizard-Mega-X", r) == "Mega Charizard X"
    assert R.resolve_poke_name("Charizard-Mega-Y", r) == "Mega Charizard Y"
    assert R.resolve_poke_name("Kyogre-Primal", r) == "Primal Kyogre"
    assert R.resolve_poke_name("Absol-Mega-Z", r) == "Mega Absol Z"
    # base stays base; mega not on roster falls back to base
    assert R.resolve_poke_name("Gardevoir", r) == "Gardevoir"
    assert R.resolve_poke_name("Swampert-Mega", ["Swampert"]) == "Swampert"
    # hyphenated base names must never be mangled
    assert R.resolve_poke_name("Chien-Pao", ["Chien-Pao"]) == "Chien-Pao"
    assert R.resolve_poke_name("Ho-Oh", ["Ho-Oh"]) == "Ho-Oh"


def test_real_fixture_58_mega_resolution():
    import os
    fx = os.path.join(os.path.dirname(__file__), "fixtures", "yuricup_s9_58.log")
    if not os.path.exists(fx):
        import pytest
        pytest.skip("fixture not present")
    log = open(fx, encoding="utf-8").read()
    p = R.parse_log(log)
    roster = ["Mega Swampert", "Swampert", "Mega Gardevoir", "Gardevoir"]
    # Swampert megas and scores; must resolve to the drafted 'Mega Swampert'
    assert R.resolve_poke_name("Swampert-Mega", roster) == "Mega Swampert"
    assert R.resolve_poke_name("Gardevoir-Mega", roster) == "Mega Gardevoir"
    # parser emits the mega suffix name (not base) for the mega's stats
    all_names = set(p["kills"]["p1"]) | set(p["deaths"]["p1"]) | \
        set(p["kills"]["p2"]) | set(p["deaths"]["p2"])
    assert "Swampert-Mega" in all_names
    assert "Gardevoir-Mega" in all_names


def test_recap_shows_mega_ko_full_bring():
    """Regression: when a coach drafts BOTH base and mega and brings a full team,
    the mega's KO must appear on the recap card (not vanish under a name that's
    never displayed). Adversarial-review finding."""
    log = "\n".join([
        "|player|p1|Alice", "|player|p2|Bob",
        "|poke|p1|Gardevoir, F|", "|poke|p1|Politoed, M|",
        "|poke|p2|Pikachu, M|", "|poke|p2|Snorlax, M|",
        "|teampreview", "|start",
        "|switch|p1a: Gardy|Gardevoir, F|100/100",
        "|switch|p2a: Pika|Pikachu, M|100/100",
        "|turn|1",
        "|detailschange|p1a: Gardy|Gardevoir-Mega, F",
        "|-mega|p1a: Gardy|Gardevoir|Gardevoirite",
        "|move|p1a: Gardy|Moonblast|p2a: Pika",
        "|faint|p2a: Pika",
        "|switch|p2a: Snor|Snorlax, M|100/100",
        "|switch|p1a: Poli|Politoed, M|100/100",
        "|turn|2",
        "|move|p1a: Poli|Hydro Pump|p2a: Snor",
        "|faint|p2a: Snor",
        "|win|Alice",
    ])
    raw = R.parse_log_recap(log)
    roster = ["Mega Gardevoir", "Gardevoir", "Politoed"]
    nmap = {n: R.resolve_poke_name(n, roster)
            for n in set(raw["rosters"]["p1"]) | set(raw["brought"]["p1"])}
    rec = R.build_recap(raw, name_map_p1=nmap, name_map_p2={})
    home = rec.get("homeRoster") or rec.get("home_roster") or []
    rows = {m["name"]: m.get("note", "") for m in home}
    assert "Mega Gardevoir" in rows, f"mega missing from recap: {list(rows)}"
    assert "Pikachu" in rows["Mega Gardevoir"], f"KO lost: {rows}"
