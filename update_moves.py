"""
update_moves.py
Fetch full Pokémon Showdown learnsets and update draft_tiers.moves
with every move each Pokémon can ever learn.
"""
import re
import sqlite3
import urllib.request

import os, pathlib
_HERE = pathlib.Path(__file__).parent
DB_PATH = str(_HERE / "league.db")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "YuriDraftLeague/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


# ── 1. Parse learnsets.js ──────────────────────────────────────────────────────
print("Fetching learnsets.js (~3 MB) ...", flush=True)
learnsets_js = fetch(
    "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/learnsets.ts"
)

# learnsets_data: { poke_id: {"moves": [move_id, ...], "inherit": bool} }
learnsets_data: dict = {}
current_poke = None
has_inherit = False
cur_moves: list = []

for line in learnsets_js.splitlines():
    poke_m = re.match(r"^\t([a-z0-9]+): \{", line)
    if poke_m:
        if current_poke is not None:
            learnsets_data[current_poke] = {"moves": cur_moves, "inherit": has_inherit}
        current_poke = poke_m.group(1)
        has_inherit = False
        cur_moves = []
    elif current_poke is not None:
        if re.search(r"\binherit\s*:", line):
            has_inherit = True
        move_m = re.match(r"^\t\t\t([a-z0-9]+): \[", line)
        if move_m:
            cur_moves.append(move_m.group(1))

if current_poke is not None:
    learnsets_data[current_poke] = {"moves": cur_moves, "inherit": has_inherit}

print(f"  -> {len(learnsets_data)} learnset entries parsed", flush=True)

# ── 2. Parse moves.js for display names ───────────────────────────────────────
print("Fetching moves.js (~2 MB) ...", flush=True)
moves_js = fetch(
    "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/moves.ts"
)

move_display: dict = {}  # move_id -> "Display Name"
cur_mid = None

for line in moves_js.splitlines():
    m = re.match(r"^\t([a-z0-9]+): \{", line)
    if m:
        cur_mid = m.group(1)
    elif cur_mid:
        nm = re.match(r'^\t\tname: "([^"]+)"', line)
        if nm:
            move_display[cur_mid] = nm.group(1)
            cur_mid = None

print(f"  -> {len(move_display)} move display names parsed", flush=True)


# ── 3. Inheritance resolution ─────────────────────────────────────────────────
def get_base_poke_id(poke_id: str):
    """Find the longest prefix of poke_id that exists with actual moves."""
    for length in range(len(poke_id) - 1, 2, -1):
        candidate = poke_id[:length]
        if candidate in learnsets_data and learnsets_data[candidate]["moves"]:
            return candidate
    return None


def get_full_moves(poke_id: str) -> list:
    """Get complete move set, resolving up to 2 levels of inheritance."""
    if poke_id not in learnsets_data:
        return []
    entry = learnsets_data[poke_id]
    own = set(entry["moves"])
    if entry["inherit"]:
        base = get_base_poke_id(poke_id)
        if base and base in learnsets_data:
            b_entry = learnsets_data[base]
            own |= set(b_entry["moves"])
            if b_entry["inherit"]:
                b2 = get_base_poke_id(base)
                if b2 and b2 in learnsets_data:
                    own |= set(learnsets_data[b2]["moves"])
    return list(own)


