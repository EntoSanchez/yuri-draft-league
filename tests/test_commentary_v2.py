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
