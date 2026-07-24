"""Tests for the commentary-quality upgrades:

- timeline: one merged, turn-sorted spine of notable events (fixes recaps
  narrating events out of order)
- crits: facts expose ONLY crits that plausibly mattered (kills the "no lucky
  crits altered the outcome" filler)
- key_status fate: a mon frozen/slept and KO'd before it could act is flagged
  even with zero |cant| lines; a thawed mon is not
- miss_streaks: the same mon whiffing 2+ times is a story beat; one miss is noise
"""

import replay_utils as R


def _recap(lines):
    return R.build_recap(R.parse_log_recap("\n".join(lines)))


BASE = [
    "|player|p1|Alice|cheryl|",
    "|player|p2|Bob|trainer.png|",
    "|poke|p1|Glaceon, F|",
    "|poke|p1|Garchomp, M|",
    "|poke|p2|Dragonite, M|",
    "|poke|p2|Pikachu, F|",
    "|start",
    "|switch|p1a: Glaceon|Glaceon, F|100/100",
    "|switch|p2a: Dragonite|Dragonite, M|100/100",
]


def test_frozen_and_koed_before_acting_flagged():
    # Dragonite is frozen T1 and KO'd T2 without ever acting (no |cant| line —
    # it simply never got to move). The freeze decided its game.
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|60/100",
        "|-status|p2a: Dragonite|frz",
        "|turn|2",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|0 fnt",
        "|faint|p2a: Dragonite",
        "|win|Alice",
    ])
    f = R.commentary_facts(recap)
    ks = [k for k in f["key_status"] if k["mon"] == "Dragonite"]
    assert ks, f["key_status"]
    assert ks[0]["status"] == "frz"
    assert ks[0]["fate"] == "koed_before_acting"


def test_frozen_with_lost_turns_counts_cants():
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|60/100",
        "|-status|p2a: Dragonite|frz",
        "|turn|2",
        "|cant|p2a: Dragonite|frz",
        "|turn|3",
        "|cant|p2a: Dragonite|frz",
        "|turn|4",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|0 fnt",
        "|faint|p2a: Dragonite",
        "|win|Alice",
    ])
    f = R.commentary_facts(recap)
    ks = [k for k in f["key_status"] if k["mon"] == "Dragonite"]
    assert ks and ks[0]["missed_turns"] == 2
    assert ks[0]["fate"] == "never_recovered"


def test_prompt_thaw_not_flagged_as_fate():
    # Frozen T1, thawed T2 (-curestatus), KO'd much later — the freeze did NOT
    # decide its game; with no lost turns it must not appear at all.
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|60/100",
        "|-status|p2a: Dragonite|frz",
        "|turn|2",
        "|-curestatus|p2a: Dragonite|frz|[msg]",
        "|move|p2a: Dragonite|Earthquake|p1a: Glaceon",
        "|-damage|p1a: Glaceon|40/100",
        "|turn|3",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|0 fnt",
        "|faint|p2a: Dragonite",
        "|win|Alice",
    ])
    f = R.commentary_facts(recap)
    assert not [k for k in f["key_status"] if k["mon"] == "Dragonite"], f["key_status"]


def test_miss_streak_two_whiffs_flagged():
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p1a: Glaceon|Blizzard|p2a: Dragonite",
        "|-miss|p1a: Glaceon|p2a: Dragonite",
        "|turn|2",
        "|move|p1a: Glaceon|Blizzard|p2a: Dragonite",
        "|-miss|p1a: Glaceon|p2a: Dragonite",
        "|turn|3",
        "|move|p2a: Dragonite|Earthquake|p1a: Glaceon",
        "|-damage|p1a: Glaceon|0 fnt",
        "|faint|p1a: Glaceon",
        "|win|Bob",
    ])
    f = R.commentary_facts(recap)
    assert f["miss_streaks"], "two misses by the same mon must be a streak"
    ms = f["miss_streaks"][0]
    assert ms["mon"] == "Glaceon" and ms["count"] == 2 and ms["turns"] == [1, 2]


