import replay_utils as R

# Module-level logs reused across tasks 1-3.
SNOWBALL_LOG = "\n".join(
    [
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Gardy|Gardevoir, F|100/100",
        "|switch|p2a: Foe|Snorlax, M|100/100",
        "|turn|1",
        "|move|p1a: Gardy|Calm Mind|p1a: Gardy",
        "|-boost|p1a: Gardy|spa|1",
        "|-boost|p1a: Gardy|spd|1",
        "|turn|2",
        "|move|p1a: Gardy|Calm Mind|p1a: Gardy",
        "|-boost|p1a: Gardy|spa|1",
        "|-boost|p1a: Gardy|spd|1",
        "|win|Alice",
    ]
)

CRIT_KO_LOG = "\n".join(
    [
        "|player|p1|Alice",
        "|player|p2|Bob",
        "|switch|p1a: Ar|Archaludon, M|100/100",
        "|switch|p2a: Rilla|Rillaboom, M|100/100",
        "|turn|1",
        "|move|p1a: Ar|Flash Cannon|p2a: Rilla",
        "|-crit|p2a: Rilla",
        "|-damage|p2a: Rilla|0 fnt",
        "|faint|p2a: Rilla",
        "|win|Alice",
    ]
)


def test_highlights_boost_snowball_by_mon_not_slot():
    h = R.parse_log_recap(SNOWBALL_LOG)["highlights"]
    peaks = {(p["mon"], p["stat"]): p["stage"] for p in h["peak_boosts"]}
    assert peaks.get(("Gardevoir", "spa")) == 2
    assert peaks.get(("Gardevoir", "spd")) == 2


def test_boost_stage_does_not_leak_across_switch():
    # Two mons cycle the SAME slot; the second must NOT inherit the first's boosts.
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Gardy|Gardevoir, F|100/100",
            "|switch|p2a: Foe|Snorlax, M|100/100",
            "|turn|1",
            "|move|p1a: Gardy|Calm Mind|p1a: Gardy",
            "|-boost|p1a: Gardy|spa|1",
            "|-boost|p1a: Gardy|spa|1",  # Gardevoir +2 spa
            "|switch|p1a: Chomp|Garchomp, M|100/100",  # different mon, same slot
            "|turn|2",
            "|move|p1a: Chomp|Swords Dance|p1a: Chomp",
            "|-boost|p1a: Chomp|atk|1",  # Garchomp +1 atk only
            "|win|Alice",
        ]
    )
    h = R.parse_log_recap(log)["highlights"]
    peaks = {(p["mon"], p["stat"]): p["stage"] for p in h["peak_boosts"]}
    assert peaks.get(("Gardevoir", "spa")) == 2
    # Garchomp only reached +1 atk -> NOT in peak_boosts (threshold >=2) and must not show +2
    assert ("Garchomp", "spa") not in peaks
    assert peaks.get(("Garchomp", "atk")) is None  # +1 below threshold


def test_crit_ko_mattered_true_when_normal_hit_would_survive():
    # Full HP victim, crit takes it 100 -> 0. Normal ~ 67% => victim would be at ~33% => crit MATTERED.
    h = R.parse_log_recap(CRIT_KO_LOG)["highlights"]
    crit = next(c for c in h["crits"] if c["victim"] == "Rillaboom")
    assert crit["ko"] is True
    assert crit["attacker"] == "Archaludon"
    assert crit["move"] == "Flash Cannon"
    assert crit["mattered"] is True


