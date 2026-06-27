"""
update_uber_slots.py
Fix ubers that were drafted into a regular tier slot because the old code didn't
recognize their "Uber Bronze/Silver/Gold/Platinum" tier_label (it compared against
the bare names). Re-slot any pick whose draft_tiers tier_label is an uber tier but
whose roster slot isn't "Uber 1"/"Uber 2" into the next free uber slot (max 2 per
coach). Updates pokemon_roster.tier and draft_picks.slot_name.

Run on prod after deploying the code fix, with the NESTED db path:
  python update_uber_slots.py --db /home/zcs55397/yuri-draft-league/yuri-draft-league/league.db
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

os.environ["DB_PATH"] = DB_PATH
import app  # noqa: E402  — provides _uber_named

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

# Which drafted names are uber-tier (by "Uber X" label OR by uber point value
# 27-30) and what their bare tier is.
uber_by_name = {}
for r in db.execute("SELECT name, tier_label, points FROM draft_tiers"):
    named = app._uber_named(r["tier_label"]) or app.UBER_POINTS.get(r["points"] or 0, "")
    if named:
        uber_by_name[r["name"]] = named

coach_ids = [r[0] for r in db.execute("SELECT DISTINCT coach_id FROM pokemon_roster")]
print(f"DB_PATH = {DB_PATH}\nScanning {len(coach_ids)} coach roster(s) ...", flush=True)

moved = 0
overflow = []
for cid in coach_ids:
    picks = db.execute(
        "SELECT id, pokemon_name, tier FROM pokemon_roster WHERE coach_id=? ORDER BY id",
        (cid,),
    ).fetchall()
    used_uber = sum(1 for p in picks if p["tier"] in ("Uber 1", "Uber 2"))
    for p in picks:
        if p["pokemon_name"] not in uber_by_name:
            continue
        if p["tier"] in ("Uber 1", "Uber 2"):
            continue  # already correctly slotted
        if used_uber >= 2:
            overflow.append((cid, p["pokemon_name"]))
            continue
        slot = "Uber 1" if used_uber == 0 else "Uber 2"
        used_uber += 1
        db.execute("UPDATE pokemon_roster SET tier=?, is_free_pick=0 WHERE id=?", (slot, p["id"]))
        db.execute(
            "UPDATE draft_picks SET slot_name=? WHERE coach_id=? AND pokemon_name=?",
            (slot, cid, p["pokemon_name"]),
        )
        moved += 1
        print(f"  coach {cid}: {p['pokemon_name']:18s} {p['tier']!r} -> {slot} ({uber_by_name[p['pokemon_name']]})", flush=True)

db.commit()
db.close()
print(f"\nOK  Re-slotted {moved} uber pick(s).")
if overflow:
    print(f"WARNING  {len(overflow)} uber pick(s) couldn't be slotted (coach already has 2 ubers):")
    for cid, nm in overflow:
        print(f"  - coach {cid}: {nm}")
