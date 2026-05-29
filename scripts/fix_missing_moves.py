"""
One-time migration: add moves that update_moves.py misses due to scraper coverage gaps.

  Final Gambit   → 18 known learners (pokemondb infocard approach catches only 2)
  Rising Voltage → all Electric-type pokemon (TM move, pokemondb only shows Raging Bolt)

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


def add_move_to_names(conn, move: str, names: list[str]) -> int:
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


def add_move_to_types(conn, move: str, type1: str, type2: str | None = None) -> int:
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
    conn = sqlite3.connect(DB_PATH)

    n = add_move_to_names(conn, "Final Gambit", FINAL_GAMBIT_LEARNERS)
    print(f"Final Gambit: added to {n} pokemon")

    n = add_move_to_types(conn, "Rising Voltage", "Electric")
    print(f"Rising Voltage: added to {n} Electric-type pokemon")

    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
