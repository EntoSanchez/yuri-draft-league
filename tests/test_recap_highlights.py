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
