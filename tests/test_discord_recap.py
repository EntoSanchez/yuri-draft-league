from app import build_discord_recap_message


def _fake_recap():
    return {
        "totals": {"home": {"ko": 4}, "away": {"ko": 2}, "winner": "HOME"},
        "commentary": {
            "summary": "Gardevoir snowballed and swept.",
            "plays": [],
            "source": "template",
        },
        "stars": [
            {
                "side": "HOME",
                "mon": {"name": "Mega Swampert"},
                "line": "2 KO · survived",
            },
            {"side": "AWAY", "mon": {"name": "Rillaboom"}, "line": "2 KO · fainted"},
        ],
        "home": {"name": "Caelyn"},
        "away": {"name": "Trey"},
    }


def test_discord_recap_message_has_score_summary_stars_link():
    msg = build_discord_recap_message(
        _fake_recap(), "Caelyn", "Trey", "https://ydl.example/match/108", "Yuri Cup"
    )
    assert "Caelyn" in msg and "Trey" in msg
    assert "snowballed" in msg
    assert "Mega Swampert" in msg
    assert "https://ydl.example/match/108" in msg
    assert "4" in msg and "2" in msg


def test_discord_recap_message_no_link_when_url_empty():
    msg = build_discord_recap_message(_fake_recap(), "Caelyn", "Trey", "", "Yuri Cup")
    assert "http" not in msg  # gracefully omit link


def test_clean_truncate_never_cuts_mid_word():
    from app import _clean_truncate
    text = ("First sentence here. Second sentence goes on. Third sentence keeps "
            "going with more words that will run past the limit eventually somewhere.")
    out = _clean_truncate(text, 60)
    # must not end mid-word: ends on a sentence period or an ellipsis
    assert out.rstrip()[-1] in ".…"
    assert len(out) <= 62  # limit + ellipsis slack
    # short text is returned unchanged
    assert _clean_truncate("short", 100) == "short"


def test_discord_recap_summary_not_truncated_at_600():
    # A ~660-char AI summary must appear IN FULL (old bug cut it at 600 mid-word).
    long_summary = (
        "The match erupted when Rillaboom came out swinging, ripping out Mr. Mime "
        "with a swift U-turn and then sweeping away Politoed with a super-effective "
        "Grassy Glide. From there, Archaludon began to snowball, its defense and "
        "special-attack stages climbing, letting it survive hits and land a decisive "
        "critical Electro Shot that felled Rillaboom, a hit a normal strike would not "
        "have finished. The turning point handed the lead over as Mega Swampert closed "
        "out the win. By the end, it was a clear victory."
    )
    rec = {
        "totals": {"home": {"ko": 4}, "away": {"ko": 1}, "winner": "HOME"},
        "commentary": {"summary": long_summary, "plays": [], "source": "ai"},
        "stars": [{"side": "HOME", "mon": {"name": "Archaludon"}, "line": "2 KO"}],
        "home": {"name": "A"}, "away": {"name": "B"},
    }
    from app import build_discord_recap_message
    msg = build_discord_recap_message(rec, "A", "B", "https://x/match/1", "L")
    assert "By the end, it was a clear victory." in msg  # full summary present
    assert len(msg) <= 2000  # within Discord's per-message limit
