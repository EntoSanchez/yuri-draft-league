"""
update_types.py
Backfill draft_tiers.type1/type2 (left empty for many forms) from the
authoritative `pokedex` table, using the app's own name->slug resolution.

Only fills rows whose type1 is empty/NULL — never overwrites an existing type.

DB selection (highest priority first): --db arg, DB_PATH env var, league.db next
to this file. On PythonAnywhere pass the nested DB path:
  python update_types.py --db /home/zcs55397/yuri-draft-league/yuri-draft-league/league.db
"""
import argparse
import os
import pathlib
import sqlite3

_HERE = pathlib.Path(__file__).parent
_p = argparse.ArgumentParser()
_p.add_argument("--db", help="Path to league.db (overrides DB_PATH env var).")
_a, _ = _p.parse_known_args()
DB_PATH = _a.db or os.environ.get("DB_PATH") or str(_HERE / "league.db")

if not os.path.exists(DB_PATH):
    raise SystemExit(f"ERROR: database not found at {DB_PATH} (pass the correct --db).")

# Make sure the app (imported below for its slug logic) targets the same DB.
os.environ["DB_PATH"] = DB_PATH
import app  # noqa: E402  — provides _name_to_slug + the form-alias tables

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
pokedex = {r["pokeapi_name"]: r for r in db.execute("SELECT pokeapi_name, type1, type2 FROM pokedex")}

rows = db.execute("SELECT id, name FROM draft_tiers WHERE type1 IS NULL OR type1=''").fetchall()
print(f"DB_PATH = {DB_PATH}\n{len(rows)} rows with empty type1 to resolve ...", flush=True)

updated, not_found = 0, []
for r in rows:
    name = r["name"]
    # Arceus plate forms aren't separate pokedex entries — the form name IS the type.
    if name.startswith("Arceus-"):
        db.execute(
            "UPDATE draft_tiers SET type1=?, type2=? WHERE id=?",
            (name.split("-", 1)[1], "", r["id"]),
        )
        updated += 1
        continue
    pd = None
    for slug in app._name_to_slug(name):
        if slug in pokedex and pokedex[slug]["type1"]:
            pd = pokedex[slug]
            break
    if pd:
        db.execute(
            "UPDATE draft_tiers SET type1=?, type2=? WHERE id=?",
            (pd["type1"], pd["type2"] or "", r["id"]),
        )
        updated += 1
    else:
        not_found.append(r["name"])

db.commit()
db.close()
print(f"OK  Updated {updated} rows.  Unresolved: {len(not_found)}")
if not_found:
    for n in not_found:
        print(f"  - {n}")
