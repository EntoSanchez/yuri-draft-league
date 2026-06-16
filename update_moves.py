"""
update_moves.py
Fetch full Pokémon Showdown learnsets and update draft_tiers.moves
with every move each Pokémon can ever learn.

DB selection (highest priority first):
  1. --db <path> command-line argument
  2. DB_PATH environment variable  (same var the Flask app reads)
  3. league.db next to this script

On PythonAnywhere the app reads a NESTED path via the WSGI DB_PATH env var:
  /home/zcs55397/yuri-draft-league/yuri-draft-league/league.db
Running this script without --db there would update the WRONG (outer) DB and
changes would never appear on the live site. Always pass --db on PythonAnywhere:
  python update_moves.py --db /home/zcs55397/yuri-draft-league/yuri-draft-league/league.db
"""
import argparse
import os
import pathlib
import re
import sqlite3
import urllib.request

_HERE = pathlib.Path(__file__).parent

_parser = argparse.ArgumentParser(description="Update draft_tiers.moves from Showdown data.")
_parser.add_argument("--db", help="Path to league.db (overrides DB_PATH env var).")
_args, _ = _parser.parse_known_args()

DB_PATH = _args.db or os.environ.get("DB_PATH") or str(_HERE / "league.db")


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


# ── 3. Parse pokedex.ts for pre-evolution chain ───────────────────────────────
print("Fetching pokedex.ts (~1 MB) ...", flush=True)
pokedex_ts = fetch(
    "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/pokedex.ts"
)

# prevo_map: { poke_id -> prevo_id }  (only direct pre-evos)
prevo_map: dict = {}
cur_pdex = None

for line in pokedex_ts.splitlines():
    pm = re.match(r"^\t([a-z0-9]+): \{", line)
    if pm:
        cur_pdex = pm.group(1)
    elif cur_pdex:
        pv = re.match(r'^\t\tprevo: "([^"]+)"', line)
        if pv:
            # Convert display name to Showdown ID (lowercase, alphanumeric only)
            prevo_map[cur_pdex] = re.sub(r"[^a-z0-9]", "", pv.group(1).lower())

print(f"  -> {len(prevo_map)} pre-evolution links parsed", flush=True)


def _prevo_chain(poke_id: str) -> list:
    """Return list of pre-evolution IDs from immediate prevo up to base form."""
    chain = []
    cur = poke_id
    seen = set()
    while True:
        prv = prevo_map.get(cur)
        if not prv or prv in seen:
            break
        chain.append(prv)
        seen.add(prv)
        cur = prv
    return chain


# ── 4. Inheritance resolution ─────────────────────────────────────────────────
def get_base_poke_id(poke_id: str):
    """Find the longest prefix of poke_id that exists with actual moves."""
    for length in range(len(poke_id) - 1, 2, -1):
        candidate = poke_id[:length]
        if candidate in learnsets_data and learnsets_data[candidate]["moves"]:
            return candidate
    return None


def get_full_moves(poke_id: str) -> list:
    """Get complete move set: own moves + same-poke gen inheritance + prevo chain."""
    if poke_id not in learnsets_data:
        return []
    entry = learnsets_data[poke_id]
    own = set(entry["moves"])

    # Same-species gen-to-gen inheritance (e.g. regional forms)
    if entry["inherit"]:
        base = get_base_poke_id(poke_id)
        if base and base in learnsets_data:
            b_entry = learnsets_data[base]
            own |= set(b_entry["moves"])
            if b_entry["inherit"]:
                b2 = get_base_poke_id(base)
                if b2 and b2 in learnsets_data:
                    own |= set(learnsets_data[b2]["moves"])

    # Pre-evolution chain — captures moves only available on earlier stages
    # (e.g. Incineroar gets Parting Shot via Litten, Lopunny gets Fake Out via Buneary)
    for prv_id in _prevo_chain(poke_id):
        if prv_id in learnsets_data:
            prv_moves = get_full_moves.__wrapped__(prv_id)
            own |= set(prv_moves)

    return list(own)


# Wrap to avoid infinite recursion on prevo chain
_orig_get_full_moves = get_full_moves
def get_full_moves(poke_id: str) -> list:
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
    for prv_id in _prevo_chain(poke_id):
        if prv_id in learnsets_data:
            prv = learnsets_data[prv_id]
            own |= set(prv["moves"])
            # one more level up (e.g. base -> mid -> final)
            if prv["inherit"]:
                pb = get_base_poke_id(prv_id)
                if pb and pb in learnsets_data:
                    own |= set(learnsets_data[pb]["moves"])
    return list(own)


# ── 5. Name -> Showdown ID ─────────────────────────────────────────────────────
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


# ── 6. Manual additions for known Showdown learnset gaps ──────────────────────
# Keys are Showdown IDs; values are display-name moves to always add.
# Only needed when Showdown's learnsets.ts omits a verifiable competitive move.
MOVE_ADDITIONS: dict = {
    # Sneasel/Weavile: Parting Shot via chain breed (Pangoro → Sneasel egg)
    "sneasel":       ["Parting Shot"],
    "sneaselhisui":  ["Parting Shot"],
    "weavile":       ["Parting Shot"],
    # Jigglypuff line: Follow Me is a level-up move missing from Showdown data
    "igglybuff":     ["Follow Me"],
    "jigglypuff":    ["Follow Me"],
    "wigglytuff":    ["Follow Me"],
}


# ── 7. Update the database ────────────────────────────────────────────────────
print(f"\nConnecting to database ...\n  DB_PATH = {DB_PATH}", flush=True)
if not os.path.exists(DB_PATH):
    raise SystemExit(f"ERROR: database not found at {DB_PATH}\n"
                     f"Pass the correct path with --db (on PythonAnywhere this is the NESTED league.db).")
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
        # Merge any manual additions for this Pokémon
        extras = MOVE_ADDITIONS.get(sid, [])
        if extras:
            display = sorted(set(display) | set(extras))
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
