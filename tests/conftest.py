import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


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
    c = app_mod.app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["role"] = "admin"
    return c
