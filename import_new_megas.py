"""
Import new Mega pokemon (Legends: Z-A) into pokedex and draft_tiers.

Run from ~/yuri-draft-league/yuri-draft-league/:
    python3 ../import_new_megas.py

Or with an explicit DB path:
    python3 ../import_new_megas.py /path/to/league.db
"""

import json
import re
import sqlite3
import sys
import time
import urllib.request

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else "league.db"

# (pokeapi_id, pokeapi_slug) — IDs 10278–10325 from PokeAPI
NEW_MEGAS = [
    (10278, "clefable-mega"),
    (10279, "victreebel-mega"),
    (10280, "starmie-mega"),
    (10281, "dragonite-mega"),
    (10282, "meganium-mega"),
    (10283, "feraligatr-mega"),
    (10284, "skarmory-mega"),
    (10285, "froslass-mega"),
    (10286, "emboar-mega"),
    (10287, "excadrill-mega"),
    (10288, "scolipede-mega"),
    (10289, "scrafty-mega"),
    (10290, "eelektross-mega"),
    (10291, "chandelure-mega"),
    (10292, "chesnaught-mega"),
    (10293, "delphox-mega"),
    (10294, "greninja-mega"),
    (10295, "pyroar-mega"),
    (10296, "floette-mega"),
    (10297, "malamar-mega"),
    (10298, "barbaracle-mega"),
    (10299, "dragalge-mega"),
    (10300, "hawlucha-mega"),
    (10301, "zygarde-mega"),
    (10302, "drampa-mega"),
    (10303, "falinks-mega"),
    (10304, "raichu-mega-x"),
    (10305, "raichu-mega-y"),
    (10306, "chimecho-mega"),
    (10307, "absol-mega-z"),
    (10308, "staraptor-mega"),
    (10309, "garchomp-mega-z"),
    (10310, "lucario-mega-z"),
    (10311, "heatran-mega"),
    (10312, "darkrai-mega"),
    (10313, "golurk-mega"),
    (10314, "meowstic-mega"),
    (10315, "crabominable-mega"),
    (10316, "golisopod-mega"),
    (10317, "magearna-mega"),
    (10318, "magearna-original-mega"),
    (10319, "zeraora-mega"),
    (10320, "scovillain-mega"),
    (10321, "glimmora-mega"),
    (10322, "tatsugiri-curly-mega"),
    (10323, "tatsugiri-droopy-mega"),
    (10324, "tatsugiri-stretchy-mega"),
    (10325, "baxcalibur-mega"),
]


def slug_to_display(slug):
    """Convert PokeAPI slug to display name.

    'clefable-mega'      → 'Mega Clefable'
    'raichu-mega-x'      → 'Mega Raichu X'
    'absol-mega-z'       → 'Mega Absol Z'
    'tatsugiri-curly-mega' → 'Mega Tatsugiri Curly'
    """
    m = re.match(r"^(.+)-mega-([xyz])$", slug)
    if m:
        base = " ".join(p.capitalize() for p in m.group(1).split("-"))
        return f"Mega {base} {m.group(2).upper()}"
    m = re.match(r"^(.+)-mega$", slug)
    if m:
        base = " ".join(p.capitalize() for p in m.group(1).split("-"))
        return f"Mega {base}"
    return slug.replace("-", " ").title()