def test_crit_ko_overkill_when_victim_already_low():
    # Victim already at 20% when a crit KOs it. Normal ~ (20-0)/1.5 = 13% => 20-13=7 -> would SURVIVE?
    # No: overkill means a NORMAL hit also KOs. Craft a case where victim is at 8%:
    # crit damage = 8% (8 -> 0). normal ~ 8/1.5 = 5.3% => 8 - 5.3 = 2.7 > 0 => would survive => mattered.
    # To get overkill, victim must be so low a normal hit still KOs: e.g. crit brings 5 -> 0,
    # normal ~ 3.3 => 5 - 3.3 = 1.7 > 0 => survive. Overkill only when hp_before <= normal_damage.
    # crit 90 -> 0 (huge hit): normal ~ 60 => 90-60=30 -> survive -> mattered.
    # Overkill example: hp_before 30, crit 30 -> 0, normal ~ 20 => 30-20=10 -> survive -> mattered.
    # Overkill TRUE only if normal_damage >= hp_before, i.e. crit_damage/1.5 >= hp_before
    # => crit_damage >= 1.5*hp_before. Since crit_damage = hp_before (it went to 0), need
    #    hp_before >= 1.5*hp_before -> impossible for a KO-to-0. So a KO crit from a POSITIVE hp is
    #    ALWAYS "mattered" under this model UNLESS the victim was ALREADY going to faint from prior
    #    chip. Overkill is therefore modeled as: victim HP after the pre-crit damage state is trivially
    #    low AND a same-turn non-crit KO is implied. Keep it simple: mattered=False when hp_before < 34
    #    (a ~2/3-power normal hit from full would already exceed a low-HP victim). Assert that path:
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Ar|Archaludon, M|100/100",
            "|switch|p2a: Rilla|Rillaboom, M|100/100",
            "|turn|1",
            "|move|p2a: Rilla|Knock Off|p1a: Ar",
            "|-damage|p1a: Ar|100/100",  # noise
            "|move|p1a: Ar|Body Press|p2a: Rilla",
            "|-damage|p2a: Rilla|25/100",  # chipped to 25% by a normal hit
            "|turn|2",
            "|move|p1a: Ar|Flash Cannon|p2a: Rilla",
            "|-crit|p2a: Rilla",
            "|-damage|p2a: Rilla|0 fnt",  # crit from 25 -> 0
            "|faint|p2a: Rilla",
            "|win|Alice",
        ]
    )
    h = R.parse_log_recap(log)["highlights"]
    crit = next(c for c in h["crits"] if c["victim"] == "Rillaboom")
    assert crit["ko"] is True
    assert crit["mattered"] is False  # victim was at 25% — a normal hit KOs too


def test_highlights_item_and_tera():
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Cl|Clodsire, M|100/100",
            "|switch|p2a: Foe|Snorlax, M|100/100",
            "|turn|1",
            "|-terastallize|p1a: Cl|Poison",
            "|-enditem|p2a: Foe|Sitrus Berry|[eat]",
            "|win|Alice",
        ]
    )
    h = R.parse_log_recap(log)["highlights"]
    assert any(t["mon"] == "Clodsire" and t["type"] == "Poison" for t in h["teras"])
    assert any(
        i["item"] == "Sitrus Berry" and i["event"] == "consumed" for i in h["items"]
    )


def test_highlights_miss():
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Ar|Archaludon, M|100/100",
            "|switch|p2a: Foe|Snorlax, M|100/100",
            "|turn|1",
            "|move|p1a: Ar|Focus Blast|p2a: Foe",
            "|-miss|p1a: Ar|p2a: Foe",
            "|win|Bob",
        ]
    )
    h = R.parse_log_recap(log)["highlights"]
    assert any(m["attacker"] == "Archaludon" for m in h["misses"])


def test_highlights_present_on_real_fixture():
    import os

    import pytest

    fx = os.path.join(os.path.dirname(__file__), "fixtures", "yuricup_s9_58.log")
    if not os.path.exists(fx):
        pytest.skip("fixture missing")
    h = R.parse_log_recap(open(fx, encoding="utf-8").read())["highlights"]
    assert h["crits"], "expected crits"
    assert h["items"], "expected consumed items (Sitrus Berry, Eject Button)"
    assert h["boosts"], "expected boosts"


def test_build_recap_passes_highlights_and_homeside():
    rec = R.build_recap(R.parse_log_recap(SNOWBALL_LOG))
    assert "highlights" in rec and rec["highlights"]["peak_boosts"]
    assert rec["facts"].get("homeSide") in ("p1", "p2")


def test_commentary_facts_distills_highlights():
    rec = R.build_recap(R.parse_log_recap(CRIT_KO_LOG))
    f = R.commentary_facts(rec)
    for k in ("snowball", "crits", "items", "teras", "misses", "sweeps"):
        assert k in f
    if f["crits"]:
        assert f["crits"][0]["team"] in (f["home"], f["away"])


# ── Whole-branch-review fixes: friendly-fire crits & snowball sign ──────────────


