"""Shared Showdown replay parsing logic used by both app.py and scripts/parse_replay.py."""

import json
import re
import urllib.request


def _norm(name: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", name).strip()


def _slot_player(slot: str) -> str:
    return slot[:2]


def _extract_slot(s: str) -> str:
    m = re.match(r"(p[12][ab])", s.strip())
    return m.group(1) if m else ""


def _extract_name(s: str) -> str:
    """'p1a: Torkoal' → 'Torkoal'; 'Torkoal, L50, F' → 'Torkoal'."""
    if ": " in s:
        return _norm(s.split(": ", 1)[1].strip())
    return _norm(s.split(",")[0].strip())


def fetch_replay(url: str) -> dict:
    url = url.rstrip("/")
    if not url.endswith(".json"):
        url += ".json"
    req = urllib.request.Request(url, headers={"User-Agent": "yuri-league/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def parse_log(log: str) -> dict:
    """
    Parse a Showdown battle log string.

    Returns:
        {
          'p1': {'username': str, 'pokemon_used': list[str]},
          'p2': {'username': str, 'pokemon_used': list[str]},
          'kills':  {'p1': {name: int}, 'p2': {name: int}},
          'deaths': {'p1': {name: int}, 'p2': {name: int}},
          'winner_player': 'p1' | 'p2' | None,
        }
    """
    players = {}
    active = {}
    used = {"p1": set(), "p2": set()}
    last_hit_by = {}
    kills  = {"p1": {}, "p2": {}}
    deaths = {"p1": {}, "p2": {}}
    winner_player = None

    for raw in log.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        cmd = parts[1]

        if cmd == "player" and len(parts) >= 4:
            pkey = parts[2]
            if pkey in ("p1", "p2"):
                players[pkey] = parts[3].strip()

        elif cmd in ("switch", "drag", "replace") and len(parts) >= 4:
            slot = _extract_slot(parts[2])
            # Use slot-descriptor name so mega-evolved forms stay as base name.
            poke_name = _extract_name(parts[2])
            if slot and poke_name:
                active[slot] = poke_name
                used[_slot_player(slot)].add(poke_name)

        elif cmd in ("detailschange", "-formechange"):
            # Intentionally ignored — kills/deaths stay attributed to base name.
            pass

        elif cmd == "move" and len(parts) >= 5:
            atk_slot = _extract_slot(parts[2])
            atk_name = active.get(atk_slot) or _extract_name(parts[2])
            if not (atk_slot and atk_name):
                continue
            atk_player = _slot_player(atk_slot)
            primary = _extract_slot(parts[4]) if len(parts) > 4 else ""
            targets = set()
            if primary and primary != atk_slot:
                targets.add(primary)
            rest = "|".join(parts[5:]) if len(parts) > 5 else ""
            spread_m = re.search(r"\[spread\]\s*([p12ab,]+)", rest)
            if spread_m:
                for s in spread_m.group(1).split(","):
                    sm = re.match(r"(p[12][ab])", s.strip())
                    if sm:
                        targets.add(sm.group(1))
            for tgt in targets:
                last_hit_by[tgt] = (atk_player, atk_name)

        elif cmd == "-damage" and len(parts) >= 3:
            victim_slot = _extract_slot(parts[2])
            if not victim_slot:
                continue
            rest = "|".join(parts[3:])
            of_m = re.search(r"\[of\]\s*(p[12][ab]):\s*(.+)", rest)
            if of_m:
                src_slot = of_m.group(1)
                src_name = _norm(of_m.group(2).strip().split(",")[0])
                last_hit_by[victim_slot] = (_slot_player(src_slot), src_name)

        elif cmd == "faint" and len(parts) >= 3:
            slot = _extract_slot(parts[2])
            if not slot:
                continue
            fainted = active.get(slot) or _extract_name(parts[2])
            fplayer = _slot_player(slot)
            if fainted:
                d = deaths[fplayer]
                d[fainted] = d.get(fainted, 0) + 1
                killer = last_hit_by.get(slot)
                if killer:
                    kplayer, kname = killer
                    k = kills[kplayer]
                    k[kname] = k.get(kname, 0) + 1
            active.pop(slot, None)

        elif cmd == "win" and len(parts) >= 3:
            winner_uname = parts[2].strip()
            for pkey, uname in players.items():
                if uname.lower() == winner_uname.lower():
                    winner_player = pkey
                    break

    return {
        "p1": {"username": players.get("p1", ""), "pokemon_used": sorted(used["p1"])},
        "p2": {"username": players.get("p2", ""), "pokemon_used": sorted(used["p2"])},
        "kills": kills,
        "deaths": deaths,
        "winner_player": winner_player,
    }


def resolve_poke_name(raw: str, roster: list) -> str:
    """Map a Showdown slot name to the closest entry in the coach's roster.

    Handles base↔mega mismatches, e.g.:
      'Gallade'   + roster has 'Gallade-Mega'   → 'Gallade-Mega'
      'Charizard' + roster has 'Charizard-Mega-X' → 'Charizard-Mega-X'
    Returns raw unchanged if roster is empty or no match found.
    """
    if not roster:
        return raw
    by_lower = {n.lower(): n for n in roster}
    if raw.lower() in by_lower:
        return by_lower[raw.lower()]
    for suffix in ("-Mega", "-Mega-X", "-Mega-Y"):
        cand = raw + suffix
        if cand.lower() in by_lower:
            return by_lower[cand.lower()]
    for suffix in ("-Mega-X", "-Mega-Y", "-Mega"):
        if raw.lower().endswith(suffix.lower()):
            base = raw[: -len(suffix)]
            if base.lower() in by_lower:
                return by_lower[base.lower()]
    return raw


def remap_dict(d: dict, name_map: dict) -> dict:
    out = {}
    for mon, val in d.items():
        canon = name_map.get(mon, mon)
        out[canon] = out.get(canon, 0) + val
    return out


# ── Type palette ──────────────────────────────────────────────────────────────
TYPE_COLORS = {
    "Dragon": "#7b6cff", "Ground": "#d9a441", "Flying": "#7fb8ff",
    "Ghost": "#9a6cff", "Steel": "#a7b3c4", "Dark": "#7a6f8a",
    "Fighting": "#ff7a59", "Fairy": "#ff8fd0", "Electric": "#ffd23d",
    "Water": "#3da5ff", "Fire": "#ff6a4d", "Grass": "#7ddc6a",
    "Poison": "#c06cff", "Rock": "#d2b06a", "Bug": "#b7d63d",
    "Ice": "#7fe8e0", "Psychic": "#ff6fa3", "Normal": "#c9c9d2",
}

TYPEDEX = {
    # Starters / fan-favourites
    "Charizard": ["Fire","Flying"], "Blastoise": ["Water"],
    "Venusaur": ["Grass","Poison"], "Mewtwo": ["Psychic"],
    "Mew": ["Psychic"], "Alakazam": ["Psychic"],
    "Gengar": ["Ghost","Poison"], "Gyarados": ["Water","Flying"],
    "Eevee": ["Normal"], "Pikachu": ["Electric"], "Raichu": ["Electric"],
    # Megas
    "Charizard-Mega-X": ["Fire","Dragon"], "Charizard-Mega-Y": ["Fire","Flying"],
    "Mewtwo-Mega-X": ["Psychic","Fighting"], "Mewtwo-Mega-Y": ["Psychic"],
    "Gallade-Mega": ["Psychic","Fighting"], "Gardevoir-Mega": ["Psychic","Fairy"],
    "Blaziken-Mega": ["Fire","Fighting"], "Garchomp-Mega": ["Dragon","Ground"],
    "Salamence-Mega": ["Dragon","Flying"], "Altaria-Mega": ["Dragon","Fairy"],
    "Swampert-Mega": ["Water","Ground"], "Sceptile-Mega": ["Grass","Dragon"],
    "Manectric-Mega": ["Electric"], "Beedrill-Mega": ["Bug","Poison"],
    "Scizor-Mega": ["Bug","Steel"], "Heracross-Mega": ["Bug","Fighting"],
    "Aggron-Mega": ["Steel"], "Ampharos-Mega": ["Electric","Dragon"],
    "Lucario-Mega": ["Fighting","Steel"], "Kangaskhan-Mega": ["Normal"],
    "Lopunny-Mega": ["Normal","Fighting"], "Latias-Mega": ["Dragon","Psychic"],
    "Latios-Mega": ["Dragon","Psychic"], "Diancie-Mega": ["Rock","Fairy"],
    "Pidgeot-Mega": ["Normal","Flying"], "Slowbro-Mega": ["Water","Psychic"],
    "Camerupt-Mega": ["Fire","Ground"], "Houndoom-Mega": ["Dark","Fire"],
    "Sharpedo-Mega": ["Water","Dark"], "Tyranitar-Mega": ["Rock","Dark"],
    "Steelix-Mega": ["Steel","Ground"], "Venusaur-Mega": ["Grass","Poison"],
    "Blastoise-Mega": ["Water"], "Banette-Mega": ["Ghost"],
    "Sableye-Mega": ["Dark","Ghost"], "Mawile-Mega": ["Steel","Fairy"],
    "Medicham-Mega": ["Fighting","Psychic"], "Glalie-Mega": ["Ice"],
    "Audino-Mega": ["Normal","Fairy"], "Abomasnow-Mega": ["Grass","Ice"],
    "Gengar-Mega": ["Ghost","Poison"], "Gyarados-Mega": ["Water","Dark"],
    # Gen 4/5
    "Garchomp": ["Dragon","Ground"], "Lucario": ["Fighting","Steel"],
    "Togekiss": ["Fairy","Flying"], "Infernape": ["Fire","Fighting"],
    "Empoleon": ["Water","Steel"], "Torterra": ["Grass","Ground"],
    "Rotom-Wash": ["Electric","Water"], "Rotom-Heat": ["Electric","Fire"],
    "Rotom-Frost": ["Electric","Ice"], "Rotom-Fan": ["Electric","Flying"],
    "Rotom-Mow": ["Electric","Grass"], "Rotom": ["Electric","Ghost"],
    "Hydreigon": ["Dark","Dragon"], "Volcarona": ["Bug","Fire"],
    "Haxorus": ["Dragon"], "Krookodile": ["Ground","Dark"],
    "Chandelure": ["Ghost","Fire"], "Excadrill": ["Ground","Steel"],
    "Conkeldurr": ["Fighting"], "Ferrothorn": ["Grass","Steel"],
    "Jellicent": ["Water","Ghost"], "Reuniclus": ["Psychic"],
    # Gen 6
    "Greninja": ["Water","Dark"], "Talonflame": ["Fire","Flying"],
    "Sylveon": ["Fairy"], "Chesnaught": ["Grass","Fighting"],
    "Delphox": ["Fire","Psychic"], "Goodra": ["Dragon"],
    "Clefable": ["Fairy"], "Aegislash": ["Steel","Ghost"],
    "Klefki": ["Steel","Fairy"], "Noivern": ["Flying","Dragon"],
    "Avalugg": ["Ice"], "Pangoro": ["Fighting","Dark"],
    # Gen 7
    "Primarina": ["Water","Fairy"], "Incineroar": ["Fire","Dark"],
    "Decidueye": ["Grass","Ghost"], "Mimikyu": ["Ghost","Fairy"],
    "Alolan Raichu": ["Electric","Psychic"], "Mudsdale": ["Ground"],
    "Araquanid": ["Water","Bug"], "Toxapex": ["Poison","Water"],
    "Kommo-o": ["Dragon","Fighting"], "Tapu Koko": ["Electric","Fairy"],
    "Tapu Lele": ["Psychic","Fairy"], "Tapu Bulu": ["Grass","Fairy"],
    "Tapu Fini": ["Water","Fairy"], "Nihilego": ["Rock","Poison"],
    "Buzzwole": ["Bug","Fighting"], "Pheromosa": ["Bug","Fighting"],
    "Kartana": ["Grass","Steel"], "Celesteela": ["Steel","Flying"],
    "Guzzlord": ["Dark","Dragon"],
    # Gen 8
    "Dragapult": ["Dragon","Ghost"], "Dragovich": ["Dragon"],
    "Corviknight": ["Flying","Steel"], "Grimmsnarl": ["Dark","Fairy"],
    "Cinderace": ["Fire"], "Rillaboom": ["Grass"], "Inteleon": ["Water"],
    "Appletun": ["Grass","Dragon"], "Frosmoth": ["Ice","Bug"],
    "Obstagoon": ["Dark","Normal"], "Dracovish": ["Water","Dragon"],
    "Dracozolt": ["Electric","Dragon"], "Arctovish": ["Water","Ice"],
    "Arctozolt": ["Ice","Electric"], "Runerigus": ["Ground","Ghost"],
    "Cursola": ["Ghost"], "Milcery": ["Fairy"], "Alcremie": ["Fairy"],
    "Indeedee": ["Psychic","Normal"], "Morpeko": ["Electric","Dark"],
    "Cufant": ["Steel"], "Galarian Weezing": ["Poison","Fairy"],
    "Galarian Rapidash": ["Psychic","Fairy"],
    "Calyrex": ["Psychic","Grass"], "Spectrier": ["Ghost"],
    "Glastrier": ["Ice"], "Kubfu": ["Fighting"],
    "Urshifu": ["Fighting","Dark"], "Zarude": ["Dark","Grass"],
    "Regieleki": ["Electric"], "Regidrago": ["Dragon"],
    "Iron Hands": ["Fighting","Electric"],
    # Gen 9
    "Sprigatito": ["Grass"], "Fuecoco": ["Fire"], "Quaxly": ["Water"],
    "Meowscarada": ["Grass","Dark"], "Skeledirge": ["Fire","Ghost"],
    "Quaquaval": ["Water","Fighting"], "Lechonk": ["Normal"],
    "Maushold": ["Normal"], "Fidough": ["Fairy"], "Dachsbun": ["Fairy"],
    "Smoliv": ["Grass","Normal"], "Arboliva": ["Grass","Normal"],
    "Squawkabilly": ["Normal","Flying"], "Nacli": ["Rock"],
    "Garganacl": ["Rock"], "Charcadet": ["Fire"], "Armarouge": ["Fire","Psychic"],
    "Ceruledge": ["Fire","Ghost"], "Hatenna": ["Psychic"],
    "Hattrem": ["Psychic"], "Hatterene": ["Psychic","Fairy"],
    "Bellibolt": ["Electric"], "Wattrel": ["Electric","Flying"],
    "Kilowattrel": ["Electric","Flying"], "Maschiff": ["Dark"],
    "Mabosstiff": ["Dark"], "Shroodle": ["Poison","Normal"],
    "Grafaiai": ["Poison","Normal"], "Bramblin": ["Grass","Ghost"],
    "Brambleghast": ["Grass","Ghost"], "Toedscool": ["Ground","Grass"],
    "Toedscruel": ["Ground","Grass"], "Klawf": ["Rock"],
    "Capsakid": ["Grass"], "Scovillain": ["Grass","Fire"],
    "Rellor": ["Bug"], "Rabsca": ["Bug","Psychic"],
    "Flittle": ["Psychic"], "Espathra": ["Psychic"],
    "Tinkatink": ["Fairy","Steel"], "Tinkatuff": ["Fairy","Steel"],
    "Tinkaton": ["Fairy","Steel"], "Wiglett": ["Water"],
    "Wugtrio": ["Water"], "Bombirdier": ["Flying","Dark"],
    "Finizen": ["Water"], "Palafin": ["Water"],
    "Varoom": ["Steel","Poison"], "Revavroom": ["Steel","Poison"],
    "Cyclizar": ["Dragon","Normal"], "Orthworm": ["Steel"],
    "Glimmet": ["Rock","Poison"], "Glimmora": ["Rock","Poison"],
    "Greavard": ["Ghost"], "Houndstone": ["Ghost"],
    "Flamigo": ["Flying","Fighting"], "Cetoddle": ["Ice"],
    "Cetitan": ["Ice"], "Veluza": ["Water","Psychic"],
    "Dondozo": ["Water"], "Tatsugiri": ["Dragon","Water"],
    "Annihilape": ["Fighting","Ghost"], "Clodsire": ["Poison","Ground"],
    "Farigiraf": ["Normal","Psychic"], "Dudunsparce": ["Normal"],
    "Kingambit": ["Dark","Steel"], "Great Tusk": ["Ground","Fighting"],
    "Scream Tail": ["Fairy","Psychic"], "Brute Bonnet": ["Grass","Dark"],
    "Flutter Mane": ["Ghost","Fairy"], "Slither Wing": ["Bug","Fighting"],
    "Sandy Shocks": ["Electric","Ground"], "Iron Treads": ["Ground","Steel"],
    "Iron Bundle": ["Ice","Water"], "Iron Jugulis": ["Dark","Flying"],
    "Iron Moth": ["Fire","Poison"], "Iron Thorns": ["Rock","Electric"],
    "Frigibax": ["Dragon","Ice"], "Arctibax": ["Dragon","Ice"],
    "Baxcalibur": ["Dragon","Ice"], "Gimmighoul": ["Ghost"],
    "Gholdengo": ["Steel","Ghost"], "Wo-Chien": ["Dark","Grass"],
    "Chien-Pao": ["Dark","Ice"], "Ting-Lu": ["Dark","Ground"],
    "Chi-Yu": ["Dark","Fire"], "Roaring Moon": ["Dragon","Dark"],
    "Iron Valiant": ["Fairy","Fighting"], "Koraidon": ["Fighting","Dragon"],
    "Miraidon": ["Electric","Dragon"], "Walking Wake": ["Water","Dragon"],
    "Iron Leaves": ["Grass","Psychic"], "Dipplin": ["Grass","Dragon"],
    "Poltchageist": ["Grass","Ghost"], "Sinistcha": ["Grass","Ghost"],
    "Okidogi": ["Poison","Fighting"], "Munkidori": ["Poison","Psychic"],
    "Fezandipiti": ["Poison","Fairy"], "Ogerpon": ["Grass"],
    "Ogerpon-Hearthflame": ["Grass","Fire"], "Ogerpon-Wellspring": ["Grass","Water"],
    "Ogerpon-Cornerstone": ["Grass","Rock"],
    "Archaludon": ["Steel","Dragon"], "Hydrapple": ["Grass","Dragon"],
    "Gouging Fire": ["Fire","Dragon"], "Raging Bolt": ["Electric","Dragon"],
    "Iron Boulder": ["Rock","Psychic"], "Iron Crown": ["Steel","Psychic"],
    "Terapagos": ["Normal"], "Pecharunt": ["Poison","Ghost"],
    # Common league mons
    "Garchomp": ["Dragon","Ground"], "Salamence": ["Dragon","Flying"],
    "Dragonite": ["Dragon","Flying"], "Tyranitar": ["Rock","Dark"],
    "Kingdra": ["Water","Dragon"], "Whimsicott": ["Grass","Fairy"],
    "Gallade": ["Psychic","Fighting"], "Gardevoir": ["Psychic","Fairy"],
    "Blaziken": ["Fire","Fighting"], "Swampert": ["Water","Ground"],
    "Sceptile": ["Grass"], "Venusaur": ["Grass","Poison"],
    "Machamp": ["Fighting"], "Golem": ["Rock","Ground"],
    "Slowbro": ["Water","Psychic"], "Slowking": ["Water","Psychic"],
    "Cloyster": ["Water","Ice"], "Starmie": ["Water","Psychic"],
    "Gengar": ["Ghost","Poison"], "Haunter": ["Ghost","Poison"],
    "Jolteon": ["Electric"], "Flareon": ["Fire"], "Vaporeon": ["Water"],
    "Espeon": ["Psychic"], "Umbreon": ["Dark"],
    "Scizor": ["Bug","Steel"], "Heracross": ["Bug","Fighting"],
    "Suicune": ["Water"], "Raikou": ["Electric"], "Entei": ["Fire"],
    "Lugia": ["Psychic","Flying"], "Ho-Oh": ["Fire","Flying"],
    "Azumarill": ["Water","Fairy"], "Politoed": ["Water"],
    "Feraligatr": ["Water"], "Typhlosion": ["Fire"], "Meganium": ["Grass"],
    "Ampharos": ["Electric"], "Umbreon": ["Dark"], "Espeon": ["Psychic"],
    "Steelix": ["Steel","Ground"], "Skarmory": ["Steel","Flying"],
    "Houndoom": ["Dark","Fire"], "Blissey": ["Normal"],
    "Swellow": ["Normal","Flying"], "Shedinja": ["Bug","Ghost"],
    "Hariyama": ["Fighting"], "Ninjask": ["Bug","Flying"],
    "Absol": ["Dark"], "Altaria": ["Dragon","Flying"],
    "Camerupt": ["Fire","Ground"], "Sharpedo": ["Water","Dark"],
    "Wailord": ["Water"], "Flygon": ["Ground","Dragon"],
    "Breloom": ["Grass","Fighting"], "Slaking": ["Normal"],
    "Medicham": ["Fighting","Psychic"], "Manectric": ["Electric"],
    "Milotic": ["Water"], "Tropius": ["Grass","Flying"],
    "Whiscash": ["Water","Ground"], "Torkoal": ["Fire"],
    "Metagross": ["Steel","Psychic"], "Latias": ["Dragon","Psychic"],
    "Latios": ["Dragon","Psychic"], "Groudon": ["Ground"],
    "Kyogre": ["Water"], "Rayquaza": ["Dragon","Flying"],
    "Jirachi": ["Steel","Psychic"], "Deoxys": ["Psychic"],
    "Gastrodon": ["Water","Ground"], "Lumineon": ["Water"],
    "Empoleon": ["Water","Steel"], "Infernape": ["Fire","Fighting"],
    "Floatzel": ["Water"], "Purugly": ["Normal"],
    "Roserade": ["Grass","Poison"], "Ambipom": ["Normal"],
    "Drifblim": ["Ghost","Flying"], "Lopunny": ["Normal"],
    "Mismagius": ["Ghost"], "Honchkrow": ["Dark","Flying"],
    "Spiritomb": ["Ghost","Dark"], "Hippowdon": ["Ground"],
    "Hippopotas": ["Ground"], "Drapion": ["Poison","Dark"],
    "Lucario": ["Fighting","Steel"], "Abomasnow": ["Grass","Ice"],
    "Weavile": ["Dark","Ice"], "Magnezone": ["Electric","Steel"],
    "Togekiss": ["Fairy","Flying"], "Yanmega": ["Bug","Flying"],
    "Leafeon": ["Grass"], "Glaceon": ["Ice"], "Gliscor": ["Ground","Flying"],
    "Mamoswine": ["Ice","Ground"], "Porygon-Z": ["Normal"],
    "Gallade": ["Psychic","Fighting"], "Probopass": ["Rock","Steel"],
    "Dusknoir": ["Ghost"], "Froslass": ["Ice","Ghost"],
    "Rotom": ["Electric","Ghost"], "Cresselia": ["Psychic"],
    "Darkrai": ["Dark"], "Shaymin": ["Grass"], "Arceus": ["Normal"],
    "Landorus": ["Ground","Flying"], "Thundurus": ["Electric","Flying"],
    "Tornadus": ["Flying"], "Reshiram": ["Dragon","Fire"],
    "Zekrom": ["Dragon","Electric"], "Kyurem": ["Dragon","Ice"],
    "Kyurem-Black": ["Dragon","Ice"], "Kyurem-White": ["Dragon","Ice"],
    "Keldeo": ["Water","Fighting"], "Meloetta": ["Normal","Psychic"],
    "Genesect": ["Bug","Steel"],
    # Gen 6 extras
    "Clefable": ["Fairy"], "Azumarill": ["Water","Fairy"],
    "Mawile": ["Steel","Fairy"], "Dedenne": ["Electric","Fairy"],
    "Florges": ["Fairy"], "Aromatisse": ["Fairy"],
    "Slurpuff": ["Fairy"], "Whimsicott": ["Grass","Fairy"],
    "Gardevoir": ["Psychic","Fairy"], "Togekiss": ["Fairy","Flying"],
    "Sylveon": ["Fairy"], "Ribombee": ["Bug","Fairy"],
    "Ninetales-Alola": ["Ice","Fairy"], "Mimikyu": ["Ghost","Fairy"],
    "Comfey": ["Fairy"], "Tapu Koko": ["Electric","Fairy"],
    "Hawlucha": ["Fighting","Flying"], "Trevenant": ["Ghost","Grass"],
    "Goodra": ["Dragon"], "Noivern": ["Flying","Dragon"],
    "Zygarde": ["Dragon","Ground"], "Diancie": ["Rock","Fairy"],
    "Hoopa": ["Psychic","Ghost"], "Volcanion": ["Fire","Water"],
    # Others
    "Urshifu-Rapid-Strike": ["Fighting","Water"],
    "Calyrex-Shadow": ["Psychic","Ghost"], "Calyrex-Ice": ["Psychic","Ice"],
    "Eternatus": ["Poison","Dragon"], "Zacian": ["Fairy"],
    "Zacian-Crowned": ["Fairy","Steel"], "Zamazenta": ["Fighting"],
    "Zamazenta-Crowned": ["Fighting","Steel"],
    "Nihilego": ["Rock","Poison"], "Poipole": ["Poison"],
    "Naganadel": ["Poison","Dragon"], "Stakataka": ["Rock","Steel"],
    "Blacephalon": ["Fire","Ghost"], "Zeraora": ["Electric"],
    "Marshadow": ["Fighting","Ghost"], "Magearna": ["Steel","Fairy"],
    "Necrozma": ["Psychic"], "Solgaleo": ["Psychic","Steel"],
    "Lunala": ["Psychic","Ghost"],
    "Necrozma-Dusk-Mane": ["Psychic","Steel"],
    "Necrozma-Dawn-Wings": ["Psychic","Ghost"],
    "Cosmog": ["Psychic"], "Cosmoem": ["Psychic"],
    "Incineroar": ["Fire","Dark"],
    "Galarian Slowbro": ["Poison","Psychic"],
    "Galarian Slowking": ["Poison","Psychic"],
}


def _type_color(t: str) -> str:
    return TYPE_COLORS.get(t, "#c9c9d2")


def _norm_forme(name: str) -> str:
    """Strip cosmetic/forme suffixes that don't change in-battle identity.
    Mirrors normName() in replay-parser.js."""
    name = re.sub(r"-Mega(-[XY])?$", "", name)
    name = re.sub(r"-(Hearthflame|Wellspring|Cornerstone|Teal)(-Tera)?$", "", name)
    name = re.sub(r"-Tera$", "", name)
    return name


def _mon_types(name: str, extra_typedex: dict = None) -> list:
    td = TYPEDEX
    if extra_typedex:
        td = dict(td)
        td.update(extra_typedex)
    return td.get(name, ["Normal"])


def parse_log_recap(log: str) -> dict:
    """Extended log parse that captures turn numbers, moves, super-effective flags,
    and team-preview rosters — everything needed to build the Match Recap page.

    Returns a dict with all raw data; call build_recap() to get the FEATURED shape.
    """
    players = {}
    rating_from = {}
    rating_to = {}
    rosters = {"p1": [], "p2": []}   # team-preview order
    brought = {"p1": set(), "p2": set()}
    active = {}                       # slot → name
    turn = 0
    cur_move = None                   # {side, user, move}
    pending_se = {}                   # slot → bool
    last_hit = {}                     # slot → {bySide, by, move, se, indirect}
    ko_log = []                       # raw chronological faints
    winner_player = None
    leads = {"p1": [], "p2": []}      # first 2 switch-ins per side before turn 2
    _leads_locked = {"p1": False, "p2": False}

    for raw in log.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) < 2:
            continue
        cmd = parts[1]

        if cmd == "player" and len(parts) >= 4:
            pkey = parts[2]
            if pkey in ("p1", "p2"):
                players[pkey] = parts[3].strip()

        elif cmd == "poke" and len(parts) >= 4:
            pside = parts[2]
            if pside in ("p1", "p2"):
                name = _norm_forme(_norm(parts[3].split(",")[0].strip()))
                if name not in rosters[pside]:
                    rosters[pside].append(name)

        elif cmd == "turn":
            turn = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else turn
            if turn >= 2:
                _leads_locked["p1"] = True
                _leads_locked["p2"] = True

        elif cmd in ("switch", "drag", "replace") and len(parts) >= 4:
            slot = _extract_slot(parts[2])
            poke_name = _extract_name(parts[2])
            if slot and poke_name:
                active[slot] = poke_name
                pside = _slot_player(slot)
                brought[pside].add(poke_name)
                if not _leads_locked[pside] and poke_name not in leads[pside]:
                    leads[pside].append(poke_name)

        elif cmd in ("detailschange", "-formechange"):
            pass  # stay with base name

        elif cmd == "move" and len(parts) >= 3:
            atk_slot = _extract_slot(parts[2])
            atk_name = active.get(atk_slot) or _extract_name(parts[2])
            if atk_slot and atk_name:
                atk_side = _slot_player(atk_slot)
                move_name = parts[3].strip() if len(parts) >= 4 else "?"
                cur_move = {"side": atk_side, "user": atk_name, "move": move_name}
                primary = _extract_slot(parts[4]) if len(parts) > 4 else ""
                targets = set()
                if primary and primary != atk_slot:
                    targets.add(primary)
                rest = "|".join(parts[5:]) if len(parts) > 5 else ""
                spread_m = re.search(r"\[spread\]\s*([p12ab,]+)", rest)
                if spread_m:
                    for s in spread_m.group(1).split(","):
                        sm = re.match(r"(p[12][ab])", s.strip())
                        if sm:
                            targets.add(sm.group(1))
                for tgt in targets:
                    last_hit[tgt] = {
                        "bySide": atk_side, "by": atk_name,
                        "move": move_name, "se": False, "indirect": False,
                    }

        elif cmd == "-supereffective" and len(parts) >= 3:
            slot = _extract_slot(parts[2])
            if slot:
                pending_se[slot] = True
                if slot in last_hit:
                    last_hit[slot]["se"] = True

        elif cmd == "-damage" and len(parts) >= 3:
            victim_slot = _extract_slot(parts[2])
            if not victim_slot:
                continue
            rest = "|".join(parts[3:])
            indirect = "[from]" in rest
            if indirect:
                fm = re.search(r"\[from\]\s*([^|]+)", rest)
                source = fm.group(1).strip() if fm else "passive"
                last_hit[victim_slot] = {
                    "bySide": None, "by": None, "move": source,
                    "se": False, "indirect": True,
                }
            elif cur_move:
                is_se = bool(pending_se.get(victim_slot))
                last_hit[victim_slot] = {
                    "bySide": cur_move["side"], "by": cur_move["user"],
                    "move": cur_move["move"], "se": is_se, "indirect": False,
                }
            pending_se[victim_slot] = False

        elif cmd == "faint" and len(parts) >= 3:
            slot = _extract_slot(parts[2])
            if not slot:
                continue
            fainted = active.get(slot) or _extract_name(parts[2])
            fplayer = _slot_player(slot)
            if fainted:
                k = last_hit.get(slot, {})
                ko_log.append({
                    "t": turn,
                    "victimSide": fplayer,
                    "victim": fainted,
                    "by": k.get("by"),
                    "bySide": k.get("bySide"),
                    "move": k.get("move", "?"),
                    "se": bool(k.get("se")),
                    "indirect": bool(k.get("indirect")),
                })
            active.pop(slot, None)

        elif cmd == "win" and len(parts) >= 3:
            winner_uname = parts[2].strip()
            for pkey, uname in players.items():
                if uname.lower() == winner_uname.lower():
                    winner_player = pkey
                    break

        elif cmd == "raw":
            rest = "|".join(parts[2:])
            m = re.search(r"([^|]+)'s rating: (\d+) &rarr; <strong>(\d+)", rest)
            if m:
                rating_from[m.group(1)] = int(m.group(2))
                rating_to[m.group(1)] = int(m.group(3))

        # Also track used mons for fallback kills/deaths
        elif cmd in ("-damage",):
            pass  # already handled above

    # Fallback: ensure used sets include all seen names
    used = {"p1": set(), "p2": set()}
    for entry in ko_log:
        if entry["victimSide"] in used:
            used[entry["victimSide"]].add(entry["victim"])
        if entry["bySide"] and entry["bySide"] in used:
            used[entry["bySide"]].add(entry["by"])
    for pside in ("p1", "p2"):
        used[pside].update(brought[pside])

    return {
        "players": players,
        "rating_from": rating_from,
        "rating_to": rating_to,
        "rosters": rosters,
        "brought": brought,
        "leads": leads,
        "ko_log": ko_log,
        "turns": turn,
        "winner_player": winner_player,
        "used": used,
    }


def build_recap(raw: dict, meta: dict = None, typedex: dict = None,
                name_map_p1: dict = None, name_map_p2: dict = None) -> dict:
    """Convert parse_log_recap() output into the FEATURED-shaped dict the recap page renders.

    name_map_p1 / name_map_p2: {showdown_name: roster_name} — roster-resolved overrides.
    meta: dict of override facts (week, pool, date, format, casters, tag, tagKind, replay, h2h, ...).
    """
    nm = meta or {}
    td = dict(TYPEDEX)
    if typedex:
        td.update(typedex)

    nmap = {
        "p1": name_map_p1 or {},
        "p2": name_map_p2 or {},
    }

    def resolve(pside: str, name: str) -> str:
        return nmap[pside].get(name, name)

    players = raw["players"]
    winner_player = raw["winner_player"] or "p1"
    home_pid = winner_player
    away_pid = "p2" if home_pid == "p1" else "p1"

    # Roster (team-preview, resolve names)
    rosters_resolved = {}
    for pside in ("p1", "p2"):
        rosters_resolved[pside] = [resolve(pside, n) for n in raw["rosters"][pside]]

    # If team-preview roster is empty (random/non-preview battles), fall back to brought
    for pside in ("p1", "p2"):
        if not rosters_resolved[pside]:
            rosters_resolved[pside] = sorted({resolve(pside, n) for n in raw["brought"][pside]})

    # Bring-N-Use-M detection: if fewer mons were switched in than were in team preview,
    # filter the displayed roster to only the mons actually used.
    # e.g. Bring 6 Use 4 — the 2 benched mons never appear and must not inflate "left" count.
    brought_resolved = {
        pside: {resolve(pside, n) for n in raw["brought"][pside]}
        for pside in ("p1", "p2")
    }
    for pside in ("p1", "p2"):
        b = brought_resolved[pside]
        if b and len(b) < len(rosters_resolved[pside]):
            # Keep team-preview order but only for used mons
            rosters_resolved[pside] = [n for n in rosters_resolved[pside] if n in b]
            # Append any used mon not in team preview (rare forme-change edge case)
            for n in sorted(b - set(rosters_resolved[pside])):
                rosters_resolved[pside].append(n)

    # How many mons each side used (4 in bring-6-use-4; 6 in standard 6v6)
    use_counts = {pside: len(rosters_resolved[pside]) for pside in ("p1", "p2")}

    # Build per-mon kill/faint tallies from ko_log
    kills_by_mon = {}    # (pside, name) → count
    fainted_mons = {}    # (pside, name) → bool
    for entry in raw["ko_log"]:
        vs_key = (entry["victimSide"], resolve(entry["victimSide"], entry["victim"]))
        fainted_mons[vs_key] = True
        if not entry["indirect"] and entry["bySide"] and entry["by"]:
            by_key = (entry["bySide"], resolve(entry["bySide"], entry["by"]))
            kills_by_mon[by_key] = kills_by_mon.get(by_key, 0) + 1

    # Leads (resolved)
    leads_resolved = {
        "p1": [resolve("p1", n) for n in raw["leads"]["p1"]],
        "p2": [resolve("p2", n) for n in raw["leads"]["p2"]],
    }

    def build_roster(pside: str) -> list:
        seen = set()
        mons = []
        for name in rosters_resolved[pside]:
            if name in seen:
                continue
            seen.add(name)
            kos = kills_by_mon.get((pside, name), 0)
            fainted = fainted_mons.get((pside, name), False)
            is_lead = name in leads_resolved[pside]
            victims = [
                resolve(e["victimSide"], e["victim"])
                for e in raw["ko_log"]
                if e["bySide"] == pside and resolve(pside, e.get("by") or "") == name
                and not e["indirect"]
            ]
            if kos:
                note = "KO " + ", ".join(victims)
            elif fainted:
                note = "fainted"
            else:
                note = "survived"
            types = td.get(name, ["Normal"])
            mons.append({
                "name": name,
                "types": types,
                "kos": kos,
                "fainted": fainted,
                "lead": is_lead,
                "note": note,
            })
        return mons

    home_roster = build_roster(home_pid)
    away_roster = build_roster(away_pid)

    # KO log in HOME/AWAY terms
    ko_log2 = []
    for entry in raw["ko_log"]:
        side_label = (
            "HOME" if entry["bySide"] == home_pid
            else "AWAY" if entry["bySide"] == away_pid
            else "PASSIVE"
        )
        ko_log2.append({
            "t": entry["t"],
            "side": side_label,
            "by": resolve(entry["bySide"] or home_pid, entry["by"] or "—"),
            "vs": resolve(entry["victimSide"], entry["victim"]),
            "move": entry["move"],
            "se": entry["se"],
            "indirect": entry["indirect"],
            "note": "",
        })

    # Totals
    def _sum_kos(r):
        return sum(m["kos"] for m in r)

    def _left(r):
        return sum(1 for m in r if not m["fainted"])

    def _brought(pside):
        return len({resolve(pside, n) for n in raw["brought"][pside]})

    bring_counts = {
        "home": len(raw["rosters"][home_pid]) or use_counts[home_pid],
        "away": len(raw["rosters"][away_pid]) or use_counts[away_pid],
    }

    totals = {
        "home": {"ko": _sum_kos(home_roster), "left": _left(home_roster),
                 "brought": bring_counts["home"], "used": use_counts[home_pid]},
        "away": {"ko": _sum_kos(away_roster), "left": _left(away_roster),
                 "brought": bring_counts["away"], "used": use_counts[away_pid]},
        "winner": "HOME",
        "diff": abs(_left(home_roster) - _left(away_roster)),
    }

    # Momentum: start at actual mons used (4 for bring-6-use-4, 6 for standard)
    h, a = use_counts[home_pid], use_counts[away_pid]
    momentum = [{"t": 0, "home": h, "away": a, "ko": None}]
    for k in ko_log2:
        if k["side"] == "HOME":
            a -= 1
        elif k["side"] == "AWAY":
            h -= 1
        momentum.append({"t": k["t"], "home": h, "away": a, "ko": k})
    momentum.append({"t": raw["turns"] + 1, "home": h, "away": a, "ko": None})

    # Three stars
    def _victims_of(pside: str, name: str):
        return [
            resolve(e["victimSide"], e["victim"])
            for e in raw["ko_log"]
            if e["bySide"] == pside
            and resolve(pside, e.get("by") or "") == name
            and not e["indirect"]
        ]

    sorted_home = sorted(home_roster, key=lambda m: -m["kos"])
    sorted_away = sorted(away_roster, key=lambda m: -m["kos"])
    s1 = sorted_home[0] if sorted_home else {"name": "—", "types": ["Normal"], "kos": 0, "fainted": False}
    s2 = sorted_away[0] if sorted_away else {"name": "—", "types": ["Normal"], "kos": 0, "fainted": False}
    s3_candidates = [m for m in sorted_home if m["name"] != s1["name"]]
    s3 = s3_candidates[0] if s3_candidates else s1

    home_name = players.get(home_pid, "Home")
    away_name = players.get(away_pid, "Away")

    def _star_blurb1():
        vs = _victims_of(home_pid, s1["name"])
        return f"Match-high {s1['kos']} knockout{'s' if s1['kos'] != 1 else ''} for {home_name} — removed {', '.join(vs) if vs else '—'}."

    def _star_blurb2():
        vs = _victims_of(away_pid, s2["name"])
        return f"Kept {away_name} in it with {s2['kos']} KO{'s' if s2['kos'] != 1 else ''} ({', '.join(vs) if vs else '—'}) before going down."

    def _star_blurb3():
        vs = _victims_of(home_pid, s3["name"])
        if s3["kos"] > 0:
            return f"Added {s3['kos']} KO{'s' if s3['kos'] != 1 else ''}{'' if s3['fainted'] else ' and survived'} — {', '.join(vs)}."
        return "Traded damage and survived." if not s3["fainted"] else "Took hits to keep the team going."

    stars = [
        {"star": 1, "side": "HOME", "mon": {"name": s1["name"], "types": s1["types"]},
         "line": f"{s1['kos']} KO · {'fainted' if s1['fainted'] else 'survived'}",
         "blurb": _star_blurb1()},
        {"star": 2, "side": "AWAY", "mon": {"name": s2["name"], "types": s2["types"]},
         "line": f"{s2['kos']} KO · {'fainted' if s2['fainted'] else 'survived'}",
         "blurb": _star_blurb2()},
        {"star": 3, "side": "HOME", "mon": {"name": s3["name"], "types": s3["types"]},
         "line": f"{s3['kos']} KO · {'fainted' if s3['fainted'] else 'survived'}",
         "blurb": _star_blurb3()},
    ]

    # Auto-detect bring/use for format string
    _bring = max(bring_counts["home"], bring_counts["away"])
    _use   = max(use_counts[home_pid], use_counts[away_pid])
    _is_bring_use = _bring > _use and _use > 0
    _auto_format = (
        f"Bring {_bring} / Use {_use} · Showdown replay"
        if _is_bring_use else "6v6 · Showdown replay"
    )

    # Facts
    facts = {
        "week": nm.get("week", "—"),
        "pool": nm.get("pool", "LADDER"),
        "status": nm.get("status", "FINAL"),
        "date": nm.get("date", ""),
        "format": nm.get("format", _auto_format),
        "turns": raw["turns"],
        "casters": nm.get("casters", []),
        "tag": nm.get("tag", "REPLAY"),
        "tagKind": nm.get("tagKind", "PARSED"),
        "replay": nm.get("replay", ""),
        "bring": _bring,
        "use": _use,
        "replayMode": nm.get("replayMode", True),
        "ratingHome": {
            "from": raw["rating_from"].get(home_name),
            "to": raw["rating_to"].get(home_name),
        },
        "ratingAway": {
            "from": raw["rating_from"].get(away_name),
            "to": raw["rating_to"].get(away_name),
        },
    }

    def _mk_team(pside: str, accent: str) -> dict:
        uname = players.get(pside, pside)
        initials = "".join(w[0] for w in re.sub(r"[^A-Za-z ]", "", uname).split() if w)[:2].upper()
        logo_url = nm.get(f"logo_{accent}")  # None for ladder replays
        return {
            "name": uname,
            "coach": uname,
            "pool": facts["pool"],
            "replay": True,
            "accent": accent,
            "initials": initials or uname[:2].upper(),
            "logo_url": logo_url,
            "id": nm.get(f"id_{accent}"),
        }

    return {
        "home": _mk_team(home_pid, "home"),
        "away": _mk_team(away_pid, "away"),
        "homeRoster": home_roster,
        "awayRoster": away_roster,
        "koLog": ko_log2,
        "momentum": momentum,
        "totals": totals,
        "stars": stars,
        "facts": facts,
        "h2h": nm.get("h2h"),
        "homeRec": nm.get("homeRec", {"w": 0, "l": 0, "t": 0, "df": 0}),
        "awayRec": nm.get("awayRec", {"w": 0, "l": 0, "t": 0, "df": 0}),
    }
