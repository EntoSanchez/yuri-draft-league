"""
Auto-populate type1/type2 for all draft_tiers entries that have blank types.
Uses the PokeAPI (https://pokeapi.co) — no key required.

Usage:
  python populate_types.py           # only fills in missing types
  python populate_types.py --force   # re-fetches all
  python -c "import populate_types; populate_types.DB_PATH='league.db'; populate_types.main()"
"""

import re
import sqlite3
import sys
import time
import urllib.request
import json

DB_PATH = "D:/Yuri Draft League/league.db"

# Types we can determine without an API call — avoids rate-limit failures
HARDCODED_TYPES = {
    # Arceus — type matches the plate
    "Arceus":           ("Normal", ""),
    "Arceus-Normal":    ("Normal", ""),
    "Arceus-Fire":      ("Fire", ""),
    "Arceus-Water":     ("Water", ""),
    "Arceus-Electric":  ("Electric", ""),
    "Arceus-Grass":     ("Grass", ""),
    "Arceus-Ice":       ("Ice", ""),
    "Arceus-Fighting":  ("Fighting", ""),
    "Arceus-Poison":    ("Poison", ""),
    "Arceus-Ground":    ("Ground", ""),
    "Arceus-Flying":    ("Flying", ""),
    "Arceus-Psychic":   ("Psychic", ""),
    "Arceus-Bug":       ("Bug", ""),
    "Arceus-Rock":      ("Rock", ""),
    "Arceus-Ghost":     ("Ghost", ""),
    "Arceus-Dragon":    ("Dragon", ""),
    "Arceus-Dark":      ("Dark", ""),
    "Arceus-Steel":     ("Steel", ""),
    "Arceus-Fairy":     ("Fairy", ""),
    # Misc special cases
    "Pichu-Spiky-Eared":      ("Electric", ""),
    "Eevee-Starter":          ("Normal", ""),
    "Eternamax Eternatus":    ("Poison", "Dragon"),
    "Terrakion":              ("Rock", "Fighting"),
    "Giratina":               ("Ghost", "Dragon"),
    "Zygarde":                ("Dragon", "Ground"),
    "Deoxys":                 ("Psychic", ""),
    "Keldeo":                 ("Water", "Fighting"),
    "Meloetta":               ("Normal", "Psychic"),
    "Shaymin":                ("Grass", ""),
    "Aegislash":              ("Steel", "Ghost"),
    "Mimikyu":                ("Ghost", "Fairy"),
    "Darmanitan":             ("Fire", ""),
    # Megas
    "Mega Gengar":            ("Ghost", "Poison"),
    "Mega Mewtwo X":          ("Psychic", "Fighting"),
    "Mega Mewtwo Y":          ("Psychic", ""),
    "Mega Rayquaza":          ("Dragon", "Flying"),
    "Mega Salamence":         ("Dragon", "Flying"),
    "Mega Lucario":           ("Fighting", "Steel"),
    "Mega Metagross":         ("Steel", "Psychic"),
    "Mega Blaziken":          ("Fire", "Fighting"),
    "Mega Blastoise":         ("Water", ""),
    "Mega Kangaskhan":        ("Normal", ""),
    "Mega Scizor":            ("Bug", "Steel"),
    "Mega Alakazam":          ("Psychic", ""),
    "Mega Diancie":           ("Rock", "Fairy"),
    "Mega Lopunny":           ("Normal", "Fighting"),
    "Mega Charizard X":       ("Fire", "Dragon"),
    "Mega Charizard Y":       ("Fire", "Flying"),
    "Mega Garchomp":          ("Dragon", "Ground"),
    "Mega Aerodactyl":        ("Rock", "Flying"),
    "Mega Mawile":            ("Steel", "Fairy"),
    "Mega Gallade":           ("Psychic", "Fighting"),
    "Mega Medicham":          ("Fighting", "Psychic"),
    "Mega Gardevoir":         ("Psychic", "Fairy"),
    "Mega Latias":            ("Dragon", "Psychic"),
    "Mega Latios":            ("Dragon", "Psychic"),
    "Mega Slowbro":           ("Water", "Psychic"),
    "Mega Swampert":          ("Water", "Ground"),
    "Mega Aggron":            ("Steel", ""),
    "Mega Sableye":           ("Dark", "Ghost"),
    "Mega Venusaur":          ("Grass", "Poison"),
    "Mega Altaria":           ("Dragon", "Fairy"),
    "Mega Tyranitar":         ("Rock", "Dark"),
    "Mega Beedrill":          ("Bug", "Poison"),
    "Mega Heracross":         ("Bug", "Fighting"),
    "Mega Sharpedo":          ("Water", "Dark"),
    "Mega Gyarados":          ("Water", "Dark"),
    "Mega Pinsir":            ("Bug", "Flying"),
    "Mega Pidgeot":           ("Normal", "Flying"),
    "Mega Steelix":           ("Steel", "Ground"),
    "Mega Sceptile":          ("Grass", "Dragon"),
    "Mega Abomasnow":         ("Grass", "Ice"),
    "Mega Ampharos":          ("Electric", "Dragon"),
    "Mega Glalie":            ("Ice", ""),
    "Mega Houndoom":          ("Dark", "Fire"),
    "Mega Manectric":         ("Electric", ""),
    "Mega Audino":            ("Normal", "Fairy"),
    "Mega Camerupt":          ("Fire", "Ground"),
    "Mega Absol":             ("Dark", ""),
    "Mega Banette":           ("Ghost", ""),
    # Primal
    "Primal Groudon":         ("Ground", "Fire"),
    "Primal Kyogre":          ("Water", ""),
    # Regional variants — Alolan
    "Alolan Raichu":          ("Electric", "Psychic"),
    "Alolan Sandshrew":       ("Ice", "Steel"),
    "Alolan Sandslash":       ("Ice", "Steel"),
    "Alolan Vulpix":          ("Ice", ""),
    "Alolan Ninetales":       ("Ice", "Fairy"),
    "Alolan Diglett":         ("Ground", "Steel"),
    "Alolan Dugtrio":         ("Ground", "Steel"),
    "Alolan Meowth":          ("Dark", ""),
    "Alolan Persian":         ("Dark", ""),
    "Alolan Geodude":         ("Rock", "Electric"),
    "Alolan Graveler":        ("Rock", "Electric"),
    "Alolan Golem":           ("Rock", "Electric"),
    "Alolan Grimer":          ("Poison", "Dark"),
    "Alolan Muk":             ("Poison", "Dark"),
    "Alolan Exeggutor":       ("Grass", "Dragon"),
    "Alolan Marowak":         ("Fire", "Ghost"),
    "Alolan Raticate":        ("Dark", "Normal"),
    "Alolan Rattata":         ("Dark", "Normal"),
    # Regional variants — Galarian
    "Galarian Meowth":        ("Steel", ""),
    "Galarian Ponyta":        ("Psychic", ""),
    "Galarian Rapidash":      ("Psychic", "Fairy"),
    "Galarian Slowpoke":      ("Psychic", ""),
    "Galarian Slowbro":       ("Poison", "Psychic"),
    "Galarian Slowking":      ("Poison", "Psychic"),
    "Galarian Farfetch'd":    ("Fighting", ""),
    "Galarian Corsola":       ("Ghost", ""),
    "Galarian Zigzagoon":     ("Dark", "Normal"),
    "Galarian Linoone":       ("Dark", "Normal"),
    "Galarian Darumaka":      ("Ice", ""),
    "Galarian Darmanitan":    ("Ice", "Fire"),
    "Galarian Yamask":        ("Ground", "Ghost"),
    "Galarian Stunfisk":      ("Ground", "Steel"),
    "Galarian Articuno":      ("Psychic", "Flying"),
    "Galarian Zapdos":        ("Fighting", "Flying"),
    "Galarian Moltres":       ("Dark", "Flying"),
    "Galarian Weezing":       ("Poison", "Fairy"),
    "Galarian Mr. Mime":      ("Ice", "Psychic"),
    # Regional variants — Hisuian
    "Hisuian Growlithe":      ("Fire", "Rock"),
    "Hisuian Arcanine":       ("Fire", "Rock"),
    "Hisuian Voltorb":        ("Electric", "Grass"),
    "Hisuian Electrode":      ("Electric", "Grass"),
    "Hisuian Sneasel":        ("Fighting", "Poison"),
    "Hisuian Qwilfish":       ("Dark", "Poison"),
    "Hisuian Sliggoo":        ("Steel", "Dragon"),
    "Hisuian Goodra":         ("Steel", "Dragon"),
    "Hisuian Avalugg":        ("Ice", "Rock"),
    "Hisuian Zorua":          ("Normal", "Ghost"),
    "Hisuian Zoroark":        ("Normal", "Ghost"),
    "Hisuian Braviary":       ("Psychic", "Flying"),
    "Hisuian Lilligant":      ("Grass", "Fighting"),
    "Hisuian Samurott":       ("Water", "Dark"),
    "Hisuian Decidueye":      ("Grass", "Fighting"),
    "Hisuian Typhlosion":     ("Fire", "Ghost"),
    # Regional variants — Paldean
    "Paldean Tauros":         ("Fighting", ""),
    "Paldean Tauros Blaze":   ("Fighting", "Fire"),
    "Paldean Tauros Aqua":    ("Fighting", "Water"),
    "Paldean Wooper":         ("Poison", "Ground"),
    # Misc form variants
    "Urshifu-Single-Strike":  ("Fighting", "Dark"),
    "Landorus-Incarnate":     ("Ground", "Flying"),
    "Thundurus-Incarnate":    ("Electric", "Flying"),
    "Tornadus-Incarnate":     ("Flying", ""),
    "Enamorus-Incarnate":     ("Fairy", "Flying"),
    "Ogerpon":                ("Grass", ""),
    "Ogerpon-Wellspring":     ("Grass", "Water"),
    "Ogerpon-Hearthflame":    ("Grass", "Fire"),
    "Ogerpon-Cornerstone":    ("Grass", "Rock"),
    "Palafin":                ("Water", ""),
    "Lycanroc-Midday":        ("Rock", ""),
    "Basculegion":            ("Water", "Ghost"),
    "Aegislash":              ("Steel", "Ghost"),
    "Meowstic":               ("Psychic", ""),
    "Indeedee":               ("Psychic", "Normal"),
    "Maushold":               ("Normal", ""),
    "Tatsugiri":              ("Dragon", "Water"),
    "Dudunsparce":            ("Normal", ""),
    "Toxtricity":             ("Electric", "Poison"),
    "Mimikyu":                ("Ghost", "Fairy"),
    "Wishiwashi":             ("Water", ""),
    "Minior":                 ("Rock", "Flying"),
    "Oricorio":               ("Fire", "Flying"),
    "Morpeko":                ("Electric", "Dark"),
    "Eiscue":                 ("Ice", ""),
    "Gourgeist":              ("Ghost", "Grass"),
    "Pumpkaboo":              ("Ghost", "Grass"),
    "Wormadam":               ("Bug", "Grass"),
    "Squawkabilly":           ("Normal", "Flying"),
    "Basculin":               ("Water", ""),
    "Jellicent":              ("Water", "Ghost"),
    "Frillish":               ("Water", "Ghost"),
    "Pyroar":                 ("Fire", "Normal"),
    "Oinkologne":             ("Normal", ""),
    "Type: Null":             ("Normal", ""),
    "Farfetch'd":             ("Normal", "Flying"),
    "Sirfetch'd":             ("Fighting", ""),
    "Mr. Mime":               ("Psychic", "Fairy"),
    "Mr. Rime":               ("Ice", "Psychic"),
    "Mime Jr.":               ("Psychic", "Fairy"),
    "Nidoran-Female":         ("Poison", ""),
    "Nidoran-Male":           ("Poison", ""),
}

