"""Admin 'Send test message' button for the Discord webhook."""


def test_test_webhook_no_url_warns(client):
    r = client.post('/admin/test_webhook', headers={'X-CSRFToken': 'testtoken'},
                    follow_redirects=True)
    assert r.status_code == 200  # redirects back to settings, no crash


def test_test_button_shown_only_when_configured(client, app_mod):
    # not shown before a webhook is saved
    assert 'Send test message' not in client.get('/admin/settings').get_data(as_text=True)
    with app_mod.get_db() as db:
        db.execute("INSERT OR REPLACE INTO league_settings (key,value) "
                   "VALUES ('discord_webhook_url','https://discord.com/api/webhooks/1/x')")
    html = client.get('/admin/settings').get_data(as_text=True)
    assert 'Send test message' in html and '/admin/test_webhook' in html


def test_post_discord_returns_bool(app_mod):
    assert app_mod.post_discord('', 'x') is False
    assert app_mod.post_discord('https://invalid.invalid/nope', 'x') is False