def test_single_miss_is_not_a_streak():
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p1a: Glaceon|Blizzard|p2a: Dragonite",
        "|-miss|p1a: Glaceon|p2a: Dragonite",
        "|turn|2",
        "|move|p2a: Dragonite|Earthquake|p1a: Glaceon",
        "|-damage|p1a: Glaceon|0 fnt",
        "|faint|p1a: Glaceon",
        "|win|Bob",
    ])
    f = R.commentary_facts(recap)
    assert f["miss_streaks"] == []


def test_sweep_genre_and_ko_ending():
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|0 fnt",
        "|faint|p2a: Dragonite",
        "|win|Alice",
    ])
    f = R.commentary_facts(recap)
    assert f["genre"] == "sweep"
    assert f["ended_by"] == "ko"


def test_forfeit_ending_detected():
    # |win| while Bob's Dragonite is still standing — forfeit/timer, not a KO.
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|60/100",
        "|win|Alice",
    ])
    f = R.commentary_facts(recap)
    assert f["ended_by"] == "forfeit_or_timer"


def test_benched_mega_not_listed_as_benched():
    # Preview says "Gardevoir"; the mon enters as Gardevoir-Mega. It played —
    # it must not appear in benched. Pikachu never appeared: genuinely benched.
    recap = _recap([
        "|player|p1|Alice|cheryl|",
        "|player|p2|Bob|trainer.png|",
        "|poke|p1|Glaceon, F|",
        "|poke|p2|Gardevoir, F|",
        "|poke|p2|Pikachu, F|",
        "|start",
        "|switch|p1a: Glaceon|Glaceon, F|100/100",
        "|switch|p2a: Gardevoir|Gardevoir, F|100/100",
        "|detailschange|p2a: Gardevoir|Gardevoir-Mega, F",
        "|turn|1",
        "|move|p2a: Gardevoir|Hyper Voice|p1a: Glaceon",
        "|-damage|p1a: Glaceon|0 fnt",
        "|faint|p1a: Glaceon",
        "|win|Bob",
    ])
    f = R.commentary_facts(recap)
    bob_bench = f["benched"][f["winner"]]
    assert "Gardevoir" not in bob_bench, bob_bench
    assert "Pikachu" in bob_bench


def test_wasted_turns_and_luck_counts():
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|60/100",
        "|-status|p2a: Dragonite|par",
        "|turn|2",
        "|cant|p2a: Dragonite|par",
        "|turn|3",
        "|move|p2a: Dragonite|Earthquake|p1a: Glaceon",
        "|-damage|p1a: Glaceon|0 fnt",
        "|faint|p1a: Glaceon",
        "|win|Bob",
    ])
    f = R.commentary_facts(recap)
    loser_luck = f["luck_summary"][f["winner"]]  # Bob's side lost the para turn
    assert loser_luck["turns_lost_to_status"] == 1
    assert f["wasted_turns"][f["winner"]]["turns_lost"] == 1


def test_final_gambit_death_cause_and_score():
    # Dragonite sacrifices itself with Final Gambit: the death gets a CAUSE (its
    # own move), no opponent is credited, and the score still counts the downed
    # mon for the opponent ("1-0", mons taken down).
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p2a: Dragonite|Final Gambit|p1a: Glaceon",
        "|-damage|p1a: Glaceon|1/100",
        "|faint|p2a: Dragonite",
        "|win|Alice",
    ])
    f = R.commentary_facts(recap)
    p0 = f["plays"][0]
    assert p0["attacker"] is None
    assert p0["cause"] == "its own Final Gambit", p0
    assert f["score"] == "1-0"
    assert any("Final Gambit" in e["event"] for e in f["timeline"])


def test_recoil_death_cause():
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p2a: Dragonite|Flare Blitz|p1a: Glaceon",
        "|-damage|p1a: Glaceon|0 fnt",
        "|faint|p1a: Glaceon",
        "|-damage|p2a: Dragonite|0 fnt|[from] Recoil",
        "|faint|p2a: Dragonite",
        "|win|Bob",
    ])
    f = R.commentary_facts(recap)
    recoil_play = next(p for p in f["plays"] if p["victim"] == "Dragonite")
    assert recoil_play["attacker"] is None
    assert "recoil" in (recoil_play["cause"] or ""), recoil_play