# Slug overrides: normalised slug → PokeAPI slug
SLUG_OVERRIDES = {
    "landorus-incarnate":    "landorus",
    "thundurus-incarnate":   "thundurus",
    "tornadus-incarnate":    "tornadus",
    "enamorus-incarnate":    "enamorus",
    "calyrex-shadow-rider":  "calyrex-shadow",
    "calyrex-ice-rider":     "calyrex-ice",
    "urshifu-single-strike": "urshifu",
    "urshifu-rapid-strike":  "urshifu-rapid-strike",
    "giratina":              "giratina-altered",
    "giratina-altered":      "giratina-altered",
    "giratina-origin":       "giratina-origin",
    "zygarde":               "zygarde",
    "zygarde-50":            "zygarde",
    "deoxys":                "deoxys-normal",
    "nidoran-female":        "nidoran-f",
    "nidoran-male":          "nidoran-m",
    "keldeo":                "keldeo",
    "aegislash":             "aegislash-shield",
    "meloetta":              "meloetta-aria",
    "meowstic":              "meowstic",
    "indeedee":              "indeedee",
    "wishiwashi":            "wishiwashi-solo",
    "minior":                "minior-red-meteor",
    "oricorio":              "oricorio-baile",
    "morpeko":               "morpeko-full-belly",
    "eiscue":                "eiscue-ice",
    "tatsugiri":             "tatsugiri-curly",
    "dudunsparce":           "dudunsparce-two-segment",
    "maushold":              "maushold",
    "basculin":              "basculin-red-striped",
    "basculegion":           "basculegion",
    "jellicent":             "jellicent",
    "frillish":              "frillish",
    "pyroar":                "pyroar",
    "oinkologne":            "oinkologne",
    "gourgeist":             "gourgeist-average",
    "pumpkaboo":             "pumpkaboo-average",
    "wormadam":              "wormadam-plant",
    "squawkabilly":          "squawkabilly-green-plumage",
    "ogerpon":               "ogerpon-teal",
    "ogerpon-wellspring":    "ogerpon-wellspring",
    "ogerpon-hearthflame":   "ogerpon-hearthflame",
    "ogerpon-cornerstone":   "ogerpon-cornerstone",
    "palafin":               "palafin",
    "palafin-zero":          "palafin",
    "palafin-hero":          "palafin-hero",
    "lycanroc-midday":       "lycanroc",
    "lycanroc-midnight":     "lycanroc-midnight",
    "lycanroc-dusk":         "lycanroc-dusk",
    "toxtricity":            "toxtricity",
    "toxtricity-low-key":    "toxtricity-low-key",
    "meowstic-male":         "meowstic",
    "meowstic-female":       "meowstic-f",
    "indeedee-male":         "indeedee",
    "indeedee-female":       "indeedee-f",
    "basculegion-male":      "basculegion",
    "basculegion-female":    "basculegion-f",
    "oinkologne-male":       "oinkologne",
    "oinkologne-female":     "oinkologne-f",
    "kyurem-black":          "kyurem-black",
    "kyurem-white":          "kyurem-white",
    "necrozma-dusk-mane":    "necrozma-dusk",
    "necrozma-dawn-wings":   "necrozma-dawn",
    "necrozma-ultra":        "necrozma-ultra",
    "tauros-paldea":         "tauros-paldea-combat",
    "tauros-paldea-aqua":    "tauros-paldea-aqua",
    "tauros-paldea-blaze":   "tauros-paldea-blaze",
}


