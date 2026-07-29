"""Regression: pool-scoped standings must count a coach's cross-pool matches.

get_standings(pool) used to skip any schedule row where the OPPONENT wasn't in
the same pool — after mid-season team additions (or a mis-set coach pool), a
coach's own win vanished from their record and KO differential while the
schedule page still showed the score.
"""


def _setup(db):
    db.execute(
        "INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (38,'Robbie','Squirtles','A')"
    )
    db.execute(
        "INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (28,'Tyler','Bruxish','B')"
    )
    db.execute(
        "INSERT INTO coaches (id, coach_name, team_name, pool) VALUES (5,'Ann','Annies','A')"
    )
    # Cross-pool: Robbie (A) beats Tyler (B) 2-0
    db.execute(
        "INSERT INTO schedule (week, coach1_id, coach2_id, score1, score2, pool) "
        "VALUES (1, 38, 28, 2, 0, 'A')"
    )
    # Same-pool: Robbie loses to Ann 0-2
    db.execute(
        "INSERT INTO schedule (week, coach1_id, coach2_id, score1, score2, pool) "
        "VALUES (2, 5, 38, 2, 0, 'A')"
    )


def _row(rows, cid):
    return next(r for r in rows if r["coach"]["id"] == cid)


def test_pool_standings_include_cross_pool_matches(app_mod):
    with app_mod.get_db() as db:
        _setup(db)
    a = app_mod.get_standings("A")
    robbie = _row(a, 38)
    # 2 game-wins vs Tyler + 2 game-losses vs Ann — the win must NOT vanish
    # just because Tyler is in pool B.
    assert (robbie["W"], robbie["L"]) == (2, 2), (robbie["W"], robbie["L"])
    assert robbie["weeks"].get(1) == "W"

    b = app_mod.get_standings("B")
    tyler = _row(b, 28)
    assert (tyler["W"], tyler["L"]) == (0, 2), (tyler["W"], tyler["L"])
    assert tyler["weeks"].get(1) == "L"


def test_overall_standings_unchanged(app_mod):
    with app_mod.get_db() as db:
        _setup(db)
    allr = app_mod.get_standings(None)
    assert (_row(allr, 38)["W"], _row(allr, 38)["L"]) == (2, 2)
    assert (_row(allr, 28)["W"], _row(allr, 28)["L"]) == (0, 2)
    assert (_row(allr, 5)["W"], _row(allr, 5)["L"]) == (2, 0)
