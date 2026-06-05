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
