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
