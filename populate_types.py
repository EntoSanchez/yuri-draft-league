"""
Auto-populate type1/type2 for all draft_tiers entries that have blank types.
Uses the PokeAPI (https://pokeapi.co) — no key required, rate-limited to ~1 req/sec.

Usage:
  python populate_types.py [--force]

Options:
  --force   Re-fetch even for pokemon that already have type data
"""

import re
import sqlite3
import sys
import time
import urllib.request
import json

DB_PATH = "D:/Yuri Draft League/league.db"

# Manual overrides for names that PokeAPI won't match by slug alone
NAME_OVERRIDES = {
    # Specific form slugs for PokeAPI
    "calyrex-shadow-rider": "calyrex-shadow",
    "calyrex-ice-rider": "calyrex-ice",
    "urshifu-rapid-strike": "urshifu-rapid-strike",
    "urshifu-single-strike": "urshifu",
    "landorus-incarnate": "landorus",
    "thundurus-incarnate": "thundurus",
    "tornadus-incarnate": "tornadus",
    "enamorus-incarnate": "enamorus",
    "landorus-therian": "landorus-therian",
    "thundurus-therian": "thundurus-therian",
    "tornadus-therian": "tornadus-therian",
    "enamorus-therian": "enamorus-therian",
    "indeedee-female": "indeedee-f",
    "indeedee-male": "indeedee",
    "basculegion-male": "basculegion",
    "basculegion-female": "basculegion-f",
    "oinkologne-female": "oinkologne-f",
    "oinkologne-male": "oinkologne",
    "palafin-zero": "palafin",
    "palafin-hero": "palafin-hero",
    "maushold-family-of-three": "maushold",
    "maushold-family-of-four": "maushold-family-of-four",
    "tatsugiri-curly": "tatsugiri",
    "tatsugiri-droopy": "tatsugiri-droopy",
    "tatsugiri-stretchy": "tatsugiri-stretchy",
    "dudunsparce-two-segment": "dudunsparce",
    "dudunsparce-three-segment": "dudunsparce-three-segment",
    "ogerpon": "ogerpon-teal",
    "ogerpon-wellspring": "ogerpon-wellspring",
    "ogerpon-hearthflame": "ogerpon-hearthflame",
    "ogerpon-cornerstone": "ogerpon-cornerstone",
    "arceus": "arceus",
    "arceus-ghost": "arceus-ghost",
    "giratina-altered": "giratina",
    "giratina-origin": "giratina-origin",
    "shaymin-sky": "shaymin-sky",
    "shaymin-land": "shaymin",
    "rotom-wash": "rotom-wash",
    "rotom-heat": "rotom-heat",
    "rotom-mow": "rotom-mow",
    "rotom-fan": "rotom-fan",
    "rotom-frost": "rotom-frost",
    "rotom-base": "rotom",
    "deoxys-attack": "deoxys-attack",
    "deoxys-defense": "deoxys-defense",
    "deoxys-speed": "deoxys-speed",
    "deoxys-normal": "deoxys",
    "kyurem-black": "kyurem-black",
    "kyurem-white": "kyurem-white",
    "necrozma-dawn-wings": "necrozma-dawn",
    "necrozma-dusk-mane": "necrozma-dusk",
    "necrozma-ultra": "necrozma-ultra",
    "zygarde-50": "zygarde",
    "zygarde-10": "zygarde-10",
    "zygarde-complete": "zygarde-complete",
    "lycanroc-midday": "lycanroc",
    "lycanroc-midnight": "lycanroc-midnight",
    "lycanroc-dusk": "lycanroc-dusk",
    "toxtricity-amped": "toxtricity",
    "toxtricity-low-key": "toxtricity-low-key",
    "meowstic-male": "meowstic",
    "meowstic-female": "meowstic-f",
    "urshifu": "urshifu",
    "mewtwo-mega-x": "mewtwo",
    "mewtwo-mega-y": "mewtwo",
}


def name_to_slug(name: str) -> str:
    """Convert a pokemon name like 'Garchomp-Mega' to a PokeAPI slug."""
    slug = name.lower().strip()
    # Remove leading/trailing spaces, collapse multiple dashes
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    # Check manual overrides first
    if slug in NAME_OVERRIDES:
        return NAME_OVERRIDES[slug]
    # Strip -mega suffix (PokeAPI uses separate mega endpoints not always consistent)
    slug = re.sub(r"-mega(?:-[xy])?$", "", slug)
    return slug


def fetch_types(slug: str) -> tuple[str, str] | None:
    """Fetch type1, type2 from PokeAPI for a given slug. Returns None on failure."""
    url = f"https://pokeapi.co/api/v2/pokemon/{slug}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "yuri-draft-league/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        types = sorted(data["types"], key=lambda x: x["slot"])
        type1 = types[0]["type"]["name"].capitalize() if len(types) >= 1 else ""
        type2 = types[1]["type"]["name"].capitalize() if len(types) >= 2 else ""
        return type1, type2
    except Exception:
        return None


def main():
    force = "--force" in sys.argv
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query = "SELECT id, name FROM draft_tiers"
    if not force:
        query += " WHERE type1 IS NULL OR type1 = ''"
    rows = conn.execute(query).fetchall()

    print(f"Fetching types for {len(rows)} pokemon{'(all)' if force else ' with missing types'}...")
    updated = 0
    failed = []

    for i, row in enumerate(rows):
        slug = name_to_slug(row["name"])
        result = fetch_types(slug)

        if result is None:
            failed.append(row["name"])
            print(f"  [{i+1}/{len(rows)}] FAIL  {row['name']} (slug: {slug})")
        else:
            type1, type2 = result
            conn.execute("UPDATE draft_tiers SET type1=?, type2=? WHERE id=?",
                         (type1, type2, row["id"]))
            conn.commit()
            updated += 1
            print(f"  [{i+1}/{len(rows)}] OK    {row['name']} → {type1}/{type2 or '-'}")

        # Rate limit: PokeAPI asks for ~1 req/sec, be polite
        time.sleep(0.6)

    conn.close()
    print(f"\nDone. Updated {updated}, failed {len(failed)}.")
    if failed:
        print("Failed pokemon:")
        for n in failed:
            print(f"  - {n}")


if __name__ == "__main__":
    main()