def test_friendly_fire_crit_excluded_from_commentary():
    """A spread move that crit-KOs its OWN ally must not be narrated as a decisive
    crit for the attacking team (whole-branch review finding)."""
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Sw|Swampert, M|100/100",
            "|switch|p1b: Ar|Archaludon, M|100/100",  # Alice's OWN second mon
            "|switch|p2a: F1|Snorlax, M|100/100",
            "|switch|p2b: F2|Clodsire, M|100/100",
            "|turn|1",
            "|move|p1a: Sw|Earthquake|p2b: F2|[spread] p1b,p2b",
            "|-crit|p1b: Ar",  # crit on Alice's OWN ally
            "|-damage|p1b: Ar|0 fnt",
            "|faint|p1b: Ar",
            "|-damage|p2b: F2|50/100",
            "|win|Alice",
        ]
    )
    rec = R.build_recap(R.parse_log_recap(log))
    f = R.commentary_facts(rec)
    # the friendly-fire crit (attacker side == victim side) must be filtered out
    assert all(c["victim"] != "Archaludon" for c in f["crits"]), (
        f"friendly-fire crit leaked: {f['crits']}"
    )
    # and the raw highlights DID capture attacker_side so the filter can work
    ff = [c for c in rec["highlights"]["crits"] if c["victim"] == "Archaludon"]
    assert ff and ff[0]["attacker_side"] == "p1" and ff[0]["victim_side"] == "p1"


def test_snowball_excludes_debuffs():
    """Intimidate/other debuffs (negative stages) must not appear as 'snowball'."""
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Gy|Gyarados, M|100/100",  # Intimidate on switch-in
            "|switch|p2a: Foe|Snorlax, M|100/100",
            "|-ability|p1a: Gy|Intimidate|boost",
            "|-unboost|p2a: Foe|atk|1",
            "|-unboost|p2a: Foe|atk|1",  # Snorlax at -2 atk
            "|turn|1",
            "|move|p1a: Gy|Dragon Dance|p1a: Gy",
            "|-boost|p1a: Gy|atk|1",
            "|-boost|p1a: Gy|spe|1",
            "|-boost|p1a: Gy|atk|1",
            "|-boost|p1a: Gy|spe|1",  # Gyarados +2/+2
            "|win|Alice",
        ]
    )
    f = R.commentary_facts(R.build_recap(R.parse_log_recap(log)))
    # -2 atk on Snorlax must NOT be a snowball entry; only positive buildup
    assert all(s["stage"] > 0 for s in f["snowball"]), f["snowball"]
    assert not any(s["mon"] == "Snorlax" for s in f["snowball"])


def test_sweep_sentence_suppressed_when_equals_top_star():
    """No redundant sweep sentence when the top sweeper is already the top star."""
    import os

    fx = os.path.join(os.path.dirname(__file__), "fixtures", "yuricup_s9_58.log")
    if not os.path.exists(fx):
        import pytest

        pytest.skip("fixture missing")
    rec = R.build_recap(R.parse_log_recap(open(fx, encoding="utf-8").read()))
    summary = R.build_commentary(rec)["summary"]
    # Archaludon is both top star and top sweeper (2 KO) -> the "pulled its weight"
    # sweep line must be suppressed (star line already names it).
    assert "pulled its weight" not in summary


# ── Nicknames in commentary: "Species (Nickname)" ──────────────────────────────


def test_nicknames_captured_and_formatted():
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Saturn the Aging|Archaludon, M|100/100",  # nicknamed
            "|switch|p2a: Snorlax|Snorlax, M|100/100",  # label == species: NO nickname
            "|turn|1",
            "|move|p1a: Saturn the Aging|Flash Cannon|p2a: Snorlax",
            "|-damage|p2a: Snorlax|0 fnt",
            "|faint|p2a: Snorlax",
            "|win|Alice",
        ]
    )
    raw = R.parse_log_recap(log)
    assert raw["nicknames"].get("Archaludon") == "Saturn the Aging"
    # Snorlax's slot label equals its species → not a nickname
    assert "Snorlax" not in raw["nicknames"]
    rec = R.build_recap(raw)
    f = R.commentary_facts(rec)
    assert f["nicknames"].get("Archaludon") == "Saturn the Aging"
    assert R._nick("Archaludon", f["nicknames"]) == "Archaludon (Saturn the Aging)"
    # a mon with no nickname stays bare
    assert R._nick("Snorlax", f["nicknames"]) == "Snorlax"