# ── 4. Name -> Showdown ID ─────────────────────────────────────────────────────
HARD_OVERRIDES = {
    # Special chars / punctuation
    "type: null":           "typenull",
    "type null":            "typenull",
    "zygarde 10%":          "zygarde10",
    "mr. mime":             "mrmime",
    "mime jr.":             "mimejr",
    "mr. rime":             "mrrime",
    "farfetch'd":           "farfetchd",
    "sirfetch'd":           "sirfetchd",
    "flabébé":              "flabebe",
    "ho-oh":                "hooh",
    # Double-hyphen chains
    "jangmo-o":             "jangmoo",
    "hakamo-o":             "hakamoo",
    "kommo-o":              "kommoo",
    "porygon-z":            "porygonz",
    # Rider / fused forms
    "calyrex-ice-rider":    "calyrexice",
    "calyrex-shadow-rider": "calyrexshadow",
    "necrozma-dusk-mane":   "necrozmaduskmane",
    "necrozma-dawn-wings":  "necrozmadawnwings",
    "urshifu-rapid-strike": "urshifurapidstrike",
    "urshifu-single-strike":"urshifu",
    # Nidoran gender
    "nidoran-female":       "nidoranf",
    "nidoran-male":         "nidoranm",
    "nidoran♀":             "nidoranf",
    "nidoran♂":             "nidoranm",
    # Eternatus
    "eternamax eternatus":  "eternatuseternamax",
    "eternatus-eternamax":  "eternatuseternamax",
    # Tapu
    "tapu koko":            "tapukoko",
    "tapu lele":            "tapulele",
    "tapu bulu":            "tapubulu",
    "tapu fini":            "tapufini",
    # Paradox mons
    "iron bundle":          "ironbundle",
    "iron hands":           "ironhands",
    "iron jugulis":         "ironjugulis",
    "iron moth":            "ironmoth",
    "iron thorns":          "ironthorns",
    "iron treads":          "irontreads",
    "iron valiant":         "ironvaliant",
    "iron boulder":         "ironboulder",
    "iron crown":           "ironcrown",
    "iron leaves":          "ironleaves",
    "great tusk":           "greattusk",
    "sandy shocks":         "sandyshocks",
    "scream tail":          "screamtail",
    "brute bonnet":         "brutebonnet",
    "flutter mane":         "fluttermane",
    "slither wing":         "slitherwing",
    "roaring moon":         "roaringmoon",
    "walking wake":         "walkingwake",
    "gouging fire":         "gougingfire",
    "raging bolt":          "ragingbolt",
    # Terapagos
    "terapagos-stellar":    "terapagosstellar",
    "terapagos-terastal":   "terapagosterastal",
    # Ogerpon masks
    "ogerpon-wellspring":   "ogerponwellspring",
    "ogerpon-hearthflame":  "ogerponhearthflame",
    "ogerpon-cornerstone":  "ogerponcornerstone",
    # Paldean Tauros
    "paldean tauros":           "taurospaldeacombat",
    "paldean tauros aqua":      "taurospaldeaaqua",
    "paldean tauros blaze":     "taurospaldeablaze",
    # Giratina forms
    "giratina-origin":          "giratinaorigin",
    "giratina-altered":         "giratina",
    # Galarian Mr. Mime — handle before regional prefix strip
    "galarian mr. mime":        "mrmimegalar",
    # Misc league-only labels that map to base mons
    "eevee-starter":            "eevee",
    "pikachu-starter":          "pikachu",
}

REGIONAL_MAP = {
    "alolan ":  "alola",
    "galarian ": "galar",
    "hisuian ":  "hisui",
    "paldean ":  "paldea",
}


def name_to_showdown_id(name: str) -> str:
    lower = name.lower().strip()
    if lower in HARD_OVERRIDES:
        return HARD_OVERRIDES[lower]
    for prefix, suffix in REGIONAL_MAP.items():
        if lower.startswith(prefix):
            base = re.sub(r"[^a-z0-9]", "", lower[len(prefix):])
            return base + suffix
    if lower.startswith("mega "):
        base = re.sub(r"[^a-z0-9]", "", lower[5:])
        return base + "mega"
    if lower.startswith("primal "):
        base = re.sub(r"[^a-z0-9]", "", lower[7:])
        return base + "primal"
    return re.sub(r"[^a-z0-9]", "", lower)


# ── 5. Update the database ────────────────────────────────────────────────────
print("\nConnecting to database ...", flush=True)
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
rows = db.execute("SELECT id, name FROM draft_tiers ORDER BY name").fetchall()
print(f"  -> {len(rows)} Pokémon to process", flush=True)

updates = []
not_found = []

for row in rows:
    name = row["name"]
    sid = name_to_showdown_id(name)
    move_ids = get_full_moves(sid)

    # If nothing found, try stripping form suffix using prefix search
    if not move_ids:
        base = get_base_poke_id(sid)
        if base:
            move_ids = get_full_moves(base)

    if move_ids:
        display = sorted({move_display.get(mid, mid.title()) for mid in move_ids})
        updates.append(("|".join(display), row["id"]))
    else:
        not_found.append((name, sid))

print(f"\nCommitting {len(updates)} updates ...", flush=True)
db.executemany("UPDATE draft_tiers SET moves = ? WHERE id = ?", updates)
db.commit()
db.close()

print(f"\nOK Done.  Updated={len(updates)}  Not-found={len(not_found)}")
if not_found:
    print("\nPokémon not matched in Showdown learnsets:")
    for n, sid in not_found:
        print(f"  {n!r:45s} -> {sid!r}")
