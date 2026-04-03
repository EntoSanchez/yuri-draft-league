"""
One-time migration: update league_settings to desired defaults.
Run on PythonAnywhere: python migrate_settings.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "league.db")

UPDATES = [
    ("draft_free_pick_type", "four_any"),
    ("mechanic_mega",        "0"),
]

conn = sqlite3.connect(DB_PATH)
for key, value in UPDATES:
    conn.execute(
        "INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)",
        (key, value)
    )
    print(f"Set {key} = {value!r}")
conn.commit()
conn.close()
print("Done.")