def _clean(s):
    return s.replace("'", "").replace(".", "").replace(":", "").replace(" ", "-")


def name_to_slug(name):
    lower = name.lower().strip()

    prefix_map = [
        (r"^alolan\s+", "-alola"),
        (r"^galarian\s+", "-galar"),
        (r"^hisuian\s+", "-hisui"),
        (r"^paldean\s+tauros(?:\s+(aqua|blaze))?$", None),  # handled below
        (r"^paldean\s+", "-paldea"),
        (r"^primal\s+", "-primal"),
        (r"^eternamax\s+", "-eternamax"),
    ]

    # Paldean Tauros variants need special handling
    m = re.match(r"^paldean\s+tauros(?:\s+(aqua|blaze))?$", lower)
    if m:
        variant = m.group(1)
        if variant == "aqua":
            return "tauros-paldea-aqua"
        elif variant == "blaze":
            return "tauros-paldea-blaze"
        else:
            return "tauros-paldea-combat"

    for pattern, suffix in prefix_map:
        if suffix is None:
            continue
        m = re.match(pattern, lower)
        if m:
            base = _clean(lower[m.end():].strip())
            slug = base + suffix
            return SLUG_OVERRIDES.get(slug, slug)

    # Mega: "Mega X" → "X-mega", "Mega X Y" → "X-mega-Y"
    m = re.match(r"^mega\s+(.+?)(?:\s+([xy]))?$", lower)
    if m:
        base = _clean(m.group(1).strip().replace(" ", "-"))
        variant = m.group(2)
        slug = base + "-mega" + (f"-{variant}" if variant else "")
        return SLUG_OVERRIDES.get(slug, slug)

    slug = _clean(lower)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return SLUG_OVERRIDES.get(slug, slug)


