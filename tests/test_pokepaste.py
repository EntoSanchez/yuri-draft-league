"""The /api/pokepaste proxy must POST to pokepast.es/create and return the
redirected paste URL (pokepast.es has no JSON API — the old /api/new endpoint
was dead, producing the export error)."""


class _FakeResp:
    def __init__(self, url):
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return self._url


def test_pokepaste_posts_to_create_and_returns_url(client, app_mod, monkeypatch):
    import urllib.request
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return _FakeResp("https://pokepast.es/abc123def456")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    resp = client.post("/api/pokepaste",
                       json={"paste": "Garchomp @ Life Orb\n- Earthquake",
                             "title": "My Team", "author": "Coach"})
    assert resp.status_code == 200
    assert resp.get_json()["url"] == "https://pokepast.es/abc123def456"
    assert captured["url"] == "https://pokepast.es/create"      # not the dead /api/new
    assert b"Garchomp" in captured["data"]                       # paste was forwarded


def test_pokepaste_rejects_empty_paste(client):
    resp = client.post("/api/pokepaste", json={"paste": "   "})
    assert resp.status_code == 400


def test_pokepaste_errors_if_no_redirect(client, app_mod, monkeypatch):
    import urllib.request
    # Simulate a failure where we stay on /create (no paste created).
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp("https://pokepast.es/create"))
    resp = client.post("/api/pokepaste", json={"paste": "Garchomp\n- Earthquake"})
    assert resp.status_code == 502