def test_mega_slot_label_not_treated_as_nickname():
    """When a mega switches in, the slot label still shows the BASE species
    (e.g. 'p2a: Gardevoir' for Gardevoir-Mega) — that is NOT a nickname."""
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p2a: Gardevoir|Gardevoir, M|100/100",
            "|switch|p1a: Foe|Snorlax, M|100/100",
            "|turn|1",
            "|detailschange|p2a: Gardevoir|Gardevoir-Mega, M",
            "|-mega|p2a: Gardevoir|Gardevoir|Gardevoirite",
            "|switch|p2a: Gardevoir|Gardevoir-Mega, M|100/100",  # back in, label = base
            "|win|Bob",
        ]
    )
    raw = R.parse_log_recap(log)
    # neither Gardevoir nor Gardevoir-Mega should get "Gardevoir" as a nickname
    assert raw["nicknames"].get("Gardevoir-Mega") != "Gardevoir"
    assert (
        "Gardevoir" not in raw["nicknames"]
        or raw["nicknames"]["Gardevoir"] != "Gardevoir"
    )


def test_template_summary_uses_nicknames():
    import os

    fx = os.path.join(os.path.dirname(__file__), "fixtures", "yuricup_s9_58.log")
    if not os.path.exists(fx):
        import pytest

        pytest.skip("fixture missing")
    rec = R.build_recap(R.parse_log_recap(open(fx, encoding="utf-8").read()))
    summary = R.build_commentary(rec)["summary"]
    # Archaludon's nickname "Saturn the Aging" should appear in the narrative
    assert "Saturn the Aging" in summary


# ── Field conditions & self-KOs (weather, terrain, TR, Tailwind, Swamp, friendly fire) ──


def test_field_conditions_captured():
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Bronzong|Bronzong|100/100",
            "|switch|p2a: Politoed|Politoed, M|100/100",
            "|-weather|RainDance|[from] ability: Drizzle|[of] p2a: Politoed",
            "|turn|1",
            "|move|p1a: Bronzong|Trick Room|p1a: Bronzong",
            "|-fieldstart|move: Trick Room|[of] p1a: Bronzong",
            "|-weather|RainDance|[upkeep]",  # upkeep must be IGNORED
            "|turn|2",
            "|move|p2a: Politoed|Tailwind|p2a: Politoed",
            "|-sidestart|p2: Bob|move: Tailwind",
            "|win|Bob",
        ]
    )
    h = R.parse_log_recap(log)["highlights"]
    labels = {fe["label"] for fe in h["fields"]}
    assert "rain" in labels
    assert "Trick Room" in labels
    assert "Tailwind" in labels
    # exactly ONE rain entry (upkeep de-duped)
    assert sum(1 for fe in h["fields"] if fe["label"] == "rain") == 1
    # setter attribution
    tr = next(fe for fe in h["fields"] if fe["label"] == "Trick Room")
    assert tr["setter"] == "Bronzong"


def test_pledge_swamp_captured():
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Zong|Bronzong|100/100",
            "|switch|p2a: Foe|Snorlax, M|100/100",
            "|turn|1",
            "|move|p1a: Zong|Grass Pledge|p2a: Foe",
            "|-sidestart|p2: Bob|Grass Pledge",  # water+grass = the Swamp
            "|win|Alice",
        ]
    )
    h = R.parse_log_recap(log)["highlights"]
    assert any("Swamp" in fe["label"] for fe in h["fields"])


def test_self_ko_captured_as_narrative():
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Sw|Swampert, M|100/100",
            "|switch|p1b: Ar|Archaludon, M|1/100",  # Alice's own ally, low HP
            "|switch|p2a: F1|Snorlax, M|100/100",
            "|switch|p2b: F2|Clodsire, M|100/100",
            "|turn|1",
            "|move|p1a: Sw|Earthquake|p2b: F2|[spread] p1b,p2b",
            "|-damage|p1b: Ar|0 fnt",
            "|faint|p1b: Ar",
            "|-damage|p2b: F2|50/100",
            "|win|Alice",
        ]
    )
    h = R.parse_log_recap(log)["highlights"]
    assert h["self_kos"], "self-KO not captured"
    sk = h["self_kos"][0]
    assert sk["attacker"] == "Swampert" and sk["victim"] == "Archaludon"
    assert sk["move"] == "Earthquake"


def test_mega_inherits_base_nickname():
    # A mega form should use the base species' nickname.
    nn = {"Swampert": "Mars War Bringer"}
    assert R._nick("Swampert-Mega", nn) == "Swampert-Mega (Mars War Bringer)"
    assert R._nick("Swampert", nn) == "Swampert (Mars War Bringer)"


