"""
update_megas.py
Set the official single Mega ability for the new Pokémon Champions / Legends Z-A
megas, per the reveal at insider-gaming.com/new-pokemon-champions-mega-abilities.

Megas have exactly one ability, so ability2/ability3 are cleared.

DB selection (highest priority first): --db arg, DB_PATH env var, league.db next
to this file. On PythonAnywhere pass the nested DB path:
  python update_megas.py --db /home/zcs55397/yuri-draft-league/yuri-draft-league/league.db
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

# name -> official mega ability (Pokémon Champions Regulation M-B)
MEGA_ABILITIES = {
    "Mega Raichu X":   "Electric Surge",
    "Mega Raichu Y":   "No Guard",
    "Mega Staraptor":  "Contrary",
    "Mega Scolipede":  "Shell Armor",
    "Mega Scrafty":    "Intimidate",
    "Mega Eelektross": "Eelevate",
    "Mega Pyroar":     "Fire Mane",
    "Mega Malamar":    "Contrary",
    "Mega Barbaracle": "Tough Claws",
    "Mega Dragalge":   "Regenerator",
    "Mega Falinks":    "Defiant",
}

print(f"DB_PATH = {DB_PATH}", flush=True)
if not os.path.exists(DB_PATH):
    raise SystemExit(f"ERROR: database not found at {DB_PATH} (pass the correct --db).")

db = sqlite3.connect(DB_PATH)
updated, missing = 0, []
for name, abil in MEGA_ABILITIES.items():
    cur = db.execute(
        "UPDATE draft_tiers SET ability1=?, ability2=NULL, ability3=NULL "
        "WHERE name=? AND is_mega=1",
        (abil, name),
    )
    if cur.rowcount:
        updated += cur.rowcount
    else:
        missing.append(name)
db.commit()
db.close()

print(f"OK  Updated {updated} mega abilities.")
if missing:
    print("Not found (name mismatch?):", missing)