def test_chip_annotated_on_ko():
    # Toxic chip wears Glaceon down before the direct KO — the play should carry
    # a chip_pct so the recap can say the poison put it in range.
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p2a: Dragonite|Toxic|p1a: Glaceon",
        "|-status|p1a: Glaceon|tox",
        "|turn|2",
        "|-damage|p1a: Glaceon|84/100 tox|[from] psn",
        "|turn|3",
        "|-damage|p1a: Glaceon|63/100 tox|[from] psn",
        "|turn|4",
        "|move|p2a: Dragonite|Earthquake|p1a: Glaceon",
        "|-damage|p1a: Glaceon|0 fnt",
        "|faint|p1a: Glaceon",
        "|win|Bob",
    ])
    f = R.commentary_facts(recap)
    ko = next(p for p in f["plays"] if p["victim"] == "Glaceon")
    assert ko["chip_pct"] >= 15, ko


def test_pivot_counts():
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p2a: Dragonite|U-turn|p1a: Glaceon",
        "|-damage|p1a: Glaceon|80/100",
        "|switch|p2a: Pikachu|Pikachu, F|100/100",
        "|turn|2",
        "|switch|p2a: Dragonite|Dragonite, M|100/100",
        "|turn|3",
        "|move|p2a: Dragonite|U-turn|p1a: Glaceon",
        "|-damage|p1a: Glaceon|60/100",
        "|turn|4",
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|0 fnt",
        "|faint|p2a: Dragonite",
        "|win|Alice",
    ])
    f = R.commentary_facts(recap)
    piv = f["pivots"].get(f["loser"])
    assert piv and piv["count"] == 2 and piv["top_pivoter"] == "Dragonite", f["pivots"]


def test_expected_misses_from_accuracy_table():
    # Five Stone Edges (80% acc) -> expected misses 5 * 0.2 = 1.0
    lines = list(BASE)
    lines.append("|turn|1")
    for _ in range(5):
        lines.append("|move|p2a: Dragonite|Stone Edge|p1a: Glaceon")
        lines.append("|-damage|p1a: Glaceon|90/100")
    lines += [
        "|move|p1a: Glaceon|Ice Beam|p2a: Dragonite",
        "|-damage|p2a: Dragonite|0 fnt",
        "|faint|p2a: Dragonite",
        "|win|Alice",
    ]
    f = R.commentary_facts(_recap(lines))
    assert f["luck_summary"][f["loser"]]["expected_misses"] == 1.0


def test_speed_read_flagged_with_guards():
    smap = {"Slowpoke": 15, "Ninjask": 160, "Glaceon": 65, "Dragonite": 80}
    lines = [
        "|player|p1|Alice|cheryl|", "|player|p2|Bob|trainer.png|",
        "|poke|p1|Slowpoke, F|", "|poke|p2|Ninjask, M|", "|start",
        "|switch|p1a: Slowpoke|Slowpoke, F|100/100",
        "|switch|p2a: Ninjask|Ninjask, M|100/100",
        "|turn|1",
        "|move|p1a: Slowpoke|Water Gun|p2a: Ninjask",
        "|-damage|p2a: Ninjask|70/100",
        "|move|p2a: Ninjask|Hyper Beam|p1a: Slowpoke",
        "|-damage|p1a: Slowpoke|0 fnt",
        "|faint|p1a: Slowpoke",
        "|win|Bob",
    ]
    f = R.commentary_facts(_recap(lines), speed_map=smap)
    assert f["speed_reads"], "Slowpoke outspeeding Ninjask must be flagged"
    assert f["speed_reads"][0]["mon"] == "Slowpoke"

    # Same order under Tailwind: the read must be suppressed (tainted turn).
    tw = lines[:7] + [
        "|move|p2a: Ninjask|Tailwind|p2a: Ninjask",
        "|-sidestart|p2: Bob|move: Tailwind",
        "|turn|2",
    ] + [ln.replace("|turn|1", "|turn|2") for ln in lines[7:]]
    f2 = R.commentary_facts(_recap(tw), speed_map=smap)
    assert f2["speed_reads"] == [], f2["speed_reads"]


