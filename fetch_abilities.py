"""
Fetch Pokemon abilities from PokeAPI and populate draft_tiers.ability1/2/3.
Run once after setting up the database:
    python fetch_abilities.py

Only processes rows that are missing ability1 (safe to re-run).
"""
import sqlite3
import urllib.request
import json
import time
import os
import re

DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "league.db")
)

REGIONAL_PREFIXES = {
    "Alolan": "alola",
    "Galarian": "galar",
    "Hisuian": "hisui",
    "Paldean": "paldea",
}

# Explicit overrides: DB display name (lowercased) → PokeAPI slug
SLUG_OVERRIDES = {
    # Punctuation
    "farfetch'd":              "farfetchd",
    "sirfetch'd":              "sirfetchd",
    "flabébé":                 "flabebe",
    # Aegislash — no base-form entry, use shield forme
    "aegislash":               "aegislash-shield",
    # Basculin default form
    "basculin":                "basculin-red-striped",
    # Basculegion
    "basculegion":             "basculegion-male",
    # Calyrex riders
    "calyrex-ice-rider":       "calyrex-ice",
    "calyrex-shadow-rider":    "calyrex-shadow",
    # Darmanitan forms
    "darmanitan":              "darmanitan-standard",
    "galarian darmanitan":     "darmanitan-galar-standard",
    # Deoxys forms (all share same ability)
    "deoxys":                  "deoxys-normal",
    "deoxys-attack":           "deoxys-attack",
    "deoxys-defense":          "deoxys-defense",
    "deoxys-speed":            "deoxys-speed",
    # Dudunsparce
    "dudunsparce":             "dudunsparce-two-segment",
    # Eiscue
    "eiscue":                  "eiscue-ice",
    # Eternatus
    "eternamax eternatus":     "eternatus-eternamax",
    # Frillish (gendered)
    "frillish":                "frillish-male",
    # Indeedee
    "indeedee":                "indeedee-male",
    # Meowstic
    "meowstic":                "meowstic-male",
    # Morpeko
    "morpeko":                 "morpeko-full-belly",
    # Oricorio forms
    "oricorio":                "oricorio-baile",
    # Toxtricity
    "toxtricity":              "toxtricity-amped",
    # Urshifu
    "urshifu":                 "urshifu-single-strike",
    # Zacian / Zamazenta
    "zacian":                  "zacian-hero",
    "zamazenta":               "zamazenta-hero",
    # Giratina
    "giratina":                "giratina-altered",
    # Shaymin
    "shaymin":                 "shaymin-land",
    # Tornadus / Thundurus / Landorus / Enamorus
    "tornadus":                "tornadus-incarnate",
    "thundurus":               "thundurus-incarnate",
    "landorus":                "landorus-incarnate",
    "enamorus":                "enamorus-incarnate",
    # Keldeo
    "keldeo":                  "keldeo-ordinary",
    # Meloetta
    "meloetta":                "meloetta-aria",
    # Hoopa
    "hoopa":                   "hoopa-confined",
    # Necrozma fusions
    "dusk mane necrozma":      "necrozma-dusk",
    "dawn wings necrozma":     "necrozma-dawn",
    # Wishiwashi
    "wishiwashi":              "wishiwashi-solo",
    # Mimikyu
    "mimikyu":                 "mimikyu-disguised",
    # Minior
    "minior":                  "minior-red-meteor",
    # Lycanroc
    "lycanroc":                "lycanroc-midday",
    # Comfey (no override needed usually)
    # Palafin
    "palafin":                 "palafin-zero",
    # Squawkabilly
    "squawkabilly":            "squawkabilly-green-plumage",
    # Tatsugiri
    "tatsugiri":               "tatsugiri-curly",
    # Maushold
    "maushold":                "maushold-family-of-four",
    # Gimmighoul
    "gimmighoul":              "gimmighoul-chest",
}


def name_to_slugs(name: str) -> list[str]:
    """Generate PokeAPI slug candidates for a display name."""
    base = name.lower().strip()

    # Check explicit overrides first
    if base in SLUG_OVERRIDES:
        return [SLUG_OVERRIDES[base]]

    slugs = []

    # Regional prefix forms: "Alolan Ninetales" → "ninetales-alola"
    for prefix, suffix in REGIONAL_PREFIXES.items():
        if base.startswith(prefix.lower() + " "):
            poke = base[len(prefix) + 1:]
            slugs.append(f"{poke.replace(' ', '-')}-{suffix}")

    # Mega forms: "Mega Charizard X" → "charizard-mega-x"
    if base.startswith("mega "):
        rest = base[5:]
        parts = rest.split()
        if len(parts) >= 2 and parts[-1] in ("x", "y"):
            slugs.append(f"{'-'.join(parts[:-1])}-mega-{parts[-1]}")
        else:
            slugs.append(f"{rest.replace(' ', '-')}-mega")

    # Primal forms: "Primal Kyogre" → "kyogre-primal"
    if base.startswith("primal "):
        slugs.append(f"{base[7:].replace(' ', '-')}-primal")

    # Simple slug fallback (replace non-alphanumeric with hyphens)
    slugs.append(re.sub(r"[^a-z0-9]+", "-", base).strip("-"))

    # Deduplicate preserving order
    seen = set()
    result = []
    for s in slugs:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def fetch_abilities(slug: str) -> tuple[str, str, str]:
    url = f"https://pokeapi.co/api/v2/pokemon/{slug}"
    req = urllib.request.Request(url, headers={"User-Agent": "YuriCupLeagueApp/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return "", "", ""

    ab1 = ab2 = ab3 = ""
    for ability in data.get("abilities", []):
        slot = ability.get("slot", 0)
        aname = ability["ability"]["name"].replace("-", " ").title()
        if slot == 1:
            ab1 = aname
        elif slot == 2:
            ab2 = aname
        elif slot == 3:
            ab3 = aname
    return ab1, ab2, ab3


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, name FROM draft_tiers WHERE (ability1 IS NULL OR ability1 = '')"
    ).fetchall()
    print(f"Fetching abilities for {len(rows)} Pokemon...")

    updated = 0
    failed = []

    for i, row in enumerate(rows):
        slugs = name_to_slugs(row["name"])
        ab1 = ab2 = ab3 = ""
        for slug in slugs:
            ab1, ab2, ab3 = fetch_abilities(slug)
            if ab1:
                break
            time.sleep(0.2)  # extra pause between slug attempts

        if ab1:
            conn.execute(
                "UPDATE draft_tiers SET ability1=?, ability2=?, ability3=? WHERE id=?",
                (ab1, ab2, ab3, row["id"])
            )
            updated += 1
        else:
            failed.append(row["name"])

        if (i + 1) % 25 == 0:
            conn.commit()
            print(f"  {i + 1}/{len(rows)} processed ({updated} updated)...")
        time.sleep(0.2)

    conn.commit()
    conn.close()

    print(f"\nDone! Updated {updated}/{len(rows)} Pokemon with abilities.")
    if failed:
        print(f"Could not fetch abilities for {len(failed)} Pokemon:")
        for n in sorted(failed):
            print(f"  - {n}")


if __name__ == "__main__":
    main()
