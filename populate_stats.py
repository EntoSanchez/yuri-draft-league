"""
One-shot script: copy base stats from the pokedex table into draft_tiers.
Run once locally and once on PythonAnywhere.
"""
import sqlite3, re, sys

DB = "league.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

dex = db.execute(
    "SELECT display_name, pokeapi_name, hp, atk, def_stat, spa, spd, spe FROM pokedex"
).fetchall()
by_display = {r["display_name"].lower(): r for r in dex}
by_api     = {r["pokeapi_name"].lower(): r for r in dex}

# Manual overrides for forms whose names don't auto-convert
MANUAL = {
    "calyrex-ice-rider":    "calyrex-ice",
    "calyrex-shadow-rider": "calyrex-shadow",
    "giratina":             "giratina-altered",
    "deoxys":               "deoxys-normal",
    "basculin":             "basculin-red-striped",
    "basculegion":          "basculegion-male",
    "necrozma-dawn-wings":  "necrozma-dawn",
    "necrozma-dusk-mane":   "necrozma-dusk",
    "keldeo":               "keldeo-ordinary",
    "nidoran-female":       "nidoran-f",
    "nidoran-male":         "nidoran-m",
    "meloetta":             "meloetta-aria",
    "meowstic":             "meowstic-male",
    "indeedee":             "indeedee-male",
    "morpeko":              "morpeko-full-belly",
    "eiscue":               "eiscue-ice",
    "mimikyu":              "mimikyu-disguised",
    "minior":               "minior-red-meteor",
    "gourgeist":            "gourgeist-average",
    "frillish":             "frillish-male",
    "jellicent":            "jellicent-male",
    "maushold":             "maushold-family-of-four",
    "dudunsparce":          "dudunsparce-two-segment",
    "darmanitan":           "darmanitan-standard",
    "galarian darmanitan":  "darmanitan-galar-standard",
    "galarian farfetch'd":  "farfetchd-galar",
    "eternamax eternatus":  "eternatus-eternamax",
    "mega charizard x":     "charizard-mega-x",
    "mega charizard y":     "charizard-mega-y",
    "mega mewtwo x":            "mewtwo-mega-x",
    "mega mewtwo y":            "mewtwo-mega-y",
    "zygarde":                  "zygarde-50",
    "ogerpon-cornerstone":      "ogerpon",
    "ogerpon-hearthflame":      "ogerpon",
    "ogerpon-wellspring":       "ogerpon-wellspring-mask",
    "oinkologne":               "oinkologne-male",
    "oricorio":                 "oricorio-baile",
    "palafin":                  "palafin-zero",
    "paldean tauros":           "tauros",
    "paldean tauros aqua":      "tauros-paldea-aqua-breed",
    "paldean tauros blaze":     "tauros-paldea-blaze-breed",
    "pichu-spiky-eared":        "pichu",
    "primal groudon":           "groudon-primal",
    "primal kyogre":            "kyogre-primal",
    "pumpkaboo":                "pumpkaboo-average",
    "pyroar":                   "pyroar-male",
    "shaymin":                  "shaymin-land",
    "squawkabilly":             "squawkabilly-green-plumage",
    "tatsugiri":                "tatsugiri-curly",
    "toxtricity":               "toxtricity-amped",
    "wishiwashi":               "wishiwashi-solo",
    "wormadam":                 "wormadam-plant",
}

def to_api(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

def find(name):
    nl = name.lower()
    # manual override
    if nl in MANUAL and MANUAL[nl] in by_api:
        return by_api[MANUAL[nl]]
    # direct display name
    if nl in by_display:
        return by_display[nl]
    # direct api name
    api = to_api(name)
    if api in by_api:
        return by_api[api]
    # regional prefixes
    for prefix, suffix in [
        ("alolan ", "alola"), ("galarian ", "galar"),
        ("hisuian ", "hisui"), ("paldean ", "paldea"),
    ]:
        if nl.startswith(prefix):
            base = to_api(name[len(prefix):])
            key = base + "-" + suffix
            if key in by_api:
                return by_api[key]
    # mega: "mega x" -> "x-mega" or "x-mega-x/y"
    if nl.startswith("mega "):
        base = to_api(name[5:])
        for k in [base + "-mega", base + "-mega-x", base + "-mega-y"]:
            if k in by_api:
                return by_api[k]
    # arceus forms all share stats
    if nl.startswith("arceus") and "arceus" in by_api:
        return by_api["arceus"]
    # eevee variants
    if nl.startswith("eevee") and "eevee" in by_api:
        return by_api["eevee"]
    # aegislash -> shield form
    if nl == "aegislash" and "aegislash-shield" in by_api:
        return by_api["aegislash-shield"]
    return None

tiers = db.execute("SELECT id, name FROM draft_tiers").fetchall()
updates, skipped = [], []

for t in tiers:
    row = find(t["name"])
    if row:
        bst = sum(row[s] or 0 for s in ("hp", "atk", "def_stat", "spa", "spd", "spe"))
        updates.append((
            row["hp"] or 0, row["atk"] or 0, row["def_stat"] or 0,
            row["spa"] or 0, row["spd"] or 0, row["spe"] or 0,
            bst, t["id"]
        ))
    else:
        skipped.append(t["name"])

db.executemany(
    "UPDATE draft_tiers SET hp=?, atk=?, defense=?, spa=?, spd=?, spe=?, bst=? WHERE id=?",
    updates
)
db.commit()

print(f"Updated {len(updates)} / {len(tiers)} Pokémon.")
if skipped:
    print(f"Could not match {len(skipped)}: {skipped}")
