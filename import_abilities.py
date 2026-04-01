"""
Import Pokemon abilities from a TSV file into draft_tiers.

Expected TSV format (columns 0-indexed):
  0: Pokemon name (e.g. "Charizard-Mega-X", "Sandslash-Alolan", "Scizor-Mega")
  1-2: ignored (blank columns)
  3: Type 1
  4: Type 2
  5-11: HP, ATK, DEF, SPA, SPD, SPE, BST
  12: Ability 1
  13: Ability 2
  14: Ability 3 (hidden ability)

Usage:
  python import_abilities.py abilities_data.tsv

The script normalizes names between TSV format and draft_tiers format:
  TSV "Exeggutor-Alolan"  →  DB "Alolan Exeggutor"
  TSV "Scizor-Mega"       →  DB "Mega Scizor"
  TSV "Charizard-Mega-X"  →  DB "Mega Charizard X"
  TSV "Kyogre-Primal"     →  DB "Primal Kyogre"
  TSV "Arcanine-Hisui"    →  DB "Hisuian Arcanine"
"""
import sqlite3
import sys
import re

DB_PATH = "D:/Yuri Draft League/league.db"

# Regional form suffix → DB prefix mapping
REGIONAL_MAP = {
    "alolan":  "Alolan",
    "alola":   "Alolan",
    "galarian": "Galarian",
    "galar":   "Galarian",
    "hisuian": "Hisuian",
    "hisui":   "Hisuian",
    "paldean": "Paldean",
    "paldea":  "Paldean",
}


def tsv_name_to_db_candidates(raw_name: str) -> list[str]:
    """
    Given a name from the TSV (e.g. "Charizard-Mega-X"), return a list of
    candidate strings to try matching against draft_tiers.name (lowercased).
    """
    name = raw_name.strip()
    parts = [p.strip() for p in name.split("-") if p.strip()]
    lower_parts = [p.lower() for p in parts]

    candidates = [name]  # original as-is

    if len(parts) >= 2:
        base = parts[0]
        suffix_parts = parts[1:]
        suffix_lower = [p.lower() for p in suffix_parts]

        # --- Regional forms ---
        # "Name-Alolan" → "Alolan Name"
        # "Name-Hisui" → "Hisuian Name"
        for i, sp in enumerate(suffix_lower):
            if sp in REGIONAL_MAP:
                region_prefix = REGIONAL_MAP[sp]
                rest_base = " ".join([base] + [suffix_parts[j] for j in range(len(suffix_parts)) if j != i])
                candidates.append(f"{region_prefix} {rest_base}")
                break

        # --- Mega forms ---
        # "Name-Mega" → "Mega Name"
        # "Name-Mega-X" → "Mega Name X"
        if "mega" in suffix_lower:
            idx = suffix_lower.index("mega")
            variants = [p for j, p in enumerate(suffix_parts) if j != idx]
            if variants:
                candidates.append(f"Mega {base} {' '.join(variants)}")
            else:
                candidates.append(f"Mega {base}")

        # --- Primal forms ---
        # "Name-Primal" → "Primal Name"
        if "primal" in suffix_lower:
            candidates.append(f"Primal {base}")

        # --- Speed Boost etc as separate ability form ---
        # "Blaziken-Speed Boost" → just "Blaziken" (same pokemon, alt ability)
        # We handle this by also trying just the base name
        candidates.append(base)

    # Also try with spaces instead of hyphens (for forms like "Crowned")
    candidates.append(name.replace("-", " "))
    candidates.append(name.replace("-", " ").replace("Hisui", "Hisuian"))

    # Lowercase versions for matching
    return [c.lower() for c in dict.fromkeys(candidates)]  # dedup, preserve order


def build_db_name_index(conn) -> dict[str, int]:
    """Map lowercase draft_tiers name → row id."""
    rows = conn.execute("SELECT id, name FROM draft_tiers").fetchall()
    return {r[1].lower(): r[0] for r in rows}


def parse_tsv(filepath: str) -> dict[str, tuple[str, str, str]]:
    """
    Parse the TSV and return {raw_name: (ability1, ability2, ability3)}.
    Skips header lines and blank/NONE-only rows.
    """
    abilities = {}
    with open(filepath, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n\r")
            if not line.strip():
                continue
            cols = line.split("\t")
            # Need at least 13 columns for ability1
            if len(cols) < 13:
                continue
            raw_name = cols[0].strip()
            if not raw_name or raw_name.lower() in ("pokémon", "pokemon", "none", ""):
                continue
            # Skip header row
            if raw_name.lower().startswith("pokémon") or raw_name == "Pokémon":
                continue

            ab1 = cols[12].strip() if len(cols) > 12 else ""
            ab2 = cols[13].strip() if len(cols) > 13 else ""
            ab3 = cols[14].strip() if len(cols) > 14 else ""

            # Skip rows with no ability data at all
            if not ab1 and not ab2 and not ab3:
                continue
            # Skip NONE values
            ab1 = ab1 if ab1.upper() not in ("NONE", "N/A", "") else ""
            ab2 = ab2 if ab2.upper() not in ("NONE", "N/A", "") else ""
            ab3 = ab3 if ab3.upper() not in ("NONE", "N/A", "") else ""

            # Handle alternate forms with same abilities (e.g. Blaziken-Speed Boost)
            # These are separate rows for the same pokemon with a different ability set
            # We'll store them under the transformed name — the normalization handles this
            abilities[raw_name] = (ab1, ab2, ab3)
    return abilities


def main():
    if len(sys.argv) < 2:
        print("Usage: python import_abilities.py <abilities.tsv>")
        sys.exit(1)

    tsv_path = sys.argv[1]
    print(f"Reading ability data from: {tsv_path}")
    abilities_raw = parse_tsv(tsv_path)
    print(f"Parsed {len(abilities_raw)} entries from TSV")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    db_index = build_db_name_index(conn)
    print(f"Draft tiers has {len(db_index)} entries")

    updated = 0
    unmatched = []

    for raw_name, (ab1, ab2, ab3) in abilities_raw.items():
        candidates = tsv_name_to_db_candidates(raw_name)
        matched_id = None
        for cand in candidates:
            if cand in db_index:
                matched_id = db_index[cand]
                break

        if matched_id is None:
            unmatched.append(raw_name)
            continue

        conn.execute(
            "UPDATE draft_tiers SET ability1=?, ability2=?, ability3=? WHERE id=?",
            (ab1, ab2, ab3, matched_id)
        )
        updated += 1

    conn.commit()
    conn.close()

    print(f"\nUpdated {updated} pokemon with ability data")
    if unmatched:
        print(f"Could not match {len(unmatched)} TSV entries to draft_tiers:")
        for n in sorted(unmatched)[:50]:
            print(f"  - {n}")
        if len(unmatched) > 50:
            print(f"  ... and {len(unmatched) - 50} more")


if __name__ == "__main__":
    main()
