"""
Diagnostic: print DB path and move counts for key moves.
Run on PythonAnywhere to verify the correct DB is being updated.
"""
import os
import sqlite3
from pathlib import Path

# Replicate app.py's DB path resolution exactly
DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "league.db")
)
DB_PATH = os.path.normpath(DB_PATH)

SCRIPT_DB = str(Path(__file__).parent.parent / "league.db")

print(f"App DB_PATH env:   {os.environ.get('DB_PATH', '(not set)')}")
print(f"App resolved path: {DB_PATH}")
print(f"Script DB path:    {SCRIPT_DB}")
print(f"Same file?         {os.path.abspath(DB_PATH) == os.path.abspath(SCRIPT_DB)}")
print()

conn = sqlite3.connect(DB_PATH)
check = ["Final Gambit", "Expanding Force", "Rising Voltage", "Misty Explosion", "Grassy Glide"]
for move in check:
    n = conn.execute(
        "SELECT COUNT(*) FROM draft_tiers WHERE is_banned != 1 AND LOWER(moves) LIKE ?",
        (f"%{move.lower()}%",)
    ).fetchone()[0]
    print(f"{move}: {n} pokemon in app DB")

print()
conn2 = sqlite3.connect(SCRIPT_DB)
for move in check:
    n = conn2.execute(
        "SELECT COUNT(*) FROM draft_tiers WHERE is_banned != 1 AND LOWER(moves) LIKE ?",
        (f"%{move.lower()}%",)
    ).fetchone()[0]
    print(f"{move}: {n} pokemon in script DB")

conn.close()
conn2.close()
