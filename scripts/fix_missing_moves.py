"""
One-time migration: add moves that update_moves.py misses due to scraper coverage gaps.

  Final Gambit   -> 18 known learners (pokemondb infocard approach catches only 2)
  Rising Voltage -> all Electric-type pokemon (TM move, pokemondb only shows Raging Bolt)

Run:
    python scripts/fix_missing_moves.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "league.db"

FINAL_GAMBIT_LEARNERS = [
    "Mankey", "Primeape", "Annihilape",
    "Starly", "Staravia", "Staraptor",
    "Riolu", "Lucario",
    "Basculin",
    "Veluza",
    "Diglett", "Dugtrio", "Alolan Diglett", "Alolan Dugtrio",
    "Seviper",
    "Squawkabilly",
    "Wiglett", "Wugtrio",
]


def add_move_to_names(conn, move, names):
    updated = 0
    for name in names:
        row = conn.execute(
            "SELECT moves FROM draft_tiers WHERE name=? AND is_banned != 1", (name,)
        ).fetchone()
        if not row:
            continue
        existing = row[0] or ""
        if move.lower() in existing.lower():
            continue
        new_moves = existing + "|" + move if existing else move
        conn.execute("UPDATE draft_tiers SET moves=? WHERE name=?", (new_moves, name))
        updated += 1
    return updated


def add_move_to_types(conn, move, type1, type2=None):
    if type2:
        rows = conn.execute(
            "SELECT name, moves FROM draft_tiers WHERE is_banned != 1 "
            "AND (type1=? OR type2=? OR type1=? OR type2=?)",
            (type1, type1, type2, type2),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT name, moves FROM draft_tiers WHERE is_banned != 1 "
            "AND (type1=? OR type2=?)",
            (type1, type1),
        ).fetchall()
    updated = 0
    for name, existing_moves in rows:
        existing = existing_moves or ""
        if move.lower() in existing.lower():
            continue
        new_moves = existing + "|" + move if existing else move
        conn.execute("UPDATE draft_tiers SET moves=? WHERE name=?", (new_moves, name))
        updated += 1
    return updated


def main():
    import sys
    db_path = str(DB_PATH)
    for i, arg in enumerate(sys.argv):
        if arg == "--db" and i + 1 < len(sys.argv):
            db_path = sys.argv[i + 1]
    print("Using DB: " + db_path)

    conn = sqlite3.connect(db_path)

    n = add_move_to_names(conn, "Final Gambit", FINAL_GAMBIT_LEARNERS)
    print("Final Gambit: added to %d pokemon" % n)

    n = add_move_to_types(conn, "Rising Voltage", "Electric")
    print("Rising Voltage: added to %d Electric-type pokemon" % n)

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
