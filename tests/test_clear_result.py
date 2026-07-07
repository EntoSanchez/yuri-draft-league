"""Admin 'Clear result' un-records a match: nulls both scores AND removes any
parsed games (so a later replay import can't silently re-record it)."""


def _mk_match_games(db):
    db.execute("""CREATE TABLE IF NOT EXISTS match_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER NOT NULL,
        winner_coach_id INTEGER)""")


def test_clear_result_nulls_scores_and_deletes_games(client, app_mod):
    with app_mod.get_db() as db:
        _mk_match_games(db)
        db.execute('INSERT INTO schedule (id,week,pool,coach1_id,coach2_id,score1,score2) VALUES (99,1,"A",1,2,4,0)')
        db.execute('INSERT INTO match_games (schedule_id,winner_coach_id) VALUES (99,1)')
    client.post('/admin/schedule', data={'action': 'clear_result', 'match_id': '99'},
                headers={'X-CSRFToken': 'testtoken'})
    with app_mod.get_db() as db:
        row = db.execute('SELECT score1,score2 FROM schedule WHERE id=99').fetchone()
        games = db.execute('SELECT COUNT(*) FROM match_games WHERE schedule_id=99').fetchone()[0]
    assert row['score1'] is None and row['score2'] is None
    assert games == 0


def test_clear_result_leaves_other_matches_untouched(client, app_mod):
    with app_mod.get_db() as db:
        _mk_match_games(db)
        db.execute('INSERT INTO schedule (id,week,pool,coach1_id,coach2_id,score1,score2) VALUES (99,1,"A",1,2,4,0)')
        db.execute('INSERT INTO schedule (id,week,pool,coach1_id,coach2_id,score1,score2) VALUES (100,1,"A",3,4,5,2)')
    client.post('/admin/schedule', data={'action': 'clear_result', 'match_id': '99'},
                headers={'X-CSRFToken': 'testtoken'})
    with app_mod.get_db() as db:
        other = db.execute('SELECT score1,score2 FROM schedule WHERE id=100').fetchone()
    assert other['score1'] == 5 and other['score2'] == 2  # untouched