def fetch_pokemon(slug):
    """Fetch types and base stats from PokeAPI. Returns dict or None."""
    url = f"https://pokeapi.co/api/v2/pokemon/{slug}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "yuri-draft-league/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        types = sorted(data["types"], key=lambda x: x["slot"])
        type1 = types[0]["type"]["name"].capitalize() if types else ""
        type2 = types[1]["type"]["name"].capitalize() if len(types) > 1 else ""

        stat_map = {s["stat"]["name"]: s["base_stat"] for s in data["stats"]}
        hp  = stat_map.get("hp")
        atk = stat_map.get("attack")
        def_ = stat_map.get("defense")
        spa = stat_map.get("special-attack")
        spd = stat_map.get("special-defense")
        spe = stat_map.get("speed")
        bst = sum(v for v in [hp, atk, def_, spa, spd, spe] if v is not None) or None

        return {"type1": type1, "type2": type2, "hp": hp, "atk": atk,
                "def_stat": def_, "spa": spa, "spd": spd, "spe": spe, "bst": bst}
    except Exception:
        return None


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    existing_dt = {r["name"] for r in conn.execute("SELECT name FROM draft_tiers").fetchall()}
    existing_pd = {r["pokeapi_name"] for r in conn.execute("SELECT pokeapi_name FROM pokedex").fetchall()}

    new_dt = new_pd = 0
    failed = []

    for pokeapi_id, slug in NEW_MEGAS:
        display = slug_to_display(slug)
        print(f"{slug:<35} → {display:<30}", end=" ", flush=True)

        pdata = fetch_pokemon(slug)
        if pdata:
            print(f"OK  {pdata['type1']}/{pdata['type2'] or '-'}")
        else:
            print("FAIL")
            failed.append((slug, display))
            pdata = {"type1": "", "type2": "", "hp": None, "atk": None,
                     "def_stat": None, "spa": None, "spd": None, "spe": None, "bst": None}

        # pokedex
        if slug not in existing_pd:
            conn.execute(
                "INSERT INTO pokedex "
                "(pokeapi_name, display_name, type1, type2, hp, atk, def_stat, spa, spd, spe, pokeapi_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (slug, display, pdata["type1"], pdata["type2"],
                 pdata["hp"], pdata["atk"], pdata["def_stat"],
                 pdata["spa"], pdata["spd"], pdata["spe"], pokeapi_id),
            )
            new_pd += 1
        else:
            conn.execute(
                "UPDATE pokedex SET display_name=?, type1=?, type2=?, hp=?, atk=?, "
                "def_stat=?, spa=?, spd=?, spe=?, pokeapi_id=? WHERE pokeapi_name=?",
                (display, pdata["type1"], pdata["type2"],
                 pdata["hp"], pdata["atk"], pdata["def_stat"],
                 pdata["spa"], pdata["spd"], pdata["spe"], pokeapi_id, slug),
            )

        # draft_tiers
        if display not in existing_dt:
            conn.execute(
                "INSERT INTO draft_tiers "
                "(name, points, is_mega, type1, type2, hp, atk, defense, spa, spd, spe, bst) "
                "VALUES (?,0,1,?,?,?,?,?,?,?,?,?)",
                (display, pdata["type1"], pdata["type2"],
                 pdata["hp"], pdata["atk"], pdata["def_stat"],
                 pdata["spa"], pdata["spd"], pdata["spe"], pdata["bst"]),
            )
            new_dt += 1
        else:
            conn.execute(
                "UPDATE draft_tiers SET type1=?, type2=?, hp=?, atk=?, "
                "defense=?, spa=?, spd=?, spe=?, bst=? WHERE name=?",
                (pdata["type1"], pdata["type2"],
                 pdata["hp"], pdata["atk"], pdata["def_stat"],
                 pdata["spa"], pdata["spd"], pdata["spe"], pdata["bst"], display),
            )

        # pokemon_db — sprite lookup uses Showdown slug format (megax not mega-x)
        # Z-variants: absol-megaz | X/Y: raichu-megax | regular: clefable-mega
        m = re.match(r"^(.+)-mega-([xyz])$", slug)
        sprite_slug = (m.group(1) + "-mega" + m.group(2)) if m else slug
        conn.execute(
            "INSERT OR REPLACE INTO pokemon_db (name, pokeapi_id) VALUES (?,?)",
            (sprite_slug, pokeapi_id),
        )

        conn.commit()
        time.sleep(0.5)

    conn.close()

    print(f"\nDone. Pokedex: +{new_pd} inserted. Draft tiers: +{new_dt} inserted.")
    if failed:
        print(f"\nPokeAPI failed for {len(failed)} slugs (types/stats left blank):")
        for slug, display in failed:
            print(f"  {slug}")
        print("\nYou can manually set types/stats via the admin panel.")


if __name__ == "__main__":
    main()
