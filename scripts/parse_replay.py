#!/usr/bin/env python3
"""
Parse Pokémon Showdown replays and import match stats into league.db.

Usage (one match = one or more game URLs):
    python scripts/parse_replay.py <url> [<url2> <url3>]
    python scripts/parse_replay.py --week N <url> [...]
    python scripts/parse_replay.py --dry-run <url>

Coach Showdown usernames must be set in the admin panel
(Edit Coach → Showdown Name field) before running this script.
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from replay_utils import fetch_replay, parse_log, resolve_poke_name, remap_dict

DEFAULT_DB = os.environ.get("DB_PATH") or str(PROJECT_ROOT / "league.db")


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _roster_names(db, coach_id: int) -> list:
    rows = db.execute(
        "SELECT pokemon_name FROM pokemon_roster WHERE coach_id=?", (coach_id,)
    ).fetchall()
    return [r["pokemon_name"] for r in rows]


def resolve_coaches(db, p1_username: str, p2_username: str):
    rows = db.execute("SELECT * FROM coaches").fetchall()
    by_showdown = {(r["showdown_name"] or "").lower().strip(): dict(r)
                   for r in rows if r["showdown_name"]}

    def _find(username):
        coach = by_showdown.get(username.lower().strip())
        if coach:
            return coach
        for sn, c in by_showdown.items():
            if username.lower() in sn or sn in username.lower():
                return c
        return None

    return _find(p1_username), _find(p2_username)


def find_schedule(db, cid1: int, cid2: int, week: int = None):
    rows = db.execute(
        "SELECT * FROM schedule WHERE "
        "(coach1_id=? AND coach2_id=?) OR (coach1_id=? AND coach2_id=?)",
        (cid1, cid2, cid2, cid1),
    ).fetchall()
    if not rows:
        return None
    if week is not None:
        rows = [r for r in rows if r["week"] == week]
    if len(rows) == 1:
        return dict(rows[0])
    print("Multiple schedule entries found:")
    for i, r in enumerate(rows):
        print(f"  [{i}] Week {r['week']} (id={r['id']})")
    choice = input("Pick entry index: ").strip()
    return dict(rows[int(choice)])


def next_game_number(db, schedule_id: int) -> int:
    row = db.execute(
        "SELECT MAX(game_number) as mx FROM match_games WHERE schedule_id=?",
        (schedule_id,),
    ).fetchone()
    return (row["mx"] or 0) + 1


def upsert_game_stats(db, schedule_id: int, game_number: int, replay_url: str,
                      parsed: dict, c1: dict, c2: dict, dry_run: bool = False):
    by_pkey = {}
    for pkey in ("p1", "p2"):
        uname = parsed[pkey]["username"].lower()
        if (c1.get("showdown_name") or "").lower() == uname:
            by_pkey[pkey] = c1
        elif (c2.get("showdown_name") or "").lower() == uname:
            by_pkey[pkey] = c2
        else:
            by_pkey[pkey] = c1 if pkey == "p1" else c2

    winner_pkey = parsed["winner_player"]
    winner_cid = by_pkey[winner_pkey]["id"] if winner_pkey else None

    name_maps = {}
    for pkey in ("p1", "p2"):
        cid = by_pkey[pkey]["id"]
        roster = _roster_names(db, cid)
        all_raw = (set(parsed[pkey]["pokemon_used"])
                   | set(parsed["kills"][pkey])
                   | set(parsed["deaths"][pkey]))
        nmap = {}
        for raw in all_raw:
            canon = resolve_poke_name(raw, roster)
            if canon != raw:
                print(f"  [name] {by_pkey[pkey]['coach_name']}: '{raw}' → '{canon}'")
            nmap[raw] = canon
        name_maps[pkey] = nmap

    resolved = {}
    for pkey in ("p1", "p2"):
        nmap = name_maps[pkey]
        resolved[pkey] = {
            "used":   sorted({nmap.get(m, m) for m in parsed[pkey]["pokemon_used"]}),
            "kills":  remap_dict(parsed["kills"][pkey],  nmap),
            "deaths": remap_dict(parsed["deaths"][pkey], nmap),
        }

    print(f"\n  Game {game_number}: {parsed['p1']['username']} vs {parsed['p2']['username']}")
    print(f"  Winner: {parsed[winner_pkey]['username'] if winner_pkey else '?'}")
    for pkey in ("p1", "p2"):
        coach = by_pkey[pkey]
        r = resolved[pkey]
        print(f"  {pkey} → {coach['coach_name']} ({coach['team_name']})")
        print(f"       used: {', '.join(r['used'])}")
        for mon in sorted(set(r["used"]) | set(r["kills"]) | set(r["deaths"])):
            ko  = r["kills"].get(mon, 0)
            fnt = r["deaths"].get(mon, 0)
            if ko or fnt:
                print(f"       {mon}: {ko}KO {fnt}fnt")

    if dry_run:
        print("  [dry-run] no DB changes")
        return

    existing = db.execute(
        "SELECT id FROM match_games WHERE schedule_id=? AND game_number=?",
        (schedule_id, game_number),
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE match_games SET replay_url=?, winner_coach_id=? WHERE id=?",
            (replay_url, winner_cid, existing["id"]),
        )
        game_id = existing["id"]
        db.execute("DELETE FROM match_lineups WHERE game_id=?", (game_id,))
        db.execute("DELETE FROM match_stats WHERE game_id=?", (game_id,))
    else:
        db.execute(
            "INSERT INTO match_games (schedule_id, game_number, replay_url, winner_coach_id) "
            "VALUES (?,?,?,?)",
            (schedule_id, game_number, replay_url, winner_cid),
        )
        game_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]

    for pkey in ("p1", "p2"):
        cid = by_pkey[pkey]["id"]
        r = resolved[pkey]
        for mon in sorted(set(r["used"]) | set(r["kills"]) | set(r["deaths"])):
            db.execute(
                "INSERT OR IGNORE INTO match_lineups (game_id, coach_id, pokemon_name) "
                "VALUES (?,?,?)",
                (game_id, cid, mon),
            )
            db.execute(
                "INSERT INTO match_stats "
                "(schedule_id, game_id, coach_id, pokemon_name, kills, deaths) "
                "VALUES (?,?,?,?,?,?)",
                (schedule_id, game_id, cid, mon,
                 float(r["kills"].get(mon, 0)), float(r["deaths"].get(mon, 0))),
            )
    db.commit()


def update_schedule_score(db, schedule_id: int, dry_run: bool = False):
    sched = db.execute("SELECT * FROM schedule WHERE id=?", (schedule_id,)).fetchone()
    if not sched:
        return
    games = db.execute(
        "SELECT winner_coach_id FROM match_games "
        "WHERE schedule_id=? AND winner_coach_id IS NOT NULL",
        (schedule_id,),
    ).fetchall()
    s1 = sum(1 for g in games if g["winner_coach_id"] == sched["coach1_id"])
    s2 = sum(1 for g in games if g["winner_coach_id"] == sched["coach2_id"])
    print(f"\n  Schedule score → {s1}-{s2}")
    if not dry_run:
        db.execute(
            "UPDATE schedule SET score1=?, score2=? WHERE id=?",
            (float(s1), float(s2), schedule_id),
        )
        db.commit()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Import Pokémon Showdown replay stats into league.db."
    )
    parser.add_argument("urls", nargs="+", help="Replay URL(s) for a single match")
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db", default=DEFAULT_DB)
    args = parser.parse_args()

    parsed_games = []
    for url in args.urls:
        print(f"Fetching {url} ...")
        try:
            data = fetch_replay(url)
        except Exception as e:
            print(f"  [ERROR] {e}")
            sys.exit(1)
        parsed_games.append((url, parse_log(data["log"])))

    p1 = parsed_games[0][1]["p1"]["username"].lower()
    p2 = parsed_games[0][1]["p2"]["username"].lower()
    for _, g in parsed_games[1:]:
        if {g["p1"]["username"].lower(), g["p2"]["username"].lower()} != {p1, p2}:
            print("[ERROR] Replays are not all from the same matchup.")
            sys.exit(1)

    db = get_db(args.db)
    c1, c2 = resolve_coaches(db, p1, p2)
    missing = [u for u, c in [(p1, c1), (p2, c2)] if c is None]
    if missing:
        print(f"[ERROR] No coach found for: {', '.join(missing)}")
        print("Set Showdown Name in the admin panel and try again.")
        for r in db.execute("SELECT coach_name, showdown_name FROM coaches").fetchall():
            print(f"  {r['coach_name']}: {r['showdown_name'] or '(not set)'}")
        sys.exit(1)

    print(f"\nCoaches: {c1['coach_name']} vs {c2['coach_name']}")
    sched = find_schedule(db, c1["id"], c2["id"], week=args.week)
    if not sched:
        print("[ERROR] No schedule entry found.")
        sys.exit(1)
    print(f"Schedule: week {sched['week']} (id={sched['id']})")

    start = next_game_number(db, sched["id"])
    for i, (url, parsed) in enumerate(parsed_games):
        upsert_game_stats(db, sched["id"], start + i, url, parsed, c1, c2,
                          dry_run=args.dry_run)

    update_schedule_score(db, sched["id"], dry_run=args.dry_run)
    print("\nDone.")


if __name__ == "__main__":
    main()
