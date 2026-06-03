"""
Migrate mega pokemon movepools: ensure each mega has all moves from its base form.
Champion-granted extras on the mega are preserved (union, not replace).
Run once in the PythonAnywhere console:
    cd /home/zcs55397/yuri-draft-league && python scripts/migrate_mega_moves.py
"""
import sqlite3

conn = sqlite3.connect("league.db")
c = conn.cursor()

c.execute("SELECT name, moves FROM draft_tiers WHERE is_mega=1")
all_megas = c.fetchall()

updates = []
for mega_name, mega_moves_raw in all_megas:
    base = mega_name.replace("Mega ", "").strip()
    if base.endswith(" X") or base.endswith(" Y"):
        base = base[:-2].strip()
    c.execute("SELECT moves FROM draft_tiers WHERE name=?", (base,))
    row = c.fetchone()
    if not row or not row[0]:
        print(f"SKIP (no base found): {mega_name}")
        continue

    base_moves = row[0].split("|")
    mega_moves = mega_moves_raw.split("|") if mega_moves_raw else []

    # Union: start with mega moves, then overwrite/add base moves
    # Base form capitalization wins to fix any case mismatches
    merged = {m.lower(): m for m in mega_moves}
    for m in base_moves:
        merged[m.lower()] = m

    final_str = "|".join(sorted(merged.values(), key=lambda x: x.lower()))

    if final_str != mega_moves_raw:
        updates.append((final_str, mega_name))

for final_str, mega_name in updates:
    c.execute("UPDATE draft_tiers SET moves=? WHERE name=?", (final_str, mega_name))

conn.commit()
conn.close()
print(f"Done — updated {len(updates)} mega movepools.")
