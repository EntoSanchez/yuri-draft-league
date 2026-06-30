import importlib
import os
import sys

import pytest
from flask.testing import FlaskClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TEST_CSRF_TOKEN = "testtoken"


class CSRFClient(FlaskClient):
    """Test client that sends a real CSRF token on every POST.

    The session is seeded with _csrf_token = TEST_CSRF_TOKEN (see the client
    fixture); app.csrf_token() preserves a pre-set session token, so injecting
    the matching X-CSRFToken header lets POSTs pass real CSRF validation.
    """

    def post(self, *args, **kwargs):
        headers = kwargs.pop("headers", None) or {}
        headers.setdefault("X-CSRFToken", TEST_CSRF_TOKEN)
        kwargs["headers"] = headers
        return super().post(*args, **kwargs)


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "test_league.db")


@pytest.fixture()
def app_mod(db_path, monkeypatch):
    # Point both init_db and app at the temp DB BEFORE importing them.
    monkeypatch.setenv("DB_PATH", db_path)
    import init_db
    importlib.reload(init_db)
    init_db.DB_PATH = db_path
    init_db.init_db()  # create base schema in the temp DB
    import app as app_module
    importlib.reload(app_module)  # re-imports with DB_PATH set; runs _migrate_db()
    app_module.DB_PATH = db_path
    app_module.app.config["TESTING"] = True
    return app_module


@pytest.fixture()
def client(app_mod):
    app_mod.app.test_client_class = CSRFClient
    c = app_mod.app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["role"] = "admin"
        s["_csrf_token"] = TEST_CSRF_TOKEN
    return c
