"""Match-recap commentary: the deterministic template floor (build_commentary)
turns a finished recap into a narrative summary + KO-by-KO play-by-play."""
import replay_utils as R


def _recap(url):
    return R.build_recap(R.parse_log_recap(R.fetch_replay(url)["log"]))


def test_commentary_shape_and_source():
    rc = _recap("https://replay.pokemonshowdown.com/gen9nationaldexubers-2501799475")
    c = R.build_commentary(rc)
    assert set(c.keys()) == {"summary", "plays", "source"}
    assert c["source"] == "template"
    assert isinstance(c["summary"], str) and c["summary"]
    assert isinstance(c["plays"], list)


def test_commentary_one_play_per_ko_and_names_real_species():
    rc = _recap("https://replay.pokemonshowdown.com/gen9nationaldexubers-2501799475")
    c = R.build_commentary(rc)
    # one play line per KO in the koLog
    assert len(c["plays"]) == len(rc["koLog"])
    joined = c["summary"] + " " + " ".join(c["plays"])
    # nickname resolved to species; no phantom disguise names
    assert "Blaziken" in joined and "Chicken Jockey" not in joined
    # the comeback (loser led, winner clawed back) is narrated
    assert "clawed all the way back" in c["summary"]


def test_commentary_super_effective_flagged():
    rc = _recap("https://replay.pokemonshowdown.com/gen9nationaldexubers-2501799475")
    c = R.build_commentary(rc)
    assert any("super effective" in line for line in c["plays"])


def test_commentary_handles_empty_kolog():
    # A recap with no KOs must not crash and yields a bare summary, no plays.
    fake = {"home": {"name": "A"}, "away": {"name": "B"},
            "totals": {"home": {"ko": 0}, "away": {"ko": 0}, "winner": "HOME"},
            "koLog": [], "momentum": [], "stars": [], "facts": {"turns": 0}}
    c = R.build_commentary(fake)
    assert c["plays"] == []
    assert "A" in c["summary"] and "B" in c["summary"]


def test_coerce_play_handles_dicts_and_strings():
    import importlib.util
    spec = importlib.util.spec_from_file_location("app", "app.py")
    # app import has side effects (DB); use the function via a light import guard
    import app as A  # conftest already sets DATABASE for the suite
    assert A._coerce_play("  hello  ") == "hello"
    assert A._coerce_play({"text": "Pika KOs Chomp"}) == "Pika KOs Chomp"
    assert A._coerce_play({"play": "x"}) == "x"
    assert A._coerce_play({"nope": 1}) == ""  # unknown dict -> empty (dropped by caller)


def test_ai_commentary_no_key_returns_none(app_mod):
    rc = _recap("https://replay.pokemonshowdown.com/gen9nationaldexubers-2501799475")
    assert app_mod.ai_commentary(rc, "") is None
    assert app_mod.ai_commentary(rc, None) is None
