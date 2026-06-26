"""
update_mega_slots.py
Re-slot megas that were already drafted into the old "Mega" slot so they sit in
their real point-based slot instead: uber slot if costed at 27/28/29 pts,
otherwise Tier 1-5 (paid before free, overflow to Free Pick) — same logic a
fresh draft now uses.

Run on prod after deploying the code fix, and after the megas are costed:
  python update_mega_slots.py --db /home/zcs55397/yuri-draft-league/yuri-draft-league/league.db
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
import app  # noqa: E402 — _auto_slot, _mega_tier_label

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
settings = {r[0]: r[1] for r in db.execute("SELECT key, value FROM league_settings")}
mega_set = {r["name"] for r in db.execute("SELECT name FROM draft_tiers WHERE is_mega=1")}
coach_ids = [r[0] for r in db.execute("SELECT DISTINCT coach_id FROM pokemon_roster WHERE tier='Mega'")]

print(f"DB_PATH = {DB_PATH}\n{len(coach_ids)} coach(es) with megas in the old slot ...", flush=True)
total = 0
for cid in coach_ids:
    picks = db.execute(
        "SELECT id, pokemon_name, points, tier, is_free_pick FROM pokemon_roster "
        "WHERE coach_id=? ORDER BY id",
        (cid,),
    ).fetchall()
    # slots already occupied by this coach's NON-mega picks (they keep their slot)
    existing = [{"tier": p["tier"], "is_free_pick": p["is_free_pick"]}
                for p in picks if p["tier"] != "Mega"]
    uber_count = sum(1 for e in existing if e["tier"] in ("Uber 1", "Uber 2"))
    for p in picks:
        if p["tier"] != "Mega":
            continue
        pts = p["points"] or 0
        if app._mega_tier_label(pts, settings):          # 27/28/29/30 -> uber
            slot = "Uber 2" if uber_count >= 1 else "Uber 1"
            uber_count += 1
            is_free = 0
        else:
            slot, is_free_b = app._auto_slot(p["pokemon_name"], pts, mega_set, existing)
            is_free = 1 if is_free_b else 0
        db.execute("UPDATE pokemon_roster SET tier=?, is_free_pick=? WHERE id=?",
                   (slot, is_free, p["id"]))
        db.execute("UPDATE draft_picks SET slot_name=? WHERE coach_id=? AND pokemon_name=? AND slot_name='Mega'",
                   (slot, cid, p["pokemon_name"]))
        existing.append({"tier": slot, "is_free_pick": is_free})
        total += 1
        print(f"  {p['pokemon_name']:22s} {pts:3d}pt -> {slot}", flush=True)

db.commit()
db.close()
print(f"\nOK  Re-slotted {total} mega pick(s).")