def fetch_types(slug):
    url = f"https://pokeapi.co/api/v2/pokemon/{slug}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "yuri-draft-league/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
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

    if force:
        rows = conn.execute("SELECT id, name FROM draft_tiers").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name FROM draft_tiers WHERE type1 IS NULL OR type1 = ''"
        ).fetchall()

    print(f"Processing {len(rows)} pokemon...")
    updated = 0
    failed = []

    for i, row in enumerate(rows):
        name = row["name"]

        # Check hardcoded first (case-insensitive)
        hardcoded = None
        for key, val in HARDCODED_TYPES.items():
            if key.lower() == name.lower():
                hardcoded = val
                break

        if hardcoded is not None:
            type1, type2 = hardcoded
            conn.execute("UPDATE draft_tiers SET type1=?, type2=? WHERE id=?",
                         (type1, type2, row["id"]))
            conn.commit()
            updated += 1
            print(f"  [{i+1}/{len(rows)}] HARD  {name} → {type1}/{type2 or '-'}")
            continue

        slug = name_to_slug(name)
        result = fetch_types(slug)

        if result is None:
            failed.append((name, slug))
            print(f"  [{i+1}/{len(rows)}] FAIL  {name} (slug: {slug})")
        else:
            type1, type2 = result
            conn.execute("UPDATE draft_tiers SET type1=?, type2=? WHERE id=?",
                         (type1, type2, row["id"]))
            conn.commit()
            updated += 1
            print(f"  [{i+1}/{len(rows)}] OK    {name} → {type1}/{type2 or '-'}")

        time.sleep(0.7)

    conn.close()
    print(f"\nDone. Updated {updated}, failed {len(failed)}.")
    if failed:
        print("Still failing:")
        for name, slug in sorted(failed):
            print(f"  {name!r:40s} → slug: {slug!r}")


if __name__ == "__main__":
    main()