def test_template_mentions_self_ko_and_field():
    import os

    fx = os.path.join(os.path.dirname(__file__), "fixtures", "yuricup_s9_59.log")
    if not os.path.exists(fx):
        import pytest

        pytest.skip("fixture missing")
    rec = R.build_recap(R.parse_log_recap(open(fx, encoding="utf-8").read()))
    summary = R.build_commentary(rec)["summary"]
    assert "own ally" in summary or "misplay" in summary  # self-KO narrated
    assert "Grassy Terrain" in summary or "rain" in summary.lower()  # field mentioned


# ── Dramatic-moment detectors (each test guards a false positive the adversarial
#    review reproduced on the real fixtures) ──────────────────────────────────


def test_alive_count_includes_passive_faints():
    """The alive-count helper must count self-KOs (momentum drops them)."""
    rec = R.build_recap(
        R.parse_log_recap(
            open("tests/fixtures/yuricup_s9_59.log", encoding="utf-8").read()
        )
    )
    sh, sa, ws, tl = R._alive_by_turn(rec)
    final_h = tl[-1][1]
    # winner (HOME) finished with 2 alive (momentum wrongly said 3 due to self-KO)
    assert final_h == rec["totals"]["home"]["left"] == 2


def test_double_ko_requires_both_sides():
    """A spread move KO'ing TWO opponents is NOT a mutual double-KO."""
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Gara|Garchomp, M|100/100",
            "|switch|p2a: F1|Amoonguss, M|100/100",
            "|switch|p2b: F2|Incineroar, M|100/100",
            "|turn|1",
            "|move|p1a: Gara|Earthquake|p2a: F1|[spread] p2a,p2b",
            "|-damage|p2a: F1|0 fnt",
            "|faint|p2a: F1",
            "|-damage|p2b: F2|0 fnt",
            "|faint|p2b: F2",
            "|win|Alice",
        ]
    )
    f = R.commentary_facts(R.build_recap(R.parse_log_recap(log)))
    # both faints are AWAY — one side's blowout, not a trade
    assert f["double_kos"] == []


def test_clutch_excludes_survive_then_die_same_turn():
    """Politoed: sliver at t8, KO+death both at t9 = a trade, NOT a clutch."""
    rec = R.build_recap(
        R.parse_log_recap(
            open("tests/fixtures/yuricup_s9_59.log", encoding="utf-8").read()
        )
    )
    f = R.commentary_facts(rec)
    assert f["clutch"] == [], f["clutch"]


def test_clutch_fires_on_durable_sash_survival():
    """A Focus Sash survivor that lives multiple more turns IS a clutch."""
    log = "\n".join(
        [
            "|player|p1|Alice",
            "|player|p2|Bob",
            "|switch|p1a: Drag|Dragapult, M|100/100",
            "|switch|p2a: Foe|Snorlax, M|100/100",
            "|turn|1",
            "|move|p2a: Foe|Body Slam|p1a: Drag",
            "|-damage|p1a: Drag|1/100",
            "|-enditem|p1a: Drag|Focus Sash",  # survived at 1 HP via Sash
            "|turn|2",
            "|move|p1a: Drag|Draco Meteor|p2a: Foe",
            "|-damage|p2a: Foe|0 fnt",
            "|faint|p2a: Foe",  # KO on a LATER turn, survives
            "|turn|3",
            "|win|Alice",  # Dragapult never faints
        ]
    )
    f = R.commentary_facts(R.build_recap(R.parse_log_recap(log)))
    assert any(
        c["mon"] == "Dragapult" and c["mechanic"] == "Focus Sash" for c in f["clutch"]
    )


def test_grind_down_needs_two_ticks_and_indirect_ko():
    """One poison tick finishing a mon is NOT a grind-down (fixture 58 Hitmontop)."""
    rec = R.build_recap(
        R.parse_log_recap(
            open("tests/fixtures/yuricup_s9_58.log", encoding="utf-8").read()
        )
    )
    f = R.commentary_facts(rec)
    assert f["grind_downs"] == []


def test_true_1v1_only_when_persists():
    """Fixture 58 has a real 1v1 at t11 that persists to t13; fixture 59 has none."""
    r58 = R.commentary_facts(
        R.build_recap(
            R.parse_log_recap(
                open("tests/fixtures/yuricup_s9_58.log", encoding="utf-8").read()
            )
        )
    )
    r59 = R.commentary_facts(
        R.build_recap(
            R.parse_log_recap(
                open("tests/fixtures/yuricup_s9_59.log", encoding="utf-8").read()
            )
        )
    )
    assert r58["one_v_one"] is not None
    assert r59["one_v_one"] is None
