"""
Fetch full Pokedex stats (types, base stats) from PokeAPI for all Pokemon in pokemon_db.
Run once: python fetch_pokedex.py

Uses 20 parallel threads to complete in ~1-2 minutes instead of 20+ minutes.
"""
import sqlite3
import urllib.request
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = "D:/Yuri Draft League/league.db"


def fetch_pokemon_data(entry):
    name, pid = entry
    url = f"https://pokeapi.co/api/v2/pokemon/{pid}/"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YuriCupLeagueApp/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())

        types = [t["type"]["name"].capitalize() for t in data["types"]]
        type1 = types[0] if len(types) > 0 else ""
        type2 = types[1] if len(types) > 1 else ""

        stats = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}

        # Build a readable display name from the API name
        display = name.replace("-", " ").title()
        # Common fixes
        display = display.replace("Mr ", "Mr. ").replace("Mime Jr", "Mime Jr.")
        display = display.replace("Farfetchd", "Farfetch'd").replace("Sirfetchd", "Sirfetch'd")
        display = display.replace(" Mega", " (Mega)").replace(" Mega X", " (Mega X)").replace(" Mega Y", " (Mega Y)")
        display = display.replace("Mega X)", "Mega X)").replace("Mega Y)", "Mega Y)")

        return (
            name, display, type1, type2,
            stats.get("hp", 0),
            stats.get("attack", 0),
            stats.get("defense", 0),
            stats.get("special-attack", 0),
            stats.get("special-defense", 0),
            stats.get("speed", 0),
            pid
        )
    except Exception as e:
        print(f"  Error fetching {name} (id={pid}): {e}")
        return None


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Load all Pokemon from the ID map
    try:
        entries = [(r["name"], r["pokeapi_id"]) for r in conn.execute("SELECT name, pokeapi_id FROM pokemon_db").fetchall()]
    except Exception:
        print("Error: Run fetch_pokemon_db.py first to build the ID mapping.")
        conn.close()
        return

    # Create pokedex table
    conn.execute("""CREATE TABLE IF NOT EXISTS pokedex (
        pokeapi_name TEXT PRIMARY KEY,
        display_name TEXT,
        type1 TEXT DEFAULT '',
        type2 TEXT DEFAULT '',
        hp INTEGER DEFAULT 0,
        atk INTEGER DEFAULT 0,
        def_stat INTEGER DEFAULT 0,
        spa INTEGER DEFAULT 0,
        spd INTEGER DEFAULT 0,
        spe INTEGER DEFAULT 0,
        pokeapi_id INTEGER
    )""")
    conn.commit()
    conn.close()

    total = len(entries)
    print(f"Fetching stats for {total} Pokemon (using 20 threads)...")

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_pokemon_data, e): e for e in entries}
        for future in as_completed(futures):
            done += 1
            result = future.result()
            if result:
                results.append(result)
            if done % 100 == 0:
                print(f"  {done}/{total} done...")

    # Bulk insert
    conn = sqlite3.connect(DB_PATH)
    conn.executemany("""INSERT OR REPLACE INTO pokedex
        (pokeapi_name, display_name, type1, type2, hp, atk, def_stat, spa, spd, spe, pokeapi_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", results)
    conn.commit()
    conn.close()

    print(f"Done! Stored {len(results)} Pokemon in the pokedex table.")


if __name__ == "__main__":
    main()
