"""
Fetch the full Pokemon name→ID mapping from PokeAPI and store in the database.
Run once: python fetch_pokemon_db.py

Sprite URL format after running:
  https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/showdown/<id>.gif
"""
import sqlite3
import urllib.request
import json

DB_PATH = "D:/Yuri Draft League/league.db"


def fetch_pokemon_db():
    print("Fetching Pokemon list from PokeAPI (this may take a moment)...")
    url = "https://pokeapi.co/api/v2/pokemon?limit=2000"
    req = urllib.request.Request(url, headers={"User-Agent": "YuriCupLeagueApp/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())

    pokemon = []
    for p in data["results"]:
        # URL format: https://pokeapi.co/api/v2/pokemon/1/
        pid = int(p["url"].rstrip("/").split("/")[-1])
        pokemon.append((p["name"], pid))

    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS pokemon_db (
        name TEXT PRIMARY KEY,
        pokeapi_id INTEGER NOT NULL
    )""")
    conn.executemany(
        "INSERT OR REPLACE INTO pokemon_db (name, pokeapi_id) VALUES (?, ?)",
        pokemon
    )
    conn.commit()
    conn.close()
    print(f"Done! Stored {len(pokemon)} Pokemon in the database.")
    print("Sprite GIFs will now load from the PokeAPI sprites repository.")


if __name__ == "__main__":
    fetch_pokemon_db()