def test_recap_json_serializable_and_roundtrip_safe():
    # The import flow json.dumps(recap) inside a silent try/except — a
    # non-serializable key (e.g. tuple) kills the ENTIRE recap while stats
    # still record. This is exactly the "stats but no recap" failure.
    import json
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p2a: Dragonite|U-turn|p1a: Glaceon",
        "|-damage|p1a: Glaceon|80/100",
        "|switch|p2a: Pikachu|Pikachu, F|100/100",
        "|turn|2",
        "|move|p1a: Glaceon|Ice Beam|p2a: Pikachu",
        "|-damage|p2a: Pikachu|0 fnt",
        "|faint|p2a: Pikachu",
        "|win|Alice",
    ])
    s = json.dumps(recap)  # must not raise
    # commentary_facts must also work on a recap re-loaded from stored JSON
    # (int dict keys become strings there).
    reloaded = json.loads(s)
    f1 = R.commentary_facts(recap, speed_map={"Glaceon": 65, "Dragonite": 80})
    f2 = R.commentary_facts(reloaded, speed_map={"Glaceon": 65, "Dragonite": 80})
    assert f1["score"] == f2["score"]
    assert f1["pivots"] == f2["pivots"]
    assert f1["luck_summary"] == f2["luck_summary"]


def test_discord_header_score_matches_mons_downed(app_mod):
    # Final Gambit self-KO: Bob's mon went down, so Alice wins 1-0. The Discord
    # header must use the same mons-downed convention as the commentary body —
    # never "def. ... 0–0" (KOs-scored) beside a body saying 1-0.
    recap = _recap(BASE + [
        "|turn|1",
        "|move|p2a: Dragonite|Final Gambit|p1a: Glaceon",
        "|-damage|p1a: Glaceon|1/100",
        "|faint|p2a: Dragonite",
        "|win|Alice",
    ])
    msg = app_mod.build_discord_recap_message(recap, "Alice", "Bob", None, "Test League")
    head = msg.split("\n")[1]
    assert "1–0" in head, head


def test_series_bits_for_bo3_context(app_mod):
    recap = _recap(BASE + [
        "|turn|1",
        "|-terastallize|p2a: Dragonite|Flying",
        "|move|p2a: Dragonite|Tera Blast|p1a: Glaceon",
        "|-damage|p1a: Glaceon|0 fnt",
        "|faint|p1a: Glaceon",
        "|win|Bob",
    ])
    bits = app_mod._series_bits(recap)
    assert bits["winner"] == "Bob"
    assert any(t["mon"] == "Dragonite" and t["type"] == "Flying" for t in bits["teras"])
    assert "Bob" in bits["leads"] and "Alice" in bits["leads"]


def test_timeline_is_turn_sorted_and_crits_mattered_only():
    import os
    fx = os.path.join(os.path.dirname(__file__), "fixtures", "yuricup_s9_58.log")
    if not os.path.exists(fx):
        import pytest
        pytest.skip("fixture missing")
    recap = _recap([open(fx, encoding="utf-8").read()])
    f = R.commentary_facts(recap)
    turns = [e["turn"] for e in f["timeline"]]
    assert turns == sorted(turns), "timeline must be chronological"
    assert all(e["turn"] is not None for e in f["timeline"])
    assert all(c["mattered"] is True for c in f["crits"]), \
        "facts crits must be pre-filtered to mattered-only"
    # every KO in plays (up to the timeline cap) appears as a timeline event
    ko_events = [e for e in f["timeline"] if "KO'd" in e["event"]]
    assert ko_events, "timeline must contain the KOs"
