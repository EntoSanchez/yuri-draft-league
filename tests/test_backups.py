def test_create_lists_and_restore_roundtrip(app_mod):
    # baseline state
    with app_mod.get_db() as db:
        db.execute("DELETE FROM draft_tiers")
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('Baseline', 7)")
    fn = app_mod.create_db_backup("manual")
    assert fn in app_mod.list_db_backups()

    # mutate after backup
    with app_mod.get_db() as db:
        db.execute("INSERT INTO draft_tiers (name, points) VALUES ('AfterBackup', 9)")

    app_mod.restore_db_backup(fn)               # roll back to the snapshot

    with app_mod.get_db() as db:
        names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers")}
    assert names == {"Baseline"}                # AfterBackup gone


def test_restore_makes_pre_restore_backup(app_mod):
    before = len(app_mod.list_db_backups())
    fn = app_mod.create_db_backup("a")
    app_mod.restore_db_backup(fn)
    assert len(app_mod.list_db_backups()) >= before + 2   # the 'a' backup + a pre-restore one


def test_restore_missing_raises(app_mod):
    import pytest
    with pytest.raises(ValueError):
        app_mod.restore_db_backup("does-not-exist.db")
