"""
Diagnostic: print DB path and move counts for key moves.
Run on PythonAnywhere to verify the correct DB is being updated.
"""
import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "league.db")
)
DB_PATH = os.path.normpath(DB_PATH)

print(f"App DB path: {DB_PATH}")
print()

conn = sqlite3.connect(DB_PATH)

# Replicate all_moves logic exactly as app.py does it
tiers = conn.execute("SELECT * FROM draft_tiers ORDER BY points DESC, name").fetchall()
all_moves = sorted({
    m for t in tiers
    for m in (t["moves"] or "").split("|") if m
})

check = ["Final Gambit", "Expanding Force", "Rising Voltage", "Misty Explosion", "Grassy Glide"]
print("=== Exact match in all_moves (as app sees it) ===")
for move in check:
    found = move in all_moves
    # also check repr to expose hidden chars
    matches = [repr(m) for m in all_moves if move.lower() in m.lower()]
    print(f"  {move}: found={found}  similar={matches[:3]}")

print()
print(f"Total moves in dropdown: {len(all_moves)}")
print("Sample from all_moves (F section):")
for m in all_moves:
    if m.lower().startswith("f"):
        print(f"  {repr(m)}")

conn.close()
