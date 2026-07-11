"""Shared Showdown replay parsing logic used by both app.py and scripts/parse_replay.py."""

import json
import re
import urllib.request


def _norm(name: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", name).strip()


# A mega evolution / primal reversion PERMANENTLY changes which drafted pick a
# slot represents ("Mega Gardevoir" and "Kyogre-Primal" are SEPARATE roster picks
# from their base). Only these suffixes re-attribute kills/deaths on a
# |detailschange|; every other forme change (Aegislash-Blade, Palafin-Hero,
# Mimikyu-Busted, Terapagos-Terastal, Ogerpon-*, …) is the SAME pick and must
# stay unified. -Mega-Z covers Legends Z-A megas (e.g. Absol-Mega-Z).
_MEGA_PRIMAL_RE = re.compile(r"-(?:Mega(?:-[XYZ])?|Primal)$")


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


# Entry-hazard identifiers used to match a hazard-set to its later chip damage.
_HAZARDS = {
    "stealth rock",
    "spikes",
    "toxic spikes",
    "g-max steelsurge",
    "gmax steelsurge",
    "steelsurge",
}


def _hazard_id(s: str) -> str:
    """Normalize a hazard reference ('move: Stealth Rock', 'Stealth Rock') to a
    lowercase id, or '' if it isn't an entry hazard."""
    x = s.strip()
    if x.lower().startswith("move:"):
        x = x.split(":", 1)[1].strip()
    xl = x.lower()
    return xl if xl in _HAZARDS else ""


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
    kills = {"p1": {}, "p2": {}}
    deaths = {"p1": {}, "p2": {}}
    winner_player = None
    # For indirect-KO attribution: who set each hazard on each side, and who
    # inflicted each mon's status. Indirect faints (hazards/poison/burn) are
    # credited to the responsible Pokémon, not to no one.
    hazard_setter = {"p1": {}, "p2": {}}  # side -> {hazard_id: (player, name)}
    status_by = {}  # victim slot -> (player, name)
    last_move_actor = None  # (player, name) of the most recent |move|
    future_move_by = {"p1": None, "p2": None}  # target side -> (player, name) of a
    # pending Future Sight / Doom Desire user
    pending_charge = {}  # victim slot -> (player, name) of a
    # charge-move attacker whose real hit
    # (|-damage|) hasn't landed yet

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
            # parts[2] is "p1a: NICKNAME"; parts[3] is "SPECIES, L50, F" — use the
            # SPECIES so a nicknamed Pokémon's kills/deaths are attributed to the
            # real mon (not the nickname), which the roster leaderboard can match.
            # Fall back to the slot-descriptor name if the species field is absent.
            poke_name = _norm(parts[3].split(",")[0].strip()) or _extract_name(parts[2])
            if slot and poke_name:
                sider = _slot_player(slot)
                if cmd == "replace":
                    # Illusion (Zoroark/Zorua) reveal: the mon that has been in this
                    # slot was actually `poke_name` all along, disguised as the old
                    # `active[slot]`. Move that disguise's kills to the real species
                    # and drop the phantom disguise from this side's used-list.
                    disguise = active.get(slot)
                    if disguise and disguise != poke_name:
                        moved = kills[sider].pop(disguise, 0)
                        if moved:
                            kills[sider][poke_name] = (
                                kills[sider].get(poke_name, 0) + moved
                            )
                        used[sider].discard(disguise)
                active[slot] = poke_name
                used[sider].add(poke_name)
                # A fresh Pokémon occupies this slot — clear any stale attribution
                # (direct last-hit AND inherited status) so it can't wrongly credit
                # whoever acted on the PREVIOUS occupant. Hazard credit persists on
                # the SIDE (hazard_setter), so it survives the switch correctly.
                # (A `replace` reveal keeps the slot's own attribution intact.)
                if cmd != "replace":
                    last_hit_by.pop(slot, None)
                    status_by.pop(slot, None)
                    pending_charge.pop(slot, None)

        elif cmd in ("detailschange", "-formechange") and len(parts) >= 4:
            # Mega/primal permanently re-points this slot to a DIFFERENT drafted
            # pick. Move any kills already scored THIS trip (before the mega
            # evolved) from the base name onto the mega/primal name — mirroring
            # the 'replace' (Illusion) branch's kill-move — and re-point the slot
            # so later kills/deaths attribute correctly. Non-mega/primal forme
            # changes (Aegislash-Blade, …) are the SAME pick: the _MEGA_PRIMAL_RE
            # guard below makes them a no-op, so they stay unified. (-formechange
            # is accepted too in case an item-less mega like Rayquaza uses it.)
            slot = _extract_slot(parts[2])
            new_name = _norm(parts[3].split(",")[0].strip())
            if slot and new_name and _MEGA_PRIMAL_RE.search(new_name):
                sider = _slot_player(slot)
                old_name = active.get(slot)
                if old_name and old_name != new_name:
                    moved = kills[sider].pop(old_name, 0)
                    if moved:
                        kills[sider][new_name] = kills[sider].get(new_name, 0) + moved
                    used[sider].discard(old_name)
                active[slot] = new_name
                used[sider].add(new_name)

        elif cmd == "move" and len(parts) >= 5:
            atk_slot = _extract_slot(parts[2])
            atk_name = active.get(atk_slot) or _extract_name(parts[2])
            if not (atk_slot and atk_name):
                continue
            atk_player = _slot_player(atk_slot)
            # Remember who just acted — a -status or -sidestart on the next line(s)
            # is attributed to this mon.
            last_move_actor = (atk_player, atk_name)
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
                # A real move targeting this mon supersedes any pending charge — the
                # charge either already resolved or was blocked; this move is now the
                # authoritative last hit, so drop the stale pending credit.
                pending_charge.pop(tgt, None)
            # Future Sight / Doom Desire land ~2 turns later on the TARGET's side,
            # by which point the user may be gone. Remember the user keyed by the
            # target side so the delayed KO still credits them.
            move_name = parts[3].strip() if len(parts) >= 4 else ""
            if move_name in ("Future Sight", "Doom Desire"):
                tgt_side = (
                    _slot_player(primary)
                    if primary
                    else ("p2" if atk_player == "p1" else "p1")
                )
                future_move_by[tgt_side] = (atk_player, atk_name)

        elif cmd == "-anim" and len(parts) >= 5:
            # Two-turn charge/semi-invulnerable moves (Electro Shot, Solar Beam,
            # Fly, Dig, Phantom Force, …) log their RELEASE with an EMPTY target
            # on the |move| line (|move|…|Move||[still]); the real hit target only
            # appears on |-anim|<attacker>|<Move>|<target>. Record the attacker as
            # PENDING here — do NOT credit yet — and promote it to last_hit_by only
            # when a real |-damage| actually lands (see the -damage plain branch).
            # This way a charge blocked by Protect (no -damage) never mis-credits a
            # later unrelated faint (e.g. a Perish Song self-KO on the same slot).
            atk_slot = _extract_slot(parts[2])
            atk_name = active.get(atk_slot) or _extract_name(parts[2])
            tgt_slot = _extract_slot(parts[4])
            if atk_slot and atk_name and tgt_slot and tgt_slot != atk_slot:
                pending_charge[tgt_slot] = (_slot_player(atk_slot), atk_name)

        elif cmd == "-sidestart" and len(parts) >= 4:
            # "|-sidestart|p1: user|move: Stealth Rock" — the mon that just moved
            # set this hazard on side p1. Credit future hazard faints on p1 to it.
            # Guard: only credit when the hazard lands on the OPPONENT's side. Court
            # Change / a redirected hazard landing on the mover's own side must not
            # credit the mover for a teammate's later hazard faint.
            side = parts[2].split(":")[0].strip()
            hz = _hazard_id(parts[3])
            if (
                side in ("p1", "p2")
                and hz
                and last_move_actor
                and last_move_actor[0] != side
            ):
                hazard_setter[side][hz] = last_move_actor

        elif cmd == "-sideend" and len(parts) >= 4:
            side = parts[2].split(":")[0].strip()
            hz = _hazard_id(parts[3])
            if side in ("p1", "p2") and hz:
                hazard_setter[side].pop(hz, None)

        elif cmd == "-status" and len(parts) >= 4:
            # "|-status|p1a: Mon|brn" — attribute the status to the mon responsible.
            victim_slot = _extract_slot(parts[2])
            rest = "|".join(parts[4:])
            of_m = re.search(r"\[of\]\s*(p[12][ab]):", rest)
            if not victim_slot:
                pass
            elif of_m and of_m.group(1) != victim_slot:
                # Ability-inflicted (Flame Body, Static, Poison Point): [of] names
                # the culprit — use it, not whoever moved last.
                src = of_m.group(1)
                if active.get(src):
                    status_by[victim_slot] = (_slot_player(src), active[src])
            elif "[from]" in rest:
                # Self-inflicted (Flame Orb / Toxic Orb / Rest) or hazard-set status
                # (Toxic Spikes) — NOT the last mover's doing. Credit no one here
                # (a hazard status is handled via hazard_setter on the damage tick).
                pass
            elif last_move_actor and last_move_actor[0] != _slot_player(victim_slot):
                # Plain opponent-move status: Will-O-Wisp, Toxic, Nuzzle, Thunder Wave.
                status_by[victim_slot] = last_move_actor

        elif cmd == "-damage" and len(parts) >= 3:
            victim_slot = _extract_slot(parts[2])
            if not victim_slot:
                continue
            rest = "|".join(parts[3:])
            of_m = re.search(r"\[of\]\s*(p[12][ab]):\s*(.+)", rest)
            if of_m:
                # Damage credited to an opponent (Rocky Helmet, Rough Skin, etc.).
                # Prefer the species we're tracking for that slot over the [of]
                # line's name (which is the nickname), so credit lands on the mon.
                src_slot = of_m.group(1)
                src_name = active.get(src_slot) or _norm(
                    of_m.group(2).strip().split(",")[0]
                )
                last_hit_by[victim_slot] = (_slot_player(src_slot), src_name)
                pending_charge.pop(victim_slot, None)
            elif "[from]" in rest:
                # Indirect damage with no [of] attacker. Attribute the eventual KO
                # to the Pokémon responsible for the source:
                #   - entry hazards  -> the mon that set that hazard on this side
                #   - poison/burn    -> the mon that inflicted the status
                #   - Life Orb/recoil/crash/weather -> self-inflicted, credit no one
                fm = re.search(r"\[from\]\s*([^|]+)", rest)
                source = fm.group(1).strip() if fm else ""
                victim_side = _slot_player(victim_slot)
                hz = _hazard_id(source)
                cause = None
                if hz and hz in hazard_setter.get(victim_side, {}):
                    cause = hazard_setter[victim_side][hz]
                elif source in ("brn", "psn", "tox"):
                    # Poison/burn tick: prefer the recorded status applier; if the
                    # poison came from Toxic Spikes (no applier recorded), credit the
                    # hazard setter instead.
                    if victim_slot in status_by:
                        cause = status_by[victim_slot]
                    elif source in (
                        "psn",
                        "tox",
                    ) and "toxic spikes" in hazard_setter.get(victim_side, {}):
                        cause = hazard_setter[victim_side]["toxic spikes"]
                elif source in ("move: Future Sight", "move: Doom Desire"):
                    # Delayed attack landing now — credit the mon that used it 2
                    # turns ago (recorded by target side), even if it's since gone.
                    cause = future_move_by.get(victim_side)
                if cause:
                    last_hit_by[victim_slot] = cause
                else:
                    # Truly self-inflicted (Life Orb, recoil) or unknown source —
                    # clear any stale direct attacker so no one is wrongly credited.
                    last_hit_by.pop(victim_slot, None)
                # An indirect [from] tick is not the charge move connecting; drop
                # any pending charge credit so it can't leak onto this faint.
                pending_charge.pop(victim_slot, None)
            else:
                # Plain direct damage with no [of]/[from] — a real move connected.
                # If a charge move's release hit this slot (target came from the
                # |-anim| line because the |move| line had no target), promote that
                # pending attacker to the killer now that damage actually landed.
                if victim_slot in pending_charge:
                    last_hit_by[victim_slot] = pending_charge.pop(victim_slot)

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
            # A mon that just fainted can't be the culprit for a status/hazard
            # applied AFTER its faint line — invalidate stale actor credit.
            if last_move_actor and last_move_actor == (fplayer, fainted):
                last_move_actor = None

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

    Roster picks are stored in PREFIX form ("Mega Gardevoir", "Mega Charizard X",
    "Primal Kyogre"), while Showdown battle logs use SUFFIX form ("Gardevoir-Mega",
    "Charizard-Mega-X", "Kyogre-Primal"). This resolver bridges both directions and
    also tolerates rosters that happen to store the suffix form ("Gardevoir-Mega").

    Match precedence (first hit wins):
      1. Exact (case-insensitive) match — covers suffix-form rosters and battle formes.
      2. Suffix → prefix conversion  ("Gardevoir-Mega"   → "Mega Gardevoir",
                                       "Charizard-Mega-X" → "Mega Charizard X",
                                       "Kyogre-Primal"    → "Primal Kyogre").
      3. Bare-base → mega/primal-on-roster (prefix probe, then legacy suffix probe).
      4. Base-strip fallback ("Gardevoir-Mega" → "Gardevoir") ONLY if the mega/primal
         pick is NOT on the roster — so a base-only pick absorbs the stats.
    Returns raw unchanged if roster is empty or nothing matches.
    """
    if not roster:
        return raw
    by_lower = {n.lower(): n for n in roster}

    # 1. Exact match. Handles suffix-form rosters AND every battle-forme mon
    #    (Aegislash-Blade, Palafin-Hero, Terapagos-Terastal, Landorus-Therian, …)
    #    which appear verbatim in both the log and the roster and stay unified.
    if raw.lower() in by_lower:
        return by_lower[raw.lower()]

    # 2. Showdown SUFFIX form → roster PREFIX form. Split on '-', find the
    #    'mega'/'primal' token, reassemble as the DB stores it:
    #    "Base-Mega[-V]" → "Mega Base [V]", "Base-Primal" → "Primal Base".
    parts = [p.strip() for p in raw.split("-") if p.strip()]
    if len(parts) >= 2:
        base = parts[0]
        suffix = parts[1:]
        suffix_lower = [s.lower() for s in suffix]
        for key, prefix in (("mega", "Mega"), ("primal", "Primal")):
            if key in suffix_lower:
                idx = suffix_lower.index(key)
                variants = [suffix[j] for j in range(len(suffix)) if j != idx]
                cand = (
                    f"{prefix} {base} {' '.join(variants)}".strip()
                    if variants
                    else f"{prefix} {base}"
                )
                if cand.lower() in by_lower:
                    return by_lower[cand.lower()]

    # 3. Bare base in log, mega/primal pick on roster.
    #    (a) prefix-form roster: "Gallade" + roster "Mega Gallade" → "Mega Gallade".
    for prefix in ("Mega", "Primal"):
        cand = f"{prefix} {raw}"
        if cand.lower() in by_lower:
            return by_lower[cand.lower()]
    #    (b) legacy suffix-form roster: "Gallade" + roster "Gallade-Mega".
    for suffix in ("-Mega", "-Mega-X", "-Mega-Y", "-Primal"):
        cand = raw + suffix
        if cand.lower() in by_lower:
            return by_lower[cand.lower()]

    # 4. Base-strip fallback — only reached when the mega/primal pick is absent, so
    #    a base-only pick ("Gardevoir") legitimately absorbs the mega's stats.
    for suffix in ("-Mega-X", "-Mega-Y", "-Mega-Z", "-Mega", "-Primal"):
        if raw.lower().endswith(suffix.lower()):
            stripped = raw[: -len(suffix)]
            if stripped.lower() in by_lower:
                return by_lower[stripped.lower()]

    return raw


def remap_dict(d: dict, name_map: dict) -> dict:
    out = {}
    for mon, val in d.items():
        canon = name_map.get(mon, mon)
        out[canon] = out.get(canon, 0) + val
    return out


# ── Type palette ──────────────────────────────────────────────────────────────
TYPE_COLORS = {
    "Dragon": "#7b6cff",
    "Ground": "#d9a441",
    "Flying": "#7fb8ff",
    "Ghost": "#9a6cff",
    "Steel": "#a7b3c4",
    "Dark": "#7a6f8a",
    "Fighting": "#ff7a59",
    "Fairy": "#ff8fd0",
    "Electric": "#ffd23d",
    "Water": "#3da5ff",
    "Fire": "#ff6a4d",
    "Grass": "#7ddc6a",
    "Poison": "#c06cff",
    "Rock": "#d2b06a",
    "Bug": "#b7d63d",
    "Ice": "#7fe8e0",
    "Psychic": "#ff6fa3",
    "Normal": "#c9c9d2",
}

TYPEDEX = {
    "Abomasnow": ["Grass", "Ice"],
    "Abomasnow (Mega)": ["Grass", "Ice"],
    "Abomasnow-Mega": ["Grass", "Ice"],
    "Abra": ["Psychic"],
    "Absol": ["Dark"],
    "Absol (Mega)": ["Dark"],
    "Absol (Mega) Z": ["Dark", "Ghost"],
    "Absol-Mega": ["Dark"],
    "Accelgor": ["Bug"],
    "Aegislash Blade": ["Steel", "Ghost"],
    "Aegislash Shield": ["Steel", "Ghost"],
    "Aegislash-Blade": ["Steel", "Ghost"],
    "Aegislash-Shield": ["Steel", "Ghost"],
    "Aerodactyl": ["Rock", "Flying"],
    "Aerodactyl (Mega)": ["Rock", "Flying"],
    "Aerodactyl-Mega": ["Rock", "Flying"],
    "Aggron": ["Steel", "Rock"],
    "Aggron (Mega)": ["Steel"],
    "Aggron-Mega": ["Steel"],
    "Aipom": ["Normal"],
    "Alakazam": ["Psychic"],
    "Alakazam (Mega)": ["Psychic"],
    "Alakazam-Mega": ["Psychic"],
    "Alcremie": ["Fairy"],
    "Alcremie Gmax": ["Fairy"],
    "Alomomola": ["Water"],
    "Altaria": ["Dragon", "Flying"],
    "Altaria (Mega)": ["Dragon", "Fairy"],
    "Altaria-Mega": ["Dragon", "Fairy"],
    "Amaura": ["Rock", "Ice"],
    "Ambipom": ["Normal"],
    "Amoonguss": ["Grass", "Poison"],
    "Ampharos": ["Electric"],
    "Ampharos (Mega)": ["Electric", "Dragon"],
    "Ampharos-Mega": ["Electric", "Dragon"],
    "Annihilape": ["Fighting", "Ghost"],
    "Anorith": ["Rock", "Bug"],
    "Appletun": ["Grass", "Dragon"],
    "Appletun Gmax": ["Grass", "Dragon"],
    "Applin": ["Grass", "Dragon"],
    "Araquanid": ["Water", "Bug"],
    "Araquanid Totem": ["Water", "Bug"],
    "Arbok": ["Poison"],
    "Arboliva": ["Grass", "Normal"],
    "Arcanine": ["Fire"],
    "Arcanine Hisui": ["Fire", "Rock"],
    "Arcanine-Hisui": ["Fire", "Rock"],
    "Arceus": ["Normal"],
    "Archaludon": ["Steel", "Dragon"],
    "Archen": ["Rock", "Flying"],
    "Archeops": ["Rock", "Flying"],
    "Arctibax": ["Dragon", "Ice"],
    "Arctovish": ["Water", "Ice"],
    "Arctozolt": ["Electric", "Ice"],
    "Ariados": ["Bug", "Poison"],
    "Armaldo": ["Rock", "Bug"],
    "Armarouge": ["Fire", "Psychic"],
    "Aromatisse": ["Fairy"],
    "Aron": ["Steel", "Rock"],
    "Arrokuda": ["Water"],
    "Articuno": ["Ice", "Flying"],
    "Articuno Galar": ["Psychic", "Flying"],
    "Articuno-Galar": ["Psychic", "Flying"],
    "Audino": ["Normal"],
    "Audino (Mega)": ["Normal", "Fairy"],
    "Audino-Mega": ["Normal", "Fairy"],
    "Aurorus": ["Rock", "Ice"],
    "Avalugg": ["Ice"],
    "Avalugg Hisui": ["Ice", "Rock"],
    "Avalugg-Hisui": ["Ice", "Rock"],
    "Axew": ["Dragon"],
    "Azelf": ["Psychic"],
    "Azumarill": ["Water", "Fairy"],
    "Azurill": ["Normal", "Fairy"],
    "Bagon": ["Dragon"],
    "Baltoy": ["Ground", "Psychic"],
    "Banette": ["Ghost"],
    "Banette (Mega)": ["Ghost"],
    "Banette-Mega": ["Ghost"],
    "Barbaracle": ["Rock", "Water"],
    "Barbaracle (Mega)": ["Rock", "Fighting"],
    "Barbaracle-Mega": ["Rock", "Fighting"],
    "Barboach": ["Water", "Ground"],
    "Barraskewda": ["Water"],
    "Basculegion Female": ["Water", "Ghost"],
    "Basculegion Male": ["Water", "Ghost"],
    "Basculegion-Female": ["Water", "Ghost"],
    "Basculegion-Male": ["Water", "Ghost"],
    "Basculin Blue Striped": ["Water"],
    "Basculin Red Striped": ["Water"],
    "Basculin White Striped": ["Water"],
    "Bastiodon": ["Rock", "Steel"],
    "Baxcalibur": ["Dragon", "Ice"],
    "Baxcalibur (Mega)": ["Dragon", "Ice"],
    "Baxcalibur-Mega": ["Dragon", "Ice"],
    "Bayleef": ["Grass"],
    "Beartic": ["Ice"],
    "Beautifly": ["Bug", "Flying"],
    "Beedrill": ["Bug", "Poison"],
    "Beedrill (Mega)": ["Bug", "Poison"],
    "Beedrill-Mega": ["Bug", "Poison"],
    "Beheeyem": ["Psychic"],
    "Beldum": ["Steel", "Psychic"],
    "Bellibolt": ["Electric"],
    "Bellossom": ["Grass"],
    "Bellsprout": ["Grass", "Poison"],
    "Bergmite": ["Ice"],
    "Bewear": ["Normal", "Fighting"],
    "Bibarel": ["Normal", "Water"],
    "Bidoof": ["Normal"],
    "Binacle": ["Rock", "Water"],
    "Bisharp": ["Dark", "Steel"],
    "Blacephalon": ["Fire", "Ghost"],
    "Blastoise": ["Water"],
    "Blastoise (Mega)": ["Water"],
    "Blastoise Gmax": ["Water"],
    "Blastoise-Mega": ["Water"],
    "Blaziken": ["Fire", "Fighting"],
    "Blaziken (Mega)": ["Fire", "Fighting"],
    "Blaziken-Mega": ["Fire", "Fighting"],
    "Blipbug": ["Bug"],
    "Blissey": ["Normal"],
    "Blitzle": ["Electric"],
    "Boldore": ["Rock"],
    "Boltund": ["Electric"],
    "Bombirdier": ["Flying", "Dark"],
    "Bonsly": ["Rock"],
    "Bouffalant": ["Normal"],
    "Bounsweet": ["Grass"],
    "Braixen": ["Fire"],
    "Brambleghast": ["Grass", "Ghost"],
    "Bramblin": ["Grass", "Ghost"],
    "Braviary": ["Normal", "Flying"],
    "Braviary Hisui": ["Psychic", "Flying"],
    "Braviary-Hisui": ["Psychic", "Flying"],
    "Breloom": ["Grass", "Fighting"],
    "Brionne": ["Water"],
    "Bronzong": ["Steel", "Psychic"],
    "Bronzor": ["Steel", "Psychic"],
    "Brute Bonnet": ["Grass", "Dark"],
    "Bruxish": ["Water", "Psychic"],
    "Budew": ["Grass", "Poison"],
    "Buizel": ["Water"],
    "Bulbasaur": ["Grass", "Poison"],
    "Buneary": ["Normal"],
    "Bunnelby": ["Normal"],
    "Burmy": ["Bug"],
    "Butterfree": ["Bug", "Flying"],
    "Butterfree Gmax": ["Bug", "Flying"],
    "Buzzwole": ["Bug", "Fighting"],
    "Cacnea": ["Grass"],
    "Cacturne": ["Grass", "Dark"],
    "Calyrex": ["Psychic", "Grass"],
    "Calyrex Ice": ["Psychic", "Ice"],
    "Calyrex Shadow": ["Psychic", "Ghost"],
    "Calyrex-Ice": ["Psychic", "Ice"],
    "Calyrex-Shadow": ["Psychic", "Ghost"],
    "Camerupt": ["Fire", "Ground"],
    "Camerupt (Mega)": ["Fire", "Ground"],
    "Camerupt-Mega": ["Fire", "Ground"],
    "Capsakid": ["Grass"],
    "Carbink": ["Rock", "Fairy"],
    "Carkol": ["Rock", "Fire"],
    "Carnivine": ["Grass"],
    "Carracosta": ["Water", "Rock"],
    "Carvanha": ["Water", "Dark"],
    "Cascoon": ["Bug"],
    "Castform": ["Normal"],
    "Castform Rainy": ["Water"],
    "Castform Snowy": ["Ice"],
    "Castform Sunny": ["Fire"],
    "Caterpie": ["Bug"],
    "Celebi": ["Psychic", "Grass"],
    "Celesteela": ["Steel", "Flying"],
    "Centiskorch": ["Fire", "Bug"],
    "Centiskorch Gmax": ["Fire", "Bug"],
    "Ceruledge": ["Fire", "Ghost"],
    "Cetitan": ["Ice"],
    "Cetoddle": ["Ice"],
    "Chandelure": ["Ghost", "Fire"],
    "Chandelure (Mega)": ["Ghost", "Fire"],
    "Chandelure-Mega": ["Ghost", "Fire"],
    "Chansey": ["Normal"],
    "Charcadet": ["Fire"],
    "Charizard": ["Fire", "Flying"],
    "Charizard (Mega) X": ["Fire", "Dragon"],
    "Charizard (Mega) Y": ["Fire", "Flying"],
    "Charizard Gmax": ["Fire", "Flying"],
    "Charizard-Mega-X": ["Fire", "Dragon"],
    "Charizard-Mega-Y": ["Fire", "Flying"],
    "Charjabug": ["Bug", "Electric"],
    "Charmander": ["Fire"],
    "Charmeleon": ["Fire"],
    "Chatot": ["Normal", "Flying"],
    "Cherrim": ["Grass"],
    "Cherubi": ["Grass"],
    "Chesnaught": ["Grass", "Fighting"],
    "Chesnaught (Mega)": ["Grass", "Fighting"],
    "Chesnaught-Mega": ["Grass", "Fighting"],
    "Chespin": ["Grass"],
    "Chewtle": ["Water"],
    "Chi Yu": ["Dark", "Fire"],
    "Chien Pao": ["Dark", "Ice"],
    "Chikorita": ["Grass"],
    "Chimchar": ["Fire"],
    "Chimecho": ["Psychic"],
    "Chimecho (Mega)": ["Psychic", "Steel"],
    "Chimecho-Mega": ["Psychic", "Steel"],
    "Chinchou": ["Water", "Electric"],
    "Chingling": ["Psychic"],
    "Cinccino": ["Normal"],
    "Cinderace": ["Fire"],
    "Cinderace Gmax": ["Fire"],
    "Clamperl": ["Water"],
    "Clauncher": ["Water"],
    "Clawitzer": ["Water"],
    "Claydol": ["Ground", "Psychic"],
    "Clefable": ["Fairy"],
    "Clefable (Mega)": ["Fairy", "Flying"],
    "Clefable-Mega": ["Fairy", "Flying"],
    "Clefairy": ["Fairy"],
    "Cleffa": ["Fairy"],
    "Clobbopus": ["Fighting"],
    "Clodsire": ["Poison", "Ground"],
    "Cloyster": ["Water", "Ice"],
    "Coalossal": ["Rock", "Fire"],
    "Coalossal Gmax": ["Rock", "Fire"],
    "Cobalion": ["Steel", "Fighting"],
    "Cofagrigus": ["Ghost"],
    "Combee": ["Bug", "Flying"],
    "Combusken": ["Fire", "Fighting"],
    "Comfey": ["Fairy"],
    "Conkeldurr": ["Fighting"],
    "Copperajah": ["Steel"],
    "Copperajah Gmax": ["Steel"],
    "Corphish": ["Water"],
    "Corsola": ["Water", "Rock"],
    "Corsola Galar": ["Ghost"],
    "Corsola-Galar": ["Ghost"],
    "Corviknight": ["Flying", "Steel"],
    "Corviknight Gmax": ["Flying", "Steel"],
    "Corvisquire": ["Flying"],
    "Cosmoem": ["Psychic"],
    "Cosmog": ["Psychic"],
    "Cottonee": ["Grass", "Fairy"],
    "Crabominable": ["Fighting", "Ice"],
    "Crabominable (Mega)": ["Fighting", "Ice"],
    "Crabominable-Mega": ["Fighting", "Ice"],
    "Crabrawler": ["Fighting"],
    "Cradily": ["Rock", "Grass"],
    "Cramorant": ["Flying", "Water"],
    "Cramorant Gorging": ["Flying", "Water"],
    "Cramorant Gulping": ["Flying", "Water"],
    "Cranidos": ["Rock"],
    "Crawdaunt": ["Water", "Dark"],
    "Cresselia": ["Psychic"],
    "Croagunk": ["Poison", "Fighting"],
    "Crobat": ["Poison", "Flying"],
    "Crocalor": ["Fire"],
    "Croconaw": ["Water"],
    "Crustle": ["Bug", "Rock"],
    "Cryogonal": ["Ice"],
    "Cubchoo": ["Ice"],
    "Cubone": ["Ground"],
    "Cufant": ["Steel"],
    "Cursola": ["Ghost"],
    "Cutiefly": ["Bug", "Fairy"],
    "Cyclizar": ["Dragon", "Normal"],
    "Cyndaquil": ["Fire"],
    "Dachsbun": ["Fairy"],
    "Darkrai": ["Dark"],
    "Darkrai (Mega)": ["Dark"],
    "Darkrai-Mega": ["Dark"],
    "Darmanitan Galar Standard": ["Ice"],
    "Darmanitan Galar Zen": ["Ice", "Fire"],
    "Darmanitan Standard": ["Fire"],
    "Darmanitan Zen": ["Fire", "Psychic"],
    "Dartrix": ["Grass", "Flying"],
    "Darumaka": ["Fire"],
    "Darumaka Galar": ["Ice"],
    "Darumaka-Galar": ["Ice"],
    "Decidueye": ["Grass", "Ghost"],
    "Decidueye Hisui": ["Grass", "Fighting"],
    "Decidueye-Hisui": ["Grass", "Fighting"],
    "Dedenne": ["Electric", "Fairy"],
    "Deerling": ["Normal", "Grass"],
    "Deino": ["Dark", "Dragon"],
    "Delcatty": ["Normal"],
    "Delibird": ["Ice", "Flying"],
    "Delphox": ["Fire", "Psychic"],
    "Delphox (Mega)": ["Fire", "Psychic"],
    "Delphox-Mega": ["Fire", "Psychic"],
    "Deoxys Attack": ["Psychic"],
    "Deoxys Defense": ["Psychic"],
    "Deoxys Normal": ["Psychic"],
    "Deoxys Speed": ["Psychic"],
    "Deoxys-Attack": ["Psychic"],
    "Deoxys-Defense": ["Psychic"],
    "Deoxys-Speed": ["Psychic"],
    "Dewgong": ["Water", "Ice"],
    "Dewott": ["Water"],
    "Dewpider": ["Water", "Bug"],
    "Dhelmise": ["Ghost", "Grass"],
    "Dialga": ["Steel", "Dragon"],
    "Dialga Origin": ["Steel", "Dragon"],
    "Dialga-Origin": ["Steel", "Dragon"],
    "Diancie": ["Rock", "Fairy"],
    "Diancie (Mega)": ["Rock", "Fairy"],
    "Diancie-Mega": ["Rock", "Fairy"],
    "Diggersby": ["Normal", "Ground"],
    "Diglett": ["Ground"],
    "Diglett Alola": ["Ground", "Steel"],
    "Diglett-Alola": ["Ground", "Steel"],
    "Dipplin": ["Grass", "Dragon"],
    "Ditto": ["Normal"],
    "Dodrio": ["Normal", "Flying"],
    "Doduo": ["Normal", "Flying"],
    "Dolliv": ["Grass", "Normal"],
    "Dondozo": ["Water"],
    "Donphan": ["Ground"],
    "Dottler": ["Bug", "Psychic"],
    "Doublade": ["Steel", "Ghost"],
    "Dracovish": ["Water", "Dragon"],
    "Dracozolt": ["Electric", "Dragon"],
    "Dragalge": ["Poison", "Dragon"],
    "Dragalge (Mega)": ["Poison", "Dragon"],
    "Dragalge-Mega": ["Poison", "Dragon"],
    "Dragapult": ["Dragon", "Ghost"],
    "Dragonair": ["Dragon"],
    "Dragonite": ["Dragon", "Flying"],
    "Dragonite (Mega)": ["Dragon", "Flying"],
    "Dragonite-Mega": ["Dragon", "Flying"],
    "Drakloak": ["Dragon", "Ghost"],
    "Drampa": ["Normal", "Dragon"],
    "Drampa (Mega)": ["Normal", "Dragon"],
    "Drampa-Mega": ["Normal", "Dragon"],
    "Drapion": ["Poison", "Dark"],
    "Dratini": ["Dragon"],
    "Drednaw": ["Water", "Rock"],
    "Drednaw Gmax": ["Water", "Rock"],
    "Dreepy": ["Dragon", "Ghost"],
    "Drifblim": ["Ghost", "Flying"],
    "Drifloon": ["Ghost", "Flying"],
    "Drilbur": ["Ground"],
    "Drizzile": ["Water"],
    "Drowzee": ["Psychic"],
    "Druddigon": ["Dragon"],
    "Dubwool": ["Normal"],
    "Ducklett": ["Water", "Flying"],
    "Dudunsparce Three Segment": ["Normal"],
    "Dudunsparce Two Segment": ["Normal"],
    "Dugtrio": ["Ground"],
    "Dugtrio Alola": ["Ground", "Steel"],
    "Dugtrio-Alola": ["Ground", "Steel"],
    "Dunsparce": ["Normal"],
    "Duosion": ["Psychic"],
    "Duraludon": ["Steel", "Dragon"],
    "Duraludon Gmax": ["Steel", "Dragon"],
    "Durant": ["Bug", "Steel"],
    "Dusclops": ["Ghost"],
    "Dusknoir": ["Ghost"],
    "Duskull": ["Ghost"],
    "Dustox": ["Bug", "Poison"],
    "Dwebble": ["Bug", "Rock"],
    "Eelektrik": ["Electric"],
    "Eelektross": ["Electric"],
    "Eelektross (Mega)": ["Electric"],
    "Eelektross-Mega": ["Electric"],
    "Eevee": ["Normal"],
    "Eevee Gmax": ["Normal"],
    "Eevee Starter": ["Normal"],
    "Eiscue Ice": ["Ice"],
    "Eiscue Noice": ["Ice"],
    "Ekans": ["Poison"],
    "Eldegoss": ["Grass"],
    "Electabuzz": ["Electric"],
    "Electivire": ["Electric"],
    "Electrike": ["Electric"],
    "Electrode": ["Electric"],
    "Electrode Hisui": ["Electric", "Grass"],
    "Electrode-Hisui": ["Electric", "Grass"],
    "Elekid": ["Electric"],
    "Elgyem": ["Psychic"],
    "Emboar": ["Fire", "Fighting"],
    "Emboar (Mega)": ["Fire", "Fighting"],
    "Emboar-Mega": ["Fire", "Fighting"],
    "Emolga": ["Electric", "Flying"],
    "Empoleon": ["Water", "Steel"],
    "Enamorus Incarnate": ["Fairy", "Flying"],
    "Enamorus Therian": ["Fairy", "Flying"],
    "Enamorus-Incarnate": ["Fairy", "Flying"],
    "Enamorus-Therian": ["Fairy", "Flying"],
    "Entei": ["Fire"],
    "Escavalier": ["Bug", "Steel"],
    "Espathra": ["Psychic"],
    "Espeon": ["Psychic"],
    "Espurr": ["Psychic"],
    "Eternatus": ["Poison", "Dragon"],
    "Eternatus Eternamax": ["Poison", "Dragon"],
    "Eternatus-Eternamax": ["Poison", "Dragon"],
    "Excadrill": ["Ground", "Steel"],
    "Excadrill (Mega)": ["Ground", "Steel"],
    "Excadrill-Mega": ["Ground", "Steel"],
    "Exeggcute": ["Grass", "Psychic"],
    "Exeggutor": ["Grass", "Psychic"],
    "Exeggutor Alola": ["Grass", "Dragon"],
    "Exeggutor-Alola": ["Grass", "Dragon"],
    "Exploud": ["Normal"],
    "Falinks": ["Fighting"],
    "Falinks (Mega)": ["Fighting"],
    "Falinks-Mega": ["Fighting"],
    "Farfetch'd": ["Normal", "Flying"],
    "Farfetch'd Galar": ["Fighting"],
    "Farfetch'd-Galar": ["Fighting"],
    "Farigiraf": ["Normal", "Psychic"],
    "Fearow": ["Normal", "Flying"],
    "Feebas": ["Water"],
    "Fennekin": ["Fire"],
    "Feraligatr": ["Water"],
    "Feraligatr (Mega)": ["Water", "Dragon"],
    "Feraligatr-Mega": ["Water", "Dragon"],
    "Ferroseed": ["Grass", "Steel"],
    "Ferrothorn": ["Grass", "Steel"],
    "Fezandipiti": ["Poison", "Fairy"],
    "Fidough": ["Fairy"],
    "Finizen": ["Water"],
    "Finneon": ["Water"],
    "Flaaffy": ["Electric"],
    "Flabebe": ["Fairy"],
    "Flamigo": ["Flying", "Fighting"],
    "Flapple": ["Grass", "Dragon"],
    "Flapple Gmax": ["Grass", "Dragon"],
    "Flareon": ["Fire"],
    "Fletchinder": ["Fire", "Flying"],
    "Fletchling": ["Normal", "Flying"],
    "Flittle": ["Psychic"],
    "Floatzel": ["Water"],
    "Floette": ["Fairy"],
    "Floette (Mega)": ["Fairy"],
    "Floette Eternal": ["Fairy"],
    "Floette-Mega": ["Fairy"],
    "Floragato": ["Grass"],
    "Florges": ["Fairy"],
    "Flutter Mane": ["Ghost", "Fairy"],
    "Flygon": ["Ground", "Dragon"],
    "Fomantis": ["Grass"],
    "Foongus": ["Grass", "Poison"],
    "Forretress": ["Bug", "Steel"],
    "Fraxure": ["Dragon"],
    "Frigibax": ["Dragon", "Ice"],
    "Frillish Male": ["Water", "Ghost"],
    "Frillish-Male": ["Water", "Ghost"],
    "Froakie": ["Water"],
    "Frogadier": ["Water"],
    "Froslass": ["Ice", "Ghost"],
    "Froslass (Mega)": ["Ice", "Ghost"],
    "Froslass-Mega": ["Ice", "Ghost"],
    "Frosmoth": ["Ice", "Bug"],
    "Fuecoco": ["Fire"],
    "Furfrou": ["Normal"],
    "Furret": ["Normal"],
    "Gabite": ["Dragon", "Ground"],
    "Gallade": ["Psychic", "Fighting"],
    "Gallade (Mega)": ["Psychic", "Fighting"],
    "Gallade-Mega": ["Psychic", "Fighting"],
    "Galvantula": ["Bug", "Electric"],
    "Garbodor": ["Poison"],
    "Garbodor Gmax": ["Poison"],
    "Garchomp": ["Dragon", "Ground"],
    "Garchomp (Mega)": ["Dragon", "Ground"],
    "Garchomp (Mega) Z": ["Dragon"],
    "Garchomp-Mega": ["Dragon", "Ground"],
    "Gardevoir": ["Psychic", "Fairy"],
    "Gardevoir (Mega)": ["Psychic", "Fairy"],
    "Gardevoir-Mega": ["Psychic", "Fairy"],
    "Garganacl": ["Rock"],
    "Gastly": ["Ghost", "Poison"],
    "Gastrodon": ["Water", "Ground"],
    "Genesect": ["Bug", "Steel"],
    "Gengar": ["Ghost", "Poison"],
    "Gengar (Mega)": ["Ghost", "Poison"],
    "Gengar Gmax": ["Ghost", "Poison"],
    "Gengar-Mega": ["Ghost", "Poison"],
    "Geodude": ["Rock", "Ground"],
    "Geodude Alola": ["Rock", "Electric"],
    "Geodude-Alola": ["Rock", "Electric"],
    "Gholdengo": ["Steel", "Ghost"],
    "Gible": ["Dragon", "Ground"],
    "Gigalith": ["Rock"],
    "Gimmighoul": ["Ghost"],
    "Gimmighoul Roaming": ["Ghost"],
    "Girafarig": ["Normal", "Psychic"],
    "Giratina Altered": ["Ghost", "Dragon"],
    "Giratina Origin": ["Ghost", "Dragon"],
    "Giratina-Altered": ["Ghost", "Dragon"],
    "Giratina-Origin": ["Ghost", "Dragon"],
    "Glaceon": ["Ice"],
    "Glalie": ["Ice"],
    "Glalie (Mega)": ["Ice"],
    "Glalie-Mega": ["Ice"],
    "Glameow": ["Normal"],
    "Glastrier": ["Ice"],
    "Gligar": ["Ground", "Flying"],
    "Glimmet": ["Rock", "Poison"],
    "Glimmora": ["Rock", "Poison"],
    "Glimmora (Mega)": ["Rock", "Poison"],
    "Glimmora-Mega": ["Rock", "Poison"],
    "Gliscor": ["Ground", "Flying"],
    "Gloom": ["Grass", "Poison"],
    "Gogoat": ["Grass"],
    "Golbat": ["Poison", "Flying"],
    "Goldeen": ["Water"],
    "Golduck": ["Water"],
    "Golem": ["Rock", "Ground"],
    "Golem Alola": ["Rock", "Electric"],
    "Golem-Alola": ["Rock", "Electric"],
    "Golett": ["Ground", "Ghost"],
    "Golisopod": ["Bug", "Water"],
    "Golisopod (Mega)": ["Bug", "Steel"],
    "Golisopod-Mega": ["Bug", "Steel"],
    "Golurk": ["Ground", "Ghost"],
    "Golurk (Mega)": ["Ground", "Ghost"],
    "Golurk-Mega": ["Ground", "Ghost"],
    "Goodra": ["Dragon"],
    "Goodra Hisui": ["Steel", "Dragon"],
    "Goodra-Hisui": ["Steel", "Dragon"],
    "Goomy": ["Dragon"],
    "Gorebyss": ["Water"],
    "Gossifleur": ["Grass"],
    "Gothita": ["Psychic"],
    "Gothitelle": ["Psychic"],
    "Gothorita": ["Psychic"],
    "Gouging Fire": ["Fire", "Dragon"],
    "Gourgeist Average": ["Ghost", "Grass"],
    "Gourgeist Large": ["Ghost", "Grass"],
    "Gourgeist Small": ["Ghost", "Grass"],
    "Gourgeist Super": ["Ghost", "Grass"],
    "Grafaiai": ["Poison", "Normal"],
    "Granbull": ["Fairy"],
    "Grapploct": ["Fighting"],
    "Graveler": ["Rock", "Ground"],
    "Graveler Alola": ["Rock", "Electric"],
    "Graveler-Alola": ["Rock", "Electric"],
    "Great Tusk": ["Ground", "Fighting"],
    "Greavard": ["Ghost"],
    "Greedent": ["Normal"],
    "Greninja": ["Water", "Dark"],
    "Greninja (Mega)": ["Water", "Dark"],
    "Greninja Ash": ["Water", "Dark"],
    "Greninja Battle Bond": ["Water", "Dark"],
    "Greninja-Mega": ["Water", "Dark"],
    "Grimer": ["Poison"],
    "Grimer Alola": ["Poison", "Dark"],
    "Grimer-Alola": ["Poison", "Dark"],
    "Grimmsnarl": ["Dark", "Fairy"],
    "Grimmsnarl Gmax": ["Dark", "Fairy"],
    "Grookey": ["Grass"],
    "Grotle": ["Grass"],
    "Groudon": ["Ground"],
    "Groudon Primal": ["Ground", "Fire"],
    "Grovyle": ["Grass"],
    "Growlithe": ["Fire"],
    "Growlithe Hisui": ["Fire", "Rock"],
    "Growlithe-Hisui": ["Fire", "Rock"],
    "Grubbin": ["Bug"],
    "Grumpig": ["Psychic"],
    "Gulpin": ["Poison"],
    "Gumshoos": ["Normal"],
    "Gumshoos Totem": ["Normal"],
    "Gurdurr": ["Fighting"],
    "Guzzlord": ["Dark", "Dragon"],
    "Gyarados": ["Water", "Flying"],
    "Gyarados (Mega)": ["Water", "Dark"],
    "Gyarados-Mega": ["Water", "Dark"],
    "Hakamo O": ["Dragon", "Fighting"],
    "Happiny": ["Normal"],
    "Hariyama": ["Fighting"],
    "Hatenna": ["Psychic"],
    "Hatterene": ["Psychic", "Fairy"],
    "Hatterene Gmax": ["Psychic", "Fairy"],
    "Hattrem": ["Psychic"],
    "Haunter": ["Ghost", "Poison"],
    "Hawlucha": ["Fighting", "Flying"],
    "Hawlucha (Mega)": ["Fighting", "Flying"],
    "Hawlucha-Mega": ["Fighting", "Flying"],
    "Haxorus": ["Dragon"],
    "Heatmor": ["Fire"],
    "Heatran": ["Fire", "Steel"],
    "Heatran (Mega)": ["Fire", "Steel"],
    "Heatran-Mega": ["Fire", "Steel"],
    "Heliolisk": ["Electric", "Normal"],
    "Helioptile": ["Electric", "Normal"],
    "Heracross": ["Bug", "Fighting"],
    "Heracross (Mega)": ["Bug", "Fighting"],
    "Heracross-Mega": ["Bug", "Fighting"],
    "Herdier": ["Normal"],
    "Hippopotas": ["Ground"],
    "Hippowdon": ["Ground"],
    "Hitmonchan": ["Fighting"],
    "Hitmonlee": ["Fighting"],
    "Hitmontop": ["Fighting"],
    "Ho Oh": ["Fire", "Flying"],
    "Honchkrow": ["Dark", "Flying"],
    "Honedge": ["Steel", "Ghost"],
    "Hoopa": ["Psychic", "Ghost"],
    "Hoopa Unbound": ["Psychic", "Dark"],
    "Hoothoot": ["Normal", "Flying"],
    "Hoppip": ["Grass", "Flying"],
    "Horsea": ["Water"],
    "Houndoom": ["Dark", "Fire"],
    "Houndoom (Mega)": ["Dark", "Fire"],
    "Houndoom-Mega": ["Dark", "Fire"],
    "Houndour": ["Dark", "Fire"],
    "Houndstone": ["Ghost"],
    "Huntail": ["Water"],
    "Hydrapple": ["Grass", "Dragon"],
    "Hydreigon": ["Dark", "Dragon"],
    "Hypno": ["Psychic"],
    "Igglybuff": ["Normal", "Fairy"],
    "Illumise": ["Bug"],
    "Impidimp": ["Dark", "Fairy"],
    "Incineroar": ["Fire", "Dark"],
    "Indeedee Female": ["Psychic", "Normal"],
    "Indeedee Male": ["Psychic", "Normal"],
    "Indeedee-Female": ["Psychic", "Normal"],
    "Indeedee-Male": ["Psychic", "Normal"],
    "Infernape": ["Fire", "Fighting"],
    "Inkay": ["Dark", "Psychic"],
    "Inteleon": ["Water"],
    "Inteleon Gmax": ["Water"],
    "Iron Boulder": ["Rock", "Psychic"],
    "Iron Bundle": ["Ice", "Water"],
    "Iron Crown": ["Steel", "Psychic"],
    "Iron Hands": ["Fighting", "Electric"],
    "Iron Jugulis": ["Dark", "Flying"],
    "Iron Leaves": ["Grass", "Psychic"],
    "Iron Moth": ["Fire", "Poison"],
    "Iron Thorns": ["Rock", "Electric"],
    "Iron Treads": ["Ground", "Steel"],
    "Iron Valiant": ["Fairy", "Fighting"],
    "Ivysaur": ["Grass", "Poison"],
    "Jangmo O": ["Dragon"],
    "Jellicent Male": ["Water", "Ghost"],
    "Jellicent-Male": ["Water", "Ghost"],
    "Jigglypuff": ["Normal", "Fairy"],
    "Jirachi": ["Steel", "Psychic"],
    "Jolteon": ["Electric"],
    "Joltik": ["Bug", "Electric"],
    "Jumpluff": ["Grass", "Flying"],
    "Jynx": ["Ice", "Psychic"],
    "Kabuto": ["Rock", "Water"],
    "Kabutops": ["Rock", "Water"],
    "Kadabra": ["Psychic"],
    "Kakuna": ["Bug", "Poison"],
    "Kangaskhan": ["Normal"],
    "Kangaskhan (Mega)": ["Normal"],
    "Kangaskhan-Mega": ["Normal"],
    "Karrablast": ["Bug"],
    "Kartana": ["Grass", "Steel"],
    "Kecleon": ["Normal"],
    "Keldeo Ordinary": ["Water", "Fighting"],
    "Keldeo Resolute": ["Water", "Fighting"],
    "Keldeo-Ordinary": ["Water", "Fighting"],
    "Keldeo-Resolute": ["Water", "Fighting"],
    "Kilowattrel": ["Electric", "Flying"],
    "Kingambit": ["Dark", "Steel"],
    "Kingdra": ["Water", "Dragon"],
    "Kingler": ["Water"],
    "Kingler Gmax": ["Water"],
    "Kirlia": ["Psychic", "Fairy"],
    "Klang": ["Steel"],
    "Klawf": ["Rock"],
    "Kleavor": ["Bug", "Rock"],
    "Klefki": ["Steel", "Fairy"],
    "Klink": ["Steel"],
    "Klinklang": ["Steel"],
    "Koffing": ["Poison"],
    "Komala": ["Normal"],
    "Kommo O": ["Dragon", "Fighting"],
    "Kommo O Totem": ["Dragon", "Fighting"],
    "Koraidon": ["Fighting", "Dragon"],
    "Koraidon Gliding Build": ["Fighting", "Dragon"],
    "Koraidon Limited Build": ["Fighting", "Dragon"],
    "Koraidon Sprinting Build": ["Fighting", "Dragon"],
    "Koraidon Swimming Build": ["Fighting", "Dragon"],
    "Krabby": ["Water"],
    "Kricketot": ["Bug"],
    "Kricketune": ["Bug"],
    "Krokorok": ["Ground", "Dark"],
    "Krookodile": ["Ground", "Dark"],
    "Kubfu": ["Fighting"],
    "Kyogre": ["Water"],
    "Kyogre Primal": ["Water"],
    "Kyurem": ["Dragon", "Ice"],
    "Kyurem Black": ["Dragon", "Ice"],
    "Kyurem White": ["Dragon", "Ice"],
    "Kyurem-Black": ["Dragon", "Ice"],
    "Kyurem-White": ["Dragon", "Ice"],
    "Lairon": ["Steel", "Rock"],
    "Lampent": ["Ghost", "Fire"],
    "Landorus Incarnate": ["Ground", "Flying"],
    "Landorus Therian": ["Ground", "Flying"],
    "Landorus-Incarnate": ["Ground", "Flying"],
    "Landorus-Therian": ["Ground", "Flying"],
    "Lanturn": ["Water", "Electric"],
    "Lapras": ["Water", "Ice"],
    "Lapras Gmax": ["Water", "Ice"],
    "Larvesta": ["Bug", "Fire"],
    "Larvitar": ["Rock", "Ground"],
    "Latias": ["Dragon", "Psychic"],
    "Latias (Mega)": ["Dragon", "Psychic"],
    "Latias-Mega": ["Dragon", "Psychic"],
    "Latios": ["Dragon", "Psychic"],
    "Latios (Mega)": ["Dragon", "Psychic"],
    "Latios-Mega": ["Dragon", "Psychic"],
    "Leafeon": ["Grass"],
    "Leavanny": ["Bug", "Grass"],
    "Lechonk": ["Normal"],
    "Ledian": ["Bug", "Flying"],
    "Ledyba": ["Bug", "Flying"],
    "Lickilicky": ["Normal"],
    "Lickitung": ["Normal"],
    "Liepard": ["Dark"],
    "Lileep": ["Rock", "Grass"],
    "Lilligant": ["Grass"],
    "Lilligant Hisui": ["Grass", "Fighting"],
    "Lilligant-Hisui": ["Grass", "Fighting"],
    "Lillipup": ["Normal"],
    "Linoone": ["Normal"],
    "Linoone Galar": ["Dark", "Normal"],
    "Linoone-Galar": ["Dark", "Normal"],
    "Litleo": ["Fire", "Normal"],
    "Litten": ["Fire"],
    "Litwick": ["Ghost", "Fire"],
    "Lokix": ["Bug", "Dark"],
    "Lombre": ["Water", "Grass"],
    "Lopunny": ["Normal"],
    "Lopunny (Mega)": ["Normal", "Fighting"],
    "Lopunny-Mega": ["Normal", "Fighting"],
    "Lotad": ["Water", "Grass"],
    "Loudred": ["Normal"],
    "Lucario": ["Fighting", "Steel"],
    "Lucario (Mega)": ["Fighting", "Steel"],
    "Lucario (Mega) Z": ["Fighting", "Steel"],
    "Lucario-Mega": ["Fighting", "Steel"],
    "Ludicolo": ["Water", "Grass"],
    "Lugia": ["Psychic", "Flying"],
    "Lumineon": ["Water"],
    "Lunala": ["Psychic", "Ghost"],
    "Lunatone": ["Rock", "Psychic"],
    "Lurantis": ["Grass"],
    "Lurantis Totem": ["Grass"],
    "Luvdisc": ["Water"],
    "Luxio": ["Electric"],
    "Luxray": ["Electric"],
    "Lycanroc Dusk": ["Rock"],
    "Lycanroc Midday": ["Rock"],
    "Lycanroc Midnight": ["Rock"],
    "Lycanroc-Dusk": ["Rock"],
    "Lycanroc-Midnight": ["Rock"],
    "Mabosstiff": ["Dark"],
    "Machamp": ["Fighting"],
    "Machamp Gmax": ["Fighting"],
    "Machoke": ["Fighting"],
    "Machop": ["Fighting"],
    "Magby": ["Fire"],
    "Magcargo": ["Fire", "Rock"],
    "Magearna": ["Steel", "Fairy"],
    "Magearna (Mega)": ["Steel", "Fairy"],
    "Magearna Original": ["Steel", "Fairy"],
    "Magearna Original (Mega)": ["Steel", "Fairy"],
    "Magearna Original-Mega": ["Steel", "Fairy"],
    "Magearna-Mega": ["Steel", "Fairy"],
    "Magikarp": ["Water"],
    "Magmar": ["Fire"],
    "Magmortar": ["Fire"],
    "Magnemite": ["Electric", "Steel"],
    "Magneton": ["Electric", "Steel"],
    "Magnezone": ["Electric", "Steel"],
    "Makuhita": ["Fighting"],
    "Malamar": ["Dark", "Psychic"],
    "Malamar (Mega)": ["Dark", "Psychic"],
    "Malamar-Mega": ["Dark", "Psychic"],
    "Mamoswine": ["Ice", "Ground"],
    "Manaphy": ["Water"],
    "Mandibuzz": ["Dark", "Flying"],
    "Manectric": ["Electric"],
    "Manectric (Mega)": ["Electric"],
    "Manectric-Mega": ["Electric"],
    "Mankey": ["Fighting"],
    "Mantine": ["Water", "Flying"],
    "Mantyke": ["Water", "Flying"],
    "Maractus": ["Grass"],
    "Mareanie": ["Poison", "Water"],
    "Mareep": ["Electric"],
    "Marill": ["Water", "Fairy"],
    "Marowak": ["Fire", "Ghost"],
    "Marowak Alola": ["Fire", "Ghost"],
    "Marowak Totem": ["Fire", "Ghost"],
    "Marowak-Alola": ["Fire", "Ghost"],
    "Marshadow": ["Fighting", "Ghost"],
    "Marshtomp": ["Water", "Ground"],
    "Maschiff": ["Dark"],
    "Masquerain": ["Bug", "Flying"],
    "Maushold Family Of Four": ["Normal"],
    "Maushold Family Of Three": ["Normal"],
    "Mawile": ["Steel", "Fairy"],
    "Mawile (Mega)": ["Steel", "Fairy"],
    "Mawile-Mega": ["Steel", "Fairy"],
    "Medicham": ["Fighting", "Psychic"],
    "Medicham (Mega)": ["Fighting", "Psychic"],
    "Medicham-Mega": ["Fighting", "Psychic"],
    "Meditite": ["Fighting", "Psychic"],
    "Meganium": ["Grass"],
    "Meganium (Mega)": ["Grass", "Fairy"],
    "Meganium-Mega": ["Grass", "Fairy"],
    "Melmetal": ["Steel"],
    "Melmetal Gmax": ["Steel"],
    "Meloetta Aria": ["Normal", "Psychic"],
    "Meloetta Pirouette": ["Normal", "Fighting"],
    "Meloetta-Aria": ["Normal", "Psychic"],
    "Meloetta-Pirouette": ["Normal", "Fighting"],
    "Meltan": ["Steel"],
    "Meowscarada": ["Grass", "Dark"],
    "Meowstic (Mega)": ["Psychic"],
    "Meowstic Female": ["Psychic"],
    "Meowstic Male": ["Psychic"],
    "Meowstic-Female": ["Psychic"],
    "Meowstic-Male": ["Psychic"],
    "Meowstic-Mega": ["Psychic"],
    "Meowth": ["Normal"],
    "Meowth Alola": ["Dark"],
    "Meowth Galar": ["Steel"],
    "Meowth Gmax": ["Normal"],
    "Meowth-Alola": ["Dark"],
    "Meowth-Galar": ["Steel"],
    "Mesprit": ["Psychic"],
    "Metagross": ["Steel", "Psychic"],
    "Metagross (Mega)": ["Steel", "Psychic"],
    "Metagross-Mega": ["Steel", "Psychic"],
    "Metang": ["Steel", "Psychic"],
    "Metapod": ["Bug"],
    "Mew": ["Psychic"],
    "Mewtwo": ["Psychic"],
    "Mewtwo (Mega) X": ["Psychic", "Fighting"],
    "Mewtwo (Mega) Y": ["Psychic"],
    "Mewtwo-Mega-X": ["Psychic", "Fighting"],
    "Mewtwo-Mega-Y": ["Psychic"],
    "Mienfoo": ["Fighting"],
    "Mienshao": ["Fighting"],
    "Mightyena": ["Dark"],
    "Milcery": ["Fairy"],
    "Milotic": ["Water"],
    "Miltank": ["Normal"],
    "Mime Jr.": ["Psychic", "Fairy"],
    "Mimikyu Busted": ["Ghost", "Fairy"],
    "Mimikyu Disguised": ["Ghost", "Fairy"],
    "Mimikyu Totem Busted": ["Ghost", "Fairy"],
    "Mimikyu Totem Disguised": ["Ghost", "Fairy"],
    "Minccino": ["Normal"],
    "Minior Blue": ["Rock", "Flying"],
    "Minior Blue Meteor": ["Rock", "Flying"],
    "Minior Green": ["Rock", "Flying"],
    "Minior Green Meteor": ["Rock", "Flying"],
    "Minior Indigo": ["Rock", "Flying"],
    "Minior Indigo Meteor": ["Rock", "Flying"],
    "Minior Orange": ["Rock", "Flying"],
    "Minior Orange Meteor": ["Rock", "Flying"],
    "Minior Red": ["Rock", "Flying"],
    "Minior Red Meteor": ["Rock", "Flying"],
    "Minior Violet": ["Rock", "Flying"],
    "Minior Violet Meteor": ["Rock", "Flying"],
    "Minior Yellow": ["Rock", "Flying"],
    "Minior Yellow Meteor": ["Rock", "Flying"],
    "Minun": ["Electric"],
    "Miraidon": ["Electric", "Dragon"],
    "Miraidon Aquatic Mode": ["Electric", "Dragon"],
    "Miraidon Drive Mode": ["Electric", "Dragon"],
    "Miraidon Glide Mode": ["Electric", "Dragon"],
    "Miraidon Low Power Mode": ["Electric", "Dragon"],
    "Misdreavus": ["Ghost"],
    "Mismagius": ["Ghost"],
    "Moltres": ["Fire", "Flying"],
    "Moltres Galar": ["Dark", "Flying"],
    "Moltres-Galar": ["Dark", "Flying"],
    "Monferno": ["Fire", "Fighting"],
    "Morelull": ["Grass", "Fairy"],
    "Morgrem": ["Dark", "Fairy"],
    "Morpeko Full Belly": ["Electric", "Dark"],
    "Morpeko Hangry": ["Electric", "Dark"],
    "Mothim": ["Bug", "Flying"],
    "Mr. Mime": ["Psychic", "Fairy"],
    "Mr. Mime Galar": ["Ice", "Psychic"],
    "Mr. Mime-Galar": ["Ice", "Psychic"],
    "Mr. Rime": ["Ice", "Psychic"],
    "Mudbray": ["Ground"],
    "Mudkip": ["Water"],
    "Mudsdale": ["Ground"],
    "Muk": ["Poison"],
    "Muk Alola": ["Poison", "Dark"],
    "Muk-Alola": ["Poison", "Dark"],
    "Munchlax": ["Normal"],
    "Munkidori": ["Poison", "Psychic"],
    "Munna": ["Psychic"],
    "Murkrow": ["Dark", "Flying"],
    "Musharna": ["Psychic"],
    "Nacli": ["Rock"],
    "Naclstack": ["Rock"],
    "Naganadel": ["Poison", "Dragon"],
    "Natu": ["Psychic", "Flying"],
    "Necrozma": ["Psychic"],
    "Necrozma Dawn": ["Psychic", "Ghost"],
    "Necrozma Dusk": ["Psychic", "Steel"],
    "Necrozma Ultra": ["Psychic", "Dragon"],
    "Necrozma-Dawn-Wings": ["Psychic", "Ghost"],
    "Necrozma-Dusk-Mane": ["Psychic", "Steel"],
    "Necrozma-Ultra": ["Psychic", "Dragon"],
    "Nickit": ["Dark"],
    "Nidoking": ["Poison", "Ground"],
    "Nidoqueen": ["Poison", "Ground"],
    "Nidoran F": ["Poison"],
    "Nidoran M": ["Poison"],
    "Nidorina": ["Poison"],
    "Nidorino": ["Poison"],
    "Nihilego": ["Rock", "Poison"],
    "Nincada": ["Bug", "Ground"],
    "Ninetales": ["Fire"],
    "Ninetales Alola": ["Ice", "Fairy"],
    "Ninetales-Alola": ["Ice", "Fairy"],
    "Ninjask": ["Bug", "Flying"],
    "Noctowl": ["Normal", "Flying"],
    "Noibat": ["Flying", "Dragon"],
    "Noivern": ["Flying", "Dragon"],
    "Nosepass": ["Rock"],
    "Numel": ["Fire", "Ground"],
    "Nuzleaf": ["Grass", "Dark"],
    "Nymble": ["Bug"],
    "Obstagoon": ["Dark", "Normal"],
    "Octillery": ["Water"],
    "Oddish": ["Grass", "Poison"],
    "Ogerpon": ["Grass"],
    "Ogerpon Cornerstone Mask": ["Grass", "Rock"],
    "Ogerpon Hearthflame Mask": ["Grass", "Fire"],
    "Ogerpon Wellspring Mask": ["Grass", "Water"],
    "Ogerpon-Cornerstone": ["Grass", "Rock"],
    "Ogerpon-Hearthflame": ["Grass", "Fire"],
    "Ogerpon-Wellspring": ["Grass", "Water"],
    "Oinkologne Female": ["Normal"],
    "Oinkologne Male": ["Normal"],
    "Oinkologne-Female": ["Normal"],
    "Oinkologne-Male": ["Normal"],
    "Okidogi": ["Poison", "Fighting"],
    "Omanyte": ["Rock", "Water"],
    "Omastar": ["Rock", "Water"],
    "Onix": ["Rock", "Ground"],
    "Oranguru": ["Normal", "Psychic"],
    "Orbeetle": ["Bug", "Psychic"],
    "Orbeetle Gmax": ["Bug", "Psychic"],
    "Oricorio Baile": ["Fire", "Flying"],
    "Oricorio Pau": ["Psychic", "Flying"],
    "Oricorio Pom Pom": ["Electric", "Flying"],
    "Oricorio Sensu": ["Ghost", "Flying"],
    "Orthworm": ["Steel"],
    "Oshawott": ["Water"],
    "Overqwil": ["Dark", "Poison"],
    "Pachirisu": ["Electric"],
    "Palafin Hero": ["Water"],
    "Palafin Zero": ["Water"],
    "Palkia": ["Water", "Dragon"],
    "Palkia Origin": ["Water", "Dragon"],
    "Palkia-Origin": ["Water", "Dragon"],
    "Palossand": ["Ghost", "Ground"],
    "Palpitoad": ["Water", "Ground"],
    "Pancham": ["Fighting"],
    "Pangoro": ["Fighting", "Dark"],
    "Panpour": ["Water"],
    "Pansage": ["Grass"],
    "Pansear": ["Fire"],
    "Paras": ["Bug", "Grass"],
    "Parasect": ["Bug", "Grass"],
    "Passimian": ["Fighting"],
    "Patrat": ["Normal"],
    "Pawmi": ["Electric"],
    "Pawmo": ["Electric", "Fighting"],
    "Pawmot": ["Electric", "Fighting"],
    "Pawniard": ["Dark", "Steel"],
    "Pecharunt": ["Poison", "Ghost"],
    "Pelipper": ["Water", "Flying"],
    "Perrserker": ["Steel"],
    "Persian": ["Normal"],
    "Persian Alola": ["Dark"],
    "Persian-Alola": ["Dark"],
    "Petilil": ["Grass"],
    "Phanpy": ["Ground"],
    "Phantump": ["Ghost", "Grass"],
    "Pheromosa": ["Bug", "Fighting"],
    "Phione": ["Water"],
    "Pichu": ["Electric"],
    "Pidgeot": ["Normal", "Flying"],
    "Pidgeot (Mega)": ["Normal", "Flying"],
    "Pidgeot-Mega": ["Normal", "Flying"],
    "Pidgeotto": ["Normal", "Flying"],
    "Pidgey": ["Normal", "Flying"],
    "Pidove": ["Normal", "Flying"],
    "Pignite": ["Fire", "Fighting"],
    "Pikachu": ["Electric"],
    "Pikachu Alola Cap": ["Electric"],
    "Pikachu Belle": ["Electric"],
    "Pikachu Cosplay": ["Electric"],
    "Pikachu Gmax": ["Electric"],
    "Pikachu Hoenn Cap": ["Electric"],
    "Pikachu Kalos Cap": ["Electric"],
    "Pikachu Libre": ["Electric"],
    "Pikachu Original Cap": ["Electric"],
    "Pikachu Partner Cap": ["Electric"],
    "Pikachu Phd": ["Electric"],
    "Pikachu Pop Star": ["Electric"],
    "Pikachu Rock Star": ["Electric"],
    "Pikachu Sinnoh Cap": ["Electric"],
    "Pikachu Starter": ["Electric"],
    "Pikachu Unova Cap": ["Electric"],
    "Pikachu World Cap": ["Electric"],
    "Pikipek": ["Normal", "Flying"],
    "Piloswine": ["Ice", "Ground"],
    "Pincurchin": ["Electric"],
    "Pineco": ["Bug"],
    "Pinsir": ["Bug"],
    "Pinsir (Mega)": ["Bug", "Flying"],
    "Pinsir-Mega": ["Bug", "Flying"],
    "Piplup": ["Water"],
    "Plusle": ["Electric"],
    "Poipole": ["Poison"],
    "Politoed": ["Water"],
    "Poliwag": ["Water"],
    "Poliwhirl": ["Water"],
    "Poliwrath": ["Water", "Fighting"],
    "Poltchageist": ["Grass", "Ghost"],
    "Polteageist": ["Ghost"],
    "Ponyta": ["Fire"],
    "Ponyta Galar": ["Psychic"],
    "Ponyta-Galar": ["Psychic"],
    "Poochyena": ["Dark"],
    "Popplio": ["Water"],
    "Porygon": ["Normal"],
    "Porygon Z": ["Normal"],
    "Porygon2": ["Normal"],
    "Primarina": ["Water", "Fairy"],
    "Primeape": ["Fighting"],
    "Prinplup": ["Water"],
    "Probopass": ["Rock", "Steel"],
    "Psyduck": ["Water"],
    "Pumpkaboo Average": ["Ghost", "Grass"],
    "Pumpkaboo Large": ["Ghost", "Grass"],
    "Pumpkaboo Small": ["Ghost", "Grass"],
    "Pumpkaboo Super": ["Ghost", "Grass"],
    "Pupitar": ["Rock", "Ground"],
    "Purrloin": ["Dark"],
    "Purugly": ["Normal"],
    "Pyroar (Mega)": ["Fire", "Normal"],
    "Pyroar Male": ["Fire", "Normal"],
    "Pyroar-Male": ["Fire", "Normal"],
    "Pyroar-Mega": ["Fire", "Normal"],
    "Pyukumuku": ["Water"],
    "Quagsire": ["Water", "Ground"],
    "Quaquaval": ["Water", "Fighting"],
    "Quaxly": ["Water"],
    "Quaxwell": ["Water"],
    "Quilava": ["Fire"],
    "Quilladin": ["Grass"],
    "Qwilfish": ["Water", "Poison"],
    "Qwilfish Hisui": ["Dark", "Poison"],
    "Qwilfish-Hisui": ["Dark", "Poison"],
    "Raboot": ["Fire"],
    "Rabsca": ["Bug", "Psychic"],
    "Raging Bolt": ["Electric", "Dragon"],
    "Raichu": ["Electric"],
    "Raichu (Mega) X": ["Electric"],
    "Raichu (Mega) Y": ["Electric"],
    "Raichu Alola": ["Electric", "Psychic"],
    "Raichu-Alola": ["Electric", "Psychic"],
    "Raichu-Mega-X": ["Electric"],
    "Raichu-Mega-Y": ["Electric"],
    "Raikou": ["Electric"],
    "Ralts": ["Psychic", "Fairy"],
    "Rampardos": ["Rock"],
    "Rapidash": ["Fire"],
    "Rapidash Galar": ["Psychic", "Fairy"],
    "Rapidash-Galar": ["Psychic", "Fairy"],
    "Raticate": ["Normal"],
    "Raticate Alola": ["Dark", "Normal"],
    "Raticate Totem Alola": ["Dark", "Normal"],
    "Raticate Totem-Alola": ["Dark", "Normal"],
    "Raticate-Alola": ["Dark", "Normal"],
    "Rattata": ["Normal"],
    "Rattata Alola": ["Dark", "Normal"],
    "Rattata-Alola": ["Dark", "Normal"],
    "Rayquaza": ["Dragon", "Flying"],
    "Rayquaza (Mega)": ["Dragon", "Flying"],
    "Rayquaza-Mega": ["Dragon", "Flying"],
    "Regice": ["Ice"],
    "Regidrago": ["Dragon"],
    "Regieleki": ["Electric"],
    "Regigigas": ["Normal"],
    "Regirock": ["Rock"],
    "Registeel": ["Steel"],
    "Relicanth": ["Water", "Rock"],
    "Rellor": ["Bug"],
    "Remoraid": ["Water"],
    "Reshiram": ["Dragon", "Fire"],
    "Reuniclus": ["Psychic"],
    "Revavroom": ["Steel", "Poison"],
    "Rhydon": ["Ground", "Rock"],
    "Rhyhorn": ["Ground", "Rock"],
    "Rhyperior": ["Ground", "Rock"],
    "Ribombee": ["Bug", "Fairy"],
    "Ribombee Totem": ["Bug", "Fairy"],
    "Rillaboom": ["Grass"],
    "Rillaboom Gmax": ["Grass"],
    "Riolu": ["Fighting"],
    "Roaring Moon": ["Dragon", "Dark"],
    "Rockruff": ["Rock"],
    "Rockruff Own Tempo": ["Rock"],
    "Roggenrola": ["Rock"],
    "Rolycoly": ["Rock"],
    "Rookidee": ["Flying"],
    "Roselia": ["Grass", "Poison"],
    "Roserade": ["Grass", "Poison"],
    "Rotom": ["Electric", "Ghost"],
    "Rotom Fan": ["Electric", "Flying"],
    "Rotom Frost": ["Electric", "Ice"],
    "Rotom Heat": ["Electric", "Fire"],
    "Rotom Mow": ["Electric", "Grass"],
    "Rotom Wash": ["Electric", "Water"],
    "Rotom-Fan": ["Electric", "Flying"],
    "Rotom-Frost": ["Electric", "Ice"],
    "Rotom-Heat": ["Electric", "Fire"],
    "Rotom-Mow": ["Electric", "Grass"],
    "Rotom-Wash": ["Electric", "Water"],
    "Rowlet": ["Grass", "Flying"],
    "Rufflet": ["Normal", "Flying"],
    "Runerigus": ["Ground", "Ghost"],
    "Sableye": ["Dark", "Ghost"],
    "Sableye (Mega)": ["Dark", "Ghost"],
    "Sableye-Mega": ["Dark", "Ghost"],
    "Salamence": ["Dragon", "Flying"],
    "Salamence (Mega)": ["Dragon", "Flying"],
    "Salamence-Mega": ["Dragon", "Flying"],
    "Salandit": ["Poison", "Fire"],
    "Salazzle": ["Poison", "Fire"],
    "Salazzle Totem": ["Poison", "Fire"],
    "Samurott": ["Water"],
    "Samurott Hisui": ["Water", "Dark"],
    "Samurott-Hisui": ["Water", "Dark"],
    "Sandaconda": ["Ground"],
    "Sandaconda Gmax": ["Ground"],
    "Sandile": ["Ground", "Dark"],
    "Sandshrew": ["Ground"],
    "Sandshrew Alola": ["Ice", "Steel"],
    "Sandshrew-Alola": ["Ice", "Steel"],
    "Sandslash": ["Ground"],
    "Sandslash Alola": ["Ice", "Steel"],
    "Sandslash-Alola": ["Ice", "Steel"],
    "Sandy Shocks": ["Electric", "Ground"],
    "Sandygast": ["Ghost", "Ground"],
    "Sawk": ["Fighting"],
    "Sawsbuck": ["Normal", "Grass"],
    "Scatterbug": ["Bug"],
    "Sceptile": ["Grass"],
    "Sceptile (Mega)": ["Grass", "Dragon"],
    "Sceptile-Mega": ["Grass", "Dragon"],
    "Scizor": ["Bug", "Steel"],
    "Scizor (Mega)": ["Bug", "Steel"],
    "Scizor-Mega": ["Bug", "Steel"],
    "Scolipede": ["Bug", "Poison"],
    "Scolipede (Mega)": ["Bug", "Poison"],
    "Scolipede-Mega": ["Bug", "Poison"],
    "Scorbunny": ["Fire"],
    "Scovillain": ["Grass", "Fire"],
    "Scovillain (Mega)": ["Grass", "Fire"],
    "Scovillain-Mega": ["Grass", "Fire"],
    "Scrafty": ["Dark", "Fighting"],
    "Scrafty (Mega)": ["Dark", "Fighting"],
    "Scrafty-Mega": ["Dark", "Fighting"],
    "Scraggy": ["Dark", "Fighting"],
    "Scream Tail": ["Fairy", "Psychic"],
    "Scyther": ["Bug", "Flying"],
    "Seadra": ["Water"],
    "Seaking": ["Water"],
    "Sealeo": ["Ice", "Water"],
    "Seedot": ["Grass"],
    "Seel": ["Water"],
    "Seismitoad": ["Water", "Ground"],
    "Sentret": ["Normal"],
    "Serperior": ["Grass"],
    "Servine": ["Grass"],
    "Seviper": ["Poison"],
    "Sewaddle": ["Bug", "Grass"],
    "Sharpedo": ["Water", "Dark"],
    "Sharpedo (Mega)": ["Water", "Dark"],
    "Sharpedo-Mega": ["Water", "Dark"],
    "Shaymin Land": ["Grass"],
    "Shaymin Sky": ["Grass", "Flying"],
    "Shaymin-Land": ["Grass"],
    "Shaymin-Sky": ["Grass", "Flying"],
    "Shedinja": ["Bug", "Ghost"],
    "Shelgon": ["Dragon"],
    "Shellder": ["Water"],
    "Shellos": ["Water"],
    "Shelmet": ["Bug"],
    "Shieldon": ["Rock", "Steel"],
    "Shiftry": ["Grass", "Dark"],
    "Shiinotic": ["Grass", "Fairy"],
    "Shinx": ["Electric"],
    "Shroodle": ["Poison", "Normal"],
    "Shroomish": ["Grass"],
    "Shuckle": ["Bug", "Rock"],
    "Shuppet": ["Ghost"],
    "Sigilyph": ["Psychic", "Flying"],
    "Silcoon": ["Bug"],
    "Silicobra": ["Ground"],
    "Silvally": ["Normal"],
    "Simipour": ["Water"],
    "Simisage": ["Grass"],
    "Simisear": ["Fire"],
    "Sinistcha": ["Grass", "Ghost"],
    "Sinistea": ["Ghost"],
    "Sirfetch'd": ["Fighting"],
    "Sizzlipede": ["Fire", "Bug"],
    "Skarmory": ["Steel", "Flying"],
    "Skarmory (Mega)": ["Steel", "Flying"],
    "Skarmory-Mega": ["Steel", "Flying"],
    "Skeledirge": ["Fire", "Ghost"],
    "Skiddo": ["Grass"],
    "Skiploom": ["Grass", "Flying"],
    "Skitty": ["Normal"],
    "Skorupi": ["Poison", "Bug"],
    "Skrelp": ["Poison", "Water"],
    "Skuntank": ["Poison", "Dark"],
    "Skwovet": ["Normal"],
    "Slaking": ["Normal"],
    "Slakoth": ["Normal"],
    "Sliggoo": ["Dragon"],
    "Sliggoo Hisui": ["Steel", "Dragon"],
    "Sliggoo-Hisui": ["Steel", "Dragon"],
    "Slither Wing": ["Bug", "Fighting"],
    "Slowbro": ["Water", "Psychic"],
    "Slowbro (Mega)": ["Water", "Psychic"],
    "Slowbro Galar": ["Poison", "Psychic"],
    "Slowbro-Galar": ["Poison", "Psychic"],
    "Slowbro-Mega": ["Water", "Psychic"],
    "Slowking": ["Water", "Psychic"],
    "Slowking Galar": ["Poison", "Psychic"],
    "Slowking-Galar": ["Poison", "Psychic"],
    "Slowpoke": ["Water", "Psychic"],
    "Slowpoke Galar": ["Psychic"],
    "Slowpoke-Galar": ["Psychic"],
    "Slugma": ["Fire"],
    "Slurpuff": ["Fairy"],
    "Smeargle": ["Normal"],
    "Smoliv": ["Grass", "Normal"],
    "Smoochum": ["Ice", "Psychic"],
    "Sneasel": ["Dark", "Ice"],
    "Sneasel Hisui": ["Fighting", "Poison"],
    "Sneasel-Hisui": ["Fighting", "Poison"],
    "Sneasler": ["Fighting", "Poison"],
    "Snivy": ["Grass"],
    "Snom": ["Ice", "Bug"],
    "Snorlax": ["Normal"],
    "Snorlax Gmax": ["Normal"],
    "Snorunt": ["Ice"],
    "Snover": ["Grass", "Ice"],
    "Snubbull": ["Fairy"],
    "Sobble": ["Water"],
    "Solgaleo": ["Psychic", "Steel"],
    "Solosis": ["Psychic"],
    "Solrock": ["Rock", "Psychic"],
    "Spearow": ["Normal", "Flying"],
    "Spectrier": ["Ghost"],
    "Spewpa": ["Bug"],
    "Spheal": ["Ice", "Water"],
    "Spidops": ["Bug"],
    "Spinarak": ["Bug", "Poison"],
    "Spinda": ["Normal"],
    "Spiritomb": ["Ghost", "Dark"],
    "Spoink": ["Psychic"],
    "Sprigatito": ["Grass"],
    "Spritzee": ["Fairy"],
    "Squawkabilly Blue Plumage": ["Normal", "Flying"],
    "Squawkabilly Green Plumage": ["Normal", "Flying"],
    "Squawkabilly White Plumage": ["Normal", "Flying"],
    "Squawkabilly Yellow Plumage": ["Normal", "Flying"],
    "Squirtle": ["Water"],
    "Stakataka": ["Rock", "Steel"],
    "Stantler": ["Normal"],
    "Staraptor": ["Normal", "Flying"],
    "Staraptor (Mega)": ["Fighting", "Flying"],
    "Staraptor-Mega": ["Fighting", "Flying"],
    "Staravia": ["Normal", "Flying"],
    "Starly": ["Normal", "Flying"],
    "Starmie": ["Water", "Psychic"],
    "Starmie (Mega)": ["Water", "Psychic"],
    "Starmie-Mega": ["Water", "Psychic"],
    "Staryu": ["Water"],
    "Steelix": ["Steel", "Ground"],
    "Steelix (Mega)": ["Steel", "Ground"],
    "Steelix-Mega": ["Steel", "Ground"],
    "Steenee": ["Grass"],
    "Stonjourner": ["Rock"],
    "Stoutland": ["Normal"],
    "Stufful": ["Normal", "Fighting"],
    "Stunfisk": ["Ground", "Electric"],
    "Stunfisk Galar": ["Ground", "Steel"],
    "Stunfisk-Galar": ["Ground", "Steel"],
    "Stunky": ["Poison", "Dark"],
    "Sudowoodo": ["Rock"],
    "Suicune": ["Water"],
    "Sunflora": ["Grass"],
    "Sunkern": ["Grass"],
    "Surskit": ["Bug", "Water"],
    "Swablu": ["Normal", "Flying"],
    "Swadloon": ["Bug", "Grass"],
    "Swalot": ["Poison"],
    "Swampert": ["Water", "Ground"],
    "Swampert (Mega)": ["Water", "Ground"],
    "Swampert-Mega": ["Water", "Ground"],
    "Swanna": ["Water", "Flying"],
    "Swellow": ["Normal", "Flying"],
    "Swinub": ["Ice", "Ground"],
    "Swirlix": ["Fairy"],
    "Swoobat": ["Psychic", "Flying"],
    "Sylveon": ["Fairy"],
    "Tadbulb": ["Electric"],
    "Taillow": ["Normal", "Flying"],
    "Talonflame": ["Fire", "Flying"],
    "Tandemaus": ["Normal"],
    "Tangela": ["Grass"],
    "Tangrowth": ["Grass"],
    "Tapu Bulu": ["Grass", "Fairy"],
    "Tapu Fini": ["Water", "Fairy"],
    "Tapu Koko": ["Electric", "Fairy"],
    "Tapu Lele": ["Psychic", "Fairy"],
    "Tarountula": ["Bug"],
    "Tatsugiri Curly": ["Dragon", "Water"],
    "Tatsugiri Curly (Mega)": ["Dragon", "Water"],
    "Tatsugiri Curly-Mega": ["Dragon", "Water"],
    "Tatsugiri Droopy": ["Dragon", "Water"],
    "Tatsugiri Droopy (Mega)": ["Dragon", "Water"],
    "Tatsugiri Droopy-Mega": ["Dragon", "Water"],
    "Tatsugiri Stretchy": ["Dragon", "Water"],
    "Tatsugiri Stretchy (Mega)": ["Dragon", "Water"],
    "Tatsugiri Stretchy-Mega": ["Dragon", "Water"],
    "Tauros": ["Normal"],
    "Tauros Paldea Aqua Breed": ["Fighting", "Water"],
    "Tauros Paldea Blaze Breed": ["Fighting", "Fire"],
    "Tauros Paldea Combat Breed": ["Fighting"],
    "Teddiursa": ["Normal"],
    "Tentacool": ["Water", "Poison"],
    "Tentacruel": ["Water", "Poison"],
    "Tepig": ["Fire"],
    "Terapagos": ["Normal"],
    "Terapagos Stellar": ["Normal"],
    "Terapagos Terastal": ["Normal"],
    "Terrakion": ["Rock", "Fighting"],
    "Thievul": ["Dark"],
    "Throh": ["Fighting"],
    "Thundurus Incarnate": ["Electric", "Flying"],
    "Thundurus Therian": ["Electric", "Flying"],
    "Thundurus-Incarnate": ["Electric", "Flying"],
    "Thundurus-Therian": ["Electric", "Flying"],
    "Thwackey": ["Grass"],
    "Timburr": ["Fighting"],
    "Ting Lu": ["Dark", "Ground"],
    "Tinkatink": ["Fairy", "Steel"],
    "Tinkaton": ["Fairy", "Steel"],
    "Tinkatuff": ["Fairy", "Steel"],
    "Tirtouga": ["Water", "Rock"],
    "Toedscool": ["Ground", "Grass"],
    "Toedscruel": ["Ground", "Grass"],
    "Togedemaru": ["Electric", "Steel"],
    "Togedemaru Totem": ["Electric", "Steel"],
    "Togekiss": ["Fairy", "Flying"],
    "Togepi": ["Fairy"],
    "Togetic": ["Fairy", "Flying"],
    "Torchic": ["Fire"],
    "Torkoal": ["Fire"],
    "Tornadus Incarnate": ["Flying"],
    "Tornadus Therian": ["Flying"],
    "Tornadus-Incarnate": ["Flying"],
    "Tornadus-Therian": ["Flying"],
    "Torracat": ["Fire"],
    "Torterra": ["Grass", "Ground"],
    "Totodile": ["Water"],
    "Toucannon": ["Normal", "Flying"],
    "Toxapex": ["Poison", "Water"],
    "Toxel": ["Electric", "Poison"],
    "Toxicroak": ["Poison", "Fighting"],
    "Toxtricity Amped": ["Electric", "Poison"],
    "Toxtricity Amped Gmax": ["Electric", "Poison"],
    "Toxtricity Low Key": ["Electric", "Poison"],
    "Toxtricity Low Key Gmax": ["Electric", "Poison"],
    "Tranquill": ["Normal", "Flying"],
    "Trapinch": ["Ground"],
    "Treecko": ["Grass"],
    "Trevenant": ["Ghost", "Grass"],
    "Tropius": ["Grass", "Flying"],
    "Trubbish": ["Poison"],
    "Trumbeak": ["Normal", "Flying"],
    "Tsareena": ["Grass"],
    "Turtonator": ["Fire", "Dragon"],
    "Turtwig": ["Grass"],
    "Tympole": ["Water"],
    "Tynamo": ["Electric"],
    "Type Null": ["Normal"],
    "Typhlosion": ["Fire"],
    "Typhlosion Hisui": ["Fire", "Ghost"],
    "Typhlosion-Hisui": ["Fire", "Ghost"],
    "Tyranitar": ["Rock", "Dark"],
    "Tyranitar (Mega)": ["Rock", "Dark"],
    "Tyranitar-Mega": ["Rock", "Dark"],
    "Tyrantrum": ["Rock", "Dragon"],
    "Tyrogue": ["Fighting"],
    "Tyrunt": ["Rock", "Dragon"],
    "Umbreon": ["Dark"],
    "Unfezant": ["Normal", "Flying"],
    "Unown": ["Psychic"],
    "Ursaluna": ["Ground", "Normal"],
    "Ursaluna Bloodmoon": ["Ground", "Normal"],
    "Ursaring": ["Normal"],
    "Urshifu": ["Fighting", "Dark"],
    "Urshifu Rapid Strike": ["Fighting", "Water"],
    "Urshifu Rapid Strike Gmax": ["Fighting", "Water"],
    "Urshifu Single Strike": ["Fighting", "Dark"],
    "Urshifu Single Strike Gmax": ["Fighting", "Dark"],
    "Urshifu-Rapid-Strike": ["Fighting", "Water"],
    "Uxie": ["Psychic"],
    "Vanillish": ["Ice"],
    "Vanillite": ["Ice"],
    "Vanilluxe": ["Ice"],
    "Vaporeon": ["Water"],
    "Varoom": ["Steel", "Poison"],
    "Veluza": ["Water", "Psychic"],
    "Venipede": ["Bug", "Poison"],
    "Venomoth": ["Bug", "Poison"],
    "Venonat": ["Bug", "Poison"],
    "Venusaur": ["Grass", "Poison"],
    "Venusaur (Mega)": ["Grass", "Poison"],
    "Venusaur Gmax": ["Grass", "Poison"],
    "Venusaur-Mega": ["Grass", "Poison"],
    "Vespiquen": ["Bug", "Flying"],
    "Vibrava": ["Ground", "Dragon"],
    "Victini": ["Psychic", "Fire"],
    "Victreebel": ["Grass", "Poison"],
    "Victreebel (Mega)": ["Grass", "Poison"],
    "Victreebel-Mega": ["Grass", "Poison"],
    "Vigoroth": ["Normal"],
    "Vikavolt": ["Bug", "Electric"],
    "Vikavolt Totem": ["Bug", "Electric"],
    "Vileplume": ["Grass", "Poison"],
    "Virizion": ["Grass", "Fighting"],
    "Vivillon": ["Bug", "Flying"],
    "Volbeat": ["Bug"],
    "Volcanion": ["Fire", "Water"],
    "Volcarona": ["Bug", "Fire"],
    "Voltorb": ["Electric"],
    "Voltorb Hisui": ["Electric", "Grass"],
    "Voltorb-Hisui": ["Electric", "Grass"],
    "Vullaby": ["Dark", "Flying"],
    "Vulpix": ["Fire"],
    "Vulpix Alola": ["Ice"],
    "Vulpix-Alola": ["Ice"],
    "Wailmer": ["Water"],
    "Wailord": ["Water"],
    "Walking Wake": ["Water", "Dragon"],
    "Walrein": ["Ice", "Water"],
    "Wartortle": ["Water"],
    "Watchog": ["Normal"],
    "Wattrel": ["Electric", "Flying"],
    "Weavile": ["Dark", "Ice"],
    "Weedle": ["Bug", "Poison"],
    "Weepinbell": ["Grass", "Poison"],
    "Weezing": ["Poison"],
    "Weezing Galar": ["Poison", "Fairy"],
    "Weezing-Galar": ["Poison", "Fairy"],
    "Whimsicott": ["Grass", "Fairy"],
    "Whirlipede": ["Bug", "Poison"],
    "Whiscash": ["Water", "Ground"],
    "Whismur": ["Normal"],
    "Wigglytuff": ["Normal", "Fairy"],
    "Wiglett": ["Water"],
    "Wimpod": ["Bug", "Water"],
    "Wingull": ["Water", "Flying"],
    "Wishiwashi School": ["Water"],
    "Wishiwashi Solo": ["Water"],
    "Wishiwashi-School": ["Water"],
    "Wishiwashi-Solo": ["Water"],
    "Wo Chien": ["Dark", "Grass"],
    "Wobbuffet": ["Psychic"],
    "Woobat": ["Psychic", "Flying"],
    "Wooloo": ["Normal"],
    "Wooper": ["Water", "Ground"],
    "Wooper Paldea": ["Poison", "Ground"],
    "Wooper-Paldea": ["Poison", "Ground"],
    "Wormadam Plant": ["Bug", "Grass"],
    "Wormadam Sandy": ["Bug", "Ground"],
    "Wormadam Trash": ["Bug", "Steel"],
    "Wormadam-Plant": ["Bug", "Grass"],
    "Wormadam-Sandy": ["Bug", "Ground"],
    "Wormadam-Trash": ["Bug", "Steel"],
    "Wugtrio": ["Water"],
    "Wurmple": ["Bug"],
    "Wynaut": ["Psychic"],
    "Wyrdeer": ["Normal", "Psychic"],
    "Xatu": ["Psychic", "Flying"],
    "Xerneas": ["Fairy"],
    "Xurkitree": ["Electric"],
    "Yamask": ["Ghost"],
    "Yamask Galar": ["Ground", "Ghost"],
    "Yamask-Galar": ["Ground", "Ghost"],
    "Yamper": ["Electric"],
    "Yanma": ["Bug", "Flying"],
    "Yanmega": ["Bug", "Flying"],
    "Yungoos": ["Normal"],
    "Yveltal": ["Dark", "Flying"],
    "Zacian": ["Fairy"],
    "Zacian Crowned": ["Fairy", "Steel"],
    "Zacian-Crowned": ["Fairy", "Steel"],
    "Zamazenta": ["Fighting"],
    "Zamazenta Crowned": ["Fighting", "Steel"],
    "Zamazenta-Crowned": ["Fighting", "Steel"],
    "Zangoose": ["Normal"],
    "Zapdos": ["Electric", "Flying"],
    "Zapdos Galar": ["Fighting", "Flying"],
    "Zapdos-Galar": ["Fighting", "Flying"],
    "Zarude": ["Dark", "Grass"],
    "Zarude Dada": ["Dark", "Grass"],
    "Zebstrika": ["Electric"],
    "Zekrom": ["Dragon", "Electric"],
    "Zeraora": ["Electric"],
    "Zeraora (Mega)": ["Electric"],
    "Zeraora-Mega": ["Electric"],
    "Zigzagoon": ["Normal"],
    "Zigzagoon Galar": ["Dark", "Normal"],
    "Zigzagoon-Galar": ["Dark", "Normal"],
    "Zoroark": ["Dark"],
    "Zoroark Hisui": ["Normal", "Ghost"],
    "Zoroark-Hisui": ["Normal", "Ghost"],
    "Zorua": ["Dark"],
    "Zorua Hisui": ["Normal", "Ghost"],
    "Zorua-Hisui": ["Normal", "Ghost"],
    "Zubat": ["Poison", "Flying"],
    "Zweilous": ["Dark", "Dragon"],
    "Zygarde (Mega)": ["Dragon", "Ground"],
    "Zygarde 10": ["Dragon", "Ground"],
    "Zygarde 10 Power Construct": ["Dragon", "Ground"],
    "Zygarde 50": ["Dragon", "Ground"],
    "Zygarde 50 Power Construct": ["Dragon", "Ground"],
    "Zygarde Complete": ["Dragon", "Ground"],
    "Zygarde-Complete": ["Dragon", "Ground"],
    "Zygarde-Mega": ["Dragon", "Ground"],
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


def _parse_hp_pct(field: str):
    """'55/100' -> 55.0, '0 fnt' -> 0.0, '100/100 slp' -> 100.0, unparseable -> None."""
    field = field.strip()
    if field.startswith("0 fnt") or field == "0":
        return 0.0
    m = re.match(r"(\d+)\s*/\s*(\d+)", field)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        return (num / den * 100.0) if den else None
    return None


def _norm_forme_keep_mega(name: str) -> str:
    """Like _norm_forme but PRESERVES -Mega/-Mega-X/-Mega-Y/-Mega-Z/-Primal, which
    are separately-drafted picks. Used on the recap switch-in so a mega that
    switches out and back in ("Swampert-Mega") is not collapsed to base
    "Swampert" (which would undo the |detailschange| re-attribution). Still strips
    the cosmetic Ogerpon-mask / Tera suffixes that don't change the drafted pick."""
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
    rosters = {"p1": [], "p2": []}  # team-preview order
    brought = {"p1": set(), "p2": set()}
    active = {}  # slot → name
    turn = 0
    cur_move = None  # {side, user, move}
    pending_se = {}  # slot → bool
    last_hit = {}  # slot → {bySide, by, move, se, indirect}
    ko_log = []  # raw chronological faints
    hazard_setter = {"p1": {}, "p2": {}}  # side -> {hazard_id: {side,name}}
    status_by = {}  # victim slot -> {side, name} that inflicted status
    future_move_by = {"p1": None, "p2": None}  # target side -> {side,name} of a
    # pending Future Sight / Doom Desire user
    winner_player = None
    leads = {"p1": [], "p2": []}  # first 2 switch-ins per side before turn 2
    _leads_locked = {"p1": False, "p2": False}

    # ── Battle-highlight collectors (additive; never affect KO attribution) ──
    hl_boosts = []
    hl_peak = {}  # (side, mon, stat) -> max cumulative stage (signed)
    hl_stage = {}  # slot -> {stat: current cumulative stage}
    hl_crits = []
    hl_items = []
    hl_teras = []
    hl_misses = []
    hp_pct = {}  # slot -> last-known HP percent (0-100), for crit "mattered"
    _pending_crit = {}  # victim slot -> hp_before (percent) until the -damage resolves it

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
            # Use the SPECIES from parts[3], not the nickname in parts[2], so recap
            # rosters/KO-log attribute to the real mon (matches parse_log).
            # Keep -Mega/-Primal here (separate picks); a mega switching back in as
            # "Swampert-Mega" must not collapse to base "Swampert".
            poke_name = _norm_forme_keep_mega(
                _norm(parts[3].split(",")[0].strip())
            ) or _extract_name(parts[2])
            if slot and poke_name:
                active[slot] = poke_name
                pside = _slot_player(slot)
                brought[pside].add(poke_name)
                if not _leads_locked[pside] and poke_name not in leads[pside]:
                    leads[pside].append(poke_name)
                last_hit.pop(slot, None)
                status_by.pop(slot, None)
                hp_pct[slot] = 100
                hl_stage.pop(slot, None)
                _pending_crit.pop(slot, None)

        elif cmd in ("detailschange", "-formechange") and len(parts) >= 4:
            # Mirror parse_log: mega/primal re-points the slot to the suffix species
            # so recap ko_log + brought attribute to the mega pick (build_recap's
            # resolve() maps it to the drafted "Mega X"). Battle formes stay unified
            # via the _MEGA_PRIMAL_RE guard. The recap has no kills accumulator to
            # migrate — re-pointing active[slot] covers both victim (|faint|) and
            # killer (|move|) attribution; we only migrate `brought` so base+mega
            # don't both appear.
            slot = _extract_slot(parts[2])
            new_name = _norm(parts[3].split(",")[0].strip())
            if slot and new_name and _MEGA_PRIMAL_RE.search(new_name):
                pside = _slot_player(slot)
                old_name = active.get(slot)
                if old_name and old_name != new_name:
                    brought[pside].discard(old_name)
                active[slot] = new_name
                brought[pside].add(new_name)

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
                        "bySide": atk_side,
                        "by": atk_name,
                        "move": move_name,
                        "se": False,
                        "indirect": False,
                    }
                if move_name in ("Future Sight", "Doom Desire"):
                    tgt_side = (
                        _slot_player(primary)
                        if primary
                        else ("p2" if atk_side == "p1" else "p1")
                    )
                    future_move_by[tgt_side] = {"side": atk_side, "name": atk_name}

        elif cmd == "-boost" and len(parts) >= 4:
            slot = _extract_slot(parts[2])
            stat = parts[3].strip()
            try:
                amt = (
                    int(parts[4])
                    if len(parts) >= 5 and parts[4].lstrip("-").isdigit()
                    else 1
                )
            except (ValueError, IndexError):
                amt = 1
            if slot and stat and active.get(slot):
                cur = hl_stage.setdefault(slot, {})
                cur[stat] = cur.get(stat, 0) + amt
                key = (_slot_player(slot), active[slot], stat)
                if abs(cur[stat]) > abs(hl_peak.get(key, 0)):
                    hl_peak[key] = cur[stat]
                hl_boosts.append(
                    {
                        "turn": turn,
                        "side": _slot_player(slot),
                        "mon": active[slot],
                        "stat": stat,
                        "by": amt,
                    }
                )

        elif cmd == "-unboost" and len(parts) >= 4:
            slot = _extract_slot(parts[2])
            stat = parts[3].strip()
            try:
                amt = (
                    int(parts[4])
                    if len(parts) >= 5 and parts[4].lstrip("-").isdigit()
                    else 1
                )
            except (ValueError, IndexError):
                amt = 1
            if slot and stat and active.get(slot):
                cur = hl_stage.setdefault(slot, {})
                cur[stat] = cur.get(stat, 0) - amt
                key = (_slot_player(slot), active[slot], stat)
                if abs(cur[stat]) > abs(hl_peak.get(key, 0)):
                    hl_peak[key] = cur[stat]
                hl_boosts.append(
                    {
                        "turn": turn,
                        "side": _slot_player(slot),
                        "mon": active[slot],
                        "stat": stat,
                        "by": -amt,
                    }
                )

        elif cmd == "-crit" and len(parts) >= 3:
            slot = _extract_slot(parts[2])
            if slot:
                _pending_crit[slot] = hp_pct.get(slot, 100.0)  # HP BEFORE this hit

        elif cmd == "-terastallize" and len(parts) >= 4:
            slot = _extract_slot(parts[2])
            ttype = parts[3].strip()
            if slot and ttype and active.get(slot):
                hl_teras.append(
                    {
                        "turn": turn,
                        "side": _slot_player(slot),
                        "mon": active[slot],
                        "type": ttype,
                    }
                )

        elif cmd in ("-item", "-enditem") and len(parts) >= 4:
            slot = _extract_slot(parts[2])
            item = parts[3].strip()
            if slot and item and active.get(slot):
                hl_items.append(
                    {
                        "turn": turn,
                        "side": _slot_player(slot),
                        "mon": active[slot],
                        "item": item,
                        "event": "consumed" if cmd == "-enditem" else "reveal",
                    }
                )

        elif cmd == "-miss" and len(parts) >= 3:
            atk_slot = _extract_slot(parts[2])
            tgt_slot = _extract_slot(parts[3]) if len(parts) >= 4 else ""
            if atk_slot and active.get(atk_slot):
                hl_misses.append(
                    {
                        "turn": turn,
                        "attacker_side": _slot_player(atk_slot),
                        "attacker": active[atk_slot],
                        "target": active.get(tgt_slot),
                    }
                )

        elif cmd == "-heal" and len(parts) >= 3:
            slot = _extract_slot(parts[2])
            hp = (
                _parse_hp_pct("|".join(parts[3:]).split("|")[0])
                if len(parts) >= 3
                else None
            )
            if slot and hp is not None:
                hp_pct[slot] = hp

        elif cmd == "-sidestart" and len(parts) >= 4:
            side = parts[2].split(":")[0].strip()
            hz = _hazard_id(parts[3])
            # Only credit a hazard set on the OPPONENT's side (Court Change guard).
            if side in ("p1", "p2") and hz and cur_move and cur_move["side"] != side:
                hazard_setter[side][hz] = {
                    "side": cur_move["side"],
                    "name": cur_move["user"],
                }

        elif cmd == "-sideend" and len(parts) >= 4:
            side = parts[2].split(":")[0].strip()
            hz = _hazard_id(parts[3])
            if side in ("p1", "p2") and hz:
                hazard_setter[side].pop(hz, None)

        elif cmd == "-status" and len(parts) >= 4:
            vslot = _extract_slot(parts[2])
            rest = "|".join(parts[4:])
            of_m = re.search(r"\[of\]\s*(p[12][ab]):", rest)
            if not vslot:
                pass
            elif of_m and of_m.group(1) != vslot:
                # Ability-inflicted (Flame Body etc.) — credit the [of] mon.
                src = of_m.group(1)
                if active.get(src):
                    status_by[vslot] = {"side": _slot_player(src), "name": active[src]}
            elif "[from]" in rest:
                # Self-inflicted (Flame/Toxic Orb, Rest) or hazard status — not the
                # last mover; credit no one here.
                pass
            elif cur_move and cur_move["side"] != _slot_player(vslot):
                status_by[vslot] = {"side": cur_move["side"], "name": cur_move["user"]}

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
            of_m = re.search(r"\[of\]\s*(p[12][ab]):\s*(.+)", rest)
            if of_m:
                # [from] X |[of] p2a: Ferrothorn — a mon (Rocky Helmet, Rough Skin,
                # Iron Barbs, poison from Toxic Spikes set by a mon, etc.) DID cause
                # this; credit that attacker, not "no one". Check [of] BEFORE [from].
                src_slot = of_m.group(1)
                src_name = active.get(src_slot) or _norm_forme(
                    _norm(of_m.group(2).strip().split(",")[0])
                )
                fm = re.search(r"\[from\]\s*([^|]+)", rest)
                source = fm.group(1).strip() if fm else "?"
                last_hit[victim_slot] = {
                    "bySide": _slot_player(src_slot),
                    "by": src_name,
                    "move": source,
                    "se": False,
                    "indirect": False,
                }
            elif "[from]" in rest:
                fm = re.search(r"\[from\]\s*([^|]+)", rest)
                source = fm.group(1).strip() if fm else "passive"
                # Attribute the cause: hazards -> setter, poison/burn -> applier.
                # Life Orb / recoil / weather stay unattributed (by=None).
                vside = _slot_player(victim_slot)
                hz = _hazard_id(source)
                cause = None
                if hz and hz in hazard_setter.get(vside, {}):
                    cause = hazard_setter[vside][hz]
                elif source in ("brn", "psn", "tox"):
                    if victim_slot in status_by:
                        cause = status_by[victim_slot]
                    elif source in (
                        "psn",
                        "tox",
                    ) and "toxic spikes" in hazard_setter.get(vside, {}):
                        cause = hazard_setter[vside]["toxic spikes"]
                elif source in ("move: Future Sight", "move: Doom Desire"):
                    cause = future_move_by.get(vside)
                last_hit[victim_slot] = {
                    "bySide": cause["side"] if cause else None,
                    "by": cause["name"] if cause else None,
                    "move": source,
                    "se": False,
                    "indirect": True,
                }
            elif cur_move:
                is_se = bool(pending_se.get(victim_slot))
                last_hit[victim_slot] = {
                    "bySide": cur_move["side"],
                    "by": cur_move["user"],
                    "move": cur_move["move"],
                    "se": is_se,
                    "indirect": False,
                }
            new_hp = (
                _parse_hp_pct("|".join(parts[3:]).split("|")[0])
                if len(parts) >= 3
                else None
            )
            fainted_now = "fnt" in "|".join(parts[3:])
            if victim_slot in _pending_crit:
                hp_before = _pending_crit.pop(victim_slot)
                mattered = None
                if fainted_now and hp_before is not None:
                    crit_dmg = hp_before  # went to 0
                    normal_dmg = crit_dmg / 1.5
                    # crit mattered if a normal hit would NOT have KO'd (victim survives)
                    mattered = (hp_before - normal_dmg) > 0 and hp_before >= 34
                    # (hp_before>=34 gate: below ~1/3, a full-power normal hit also KOs)
                lh = last_hit.get(victim_slot) or {}
                hl_crits.append(
                    {
                        "turn": turn,
                        "victim_side": _slot_player(victim_slot),
                        "victim": active.get(victim_slot),
                        "attacker": lh.get("by"),
                        "move": lh.get("move"),
                        "ko": fainted_now,
                        "mattered": mattered,
                    }
                )
            if new_hp is not None:
                hp_pct[victim_slot] = new_hp
            pending_se[victim_slot] = False

        elif cmd == "faint" and len(parts) >= 3:
            slot = _extract_slot(parts[2])
            if not slot:
                continue
            fainted = active.get(slot) or _extract_name(parts[2])
            fplayer = _slot_player(slot)
            if fainted:
                k = last_hit.get(slot, {})
                ko_log.append(
                    {
                        "t": turn,
                        "victimSide": fplayer,
                        "victim": fainted,
                        "by": k.get("by"),
                        "bySide": k.get("bySide"),
                        "move": k.get("move", "?"),
                        "se": bool(k.get("se")),
                        "indirect": bool(k.get("indirect")),
                    }
                )
            active.pop(slot, None)
            # Invalidate a just-fainted mon as the "last mover" so it can't be
            # credited for a status/hazard applied after its faint line.
            if (
                cur_move
                and cur_move.get("side") == fplayer
                and cur_move.get("user") == fainted
            ):
                cur_move = None

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
        "highlights": {
            "boosts": hl_boosts,
            "peak_boosts": [
                {"side": s, "mon": m, "stat": st, "stage": v}
                for (s, m, st), v in hl_peak.items()
                if abs(v) >= 2
            ],
            "crits": hl_crits,
            "items": hl_items,
            "teras": hl_teras,
            "misses": hl_misses,
        },
    }


def build_recap(
    raw: dict,
    meta: dict = None,
    typedex: dict = None,
    name_map_p1: dict = None,
    name_map_p2: dict = None,
) -> dict:
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
            rosters_resolved[pside] = sorted(
                {resolve(pside, n) for n in raw["brought"][pside]}
            )

    # Bring-N-Use-M detection: if fewer mons were switched in than were in team preview,
    # filter the displayed roster to only the mons actually used.
    # e.g. Bring 6 Use 4 — the 2 benched mons never appear and must not inflate "left" count.
    brought_resolved = {
        pside: {resolve(pside, n) for n in raw["brought"][pside]}
        for pside in ("p1", "p2")
    }
    for pside in ("p1", "p2"):
        b = brought_resolved[pside]
        # Reconcile whenever the brought SET differs from the team-preview set — not
        # only when fewer were brought. A mega (team preview shows base "Swampert";
        # the mon actually brought resolves to "Mega Swampert") is a same-count-but-
        # different-name case: without this the mega's KOs land on a name that's
        # never displayed and vanish from the recap card.
        if b and set(rosters_resolved[pside]) != b:
            # Keep team-preview order but only for used mons
            rosters_resolved[pside] = [n for n in rosters_resolved[pside] if n in b]
            # Append any used mon not in team preview (mega/primal or forme change)
            for n in sorted(b - set(rosters_resolved[pside])):
                rosters_resolved[pside].append(n)

    # How many mons each side used (4 in bring-6-use-4; 6 in standard 6v6)
    use_counts = {pside: len(rosters_resolved[pside]) for pside in ("p1", "p2")}

    # Build per-mon kill/faint tallies from ko_log
    kills_by_mon = {}  # (pside, name) → count
    fainted_mons = {}  # (pside, name) → bool
    for entry in raw["ko_log"]:
        vs_key = (entry["victimSide"], resolve(entry["victimSide"], entry["victim"]))
        fainted_mons[vs_key] = True
        # Credit the KO whenever an attacker is known — direct hits AND indirect
        # faints attributed to a hazard-setter / status-applier. Only genuinely
        # unattributed indirect faints (Life Orb, recoil; by=None) are excluded.
        if entry["bySide"] and entry["by"]:
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
                if e["bySide"] == pside
                and resolve(pside, e.get("by") or "") == name
                and e["by"]
            ]
            if kos:
                note = "KO " + ", ".join(victims)
            elif fainted:
                note = "fainted"
            else:
                note = "survived"
            types = td.get(name, ["Normal"])
            mons.append(
                {
                    "name": name,
                    "types": types,
                    "kos": kos,
                    "fainted": fainted,
                    "lead": is_lead,
                    "note": note,
                }
            )
        return mons

    home_roster = build_roster(home_pid)
    away_roster = build_roster(away_pid)

    # KO log in HOME/AWAY terms
    ko_log2 = []
    for entry in raw["ko_log"]:
        side_label = (
            "HOME"
            if entry["bySide"] == home_pid
            else "AWAY"
            if entry["bySide"] == away_pid
            else "PASSIVE"
        )
        ko_log2.append(
            {
                "t": entry["t"],
                "side": side_label,
                "by": resolve(entry["bySide"] or home_pid, entry["by"] or "—"),
                "vs": resolve(entry["victimSide"], entry["victim"]),
                "move": entry["move"],
                "se": entry["se"],
                "indirect": entry["indirect"],
                "note": "",
            }
        )

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
        "home": {
            "ko": _sum_kos(home_roster),
            "left": _left(home_roster),
            "brought": bring_counts["home"],
            "used": use_counts[home_pid],
        },
        "away": {
            "ko": _sum_kos(away_roster),
            "left": _left(away_roster),
            "brought": bring_counts["away"],
            "used": use_counts[away_pid],
        },
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
        # Match kills_by_mon / build_roster.victims: an indirect KO with a known
        # attacker (hazard setter / status applier) counts. Only truly unattributed
        # faints (by=None) are excluded — keep this predicate in sync with L2134/L2157.
        return [
            resolve(e["victimSide"], e["victim"])
            for e in raw["ko_log"]
            if e["bySide"] == pside
            and resolve(pside, e.get("by") or "") == name
            and e["by"]
        ]

    sorted_home = sorted(home_roster, key=lambda m: -m["kos"])
    sorted_away = sorted(away_roster, key=lambda m: -m["kos"])
    s1 = (
        sorted_home[0]
        if sorted_home
        else {"name": "—", "types": ["Normal"], "kos": 0, "fainted": False}
    )
    s2 = (
        sorted_away[0]
        if sorted_away
        else {"name": "—", "types": ["Normal"], "kos": 0, "fainted": False}
    )
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
        return (
            "Traded damage and survived."
            if not s3["fainted"]
            else "Took hits to keep the team going."
        )

    stars = [
        {
            "star": 1,
            "side": "HOME",
            "mon": {"name": s1["name"], "types": s1["types"]},
            "line": f"{s1['kos']} KO · {'fainted' if s1['fainted'] else 'survived'}",
            "blurb": _star_blurb1(),
        },
        {
            "star": 2,
            "side": "AWAY",
            "mon": {"name": s2["name"], "types": s2["types"]},
            "line": f"{s2['kos']} KO · {'fainted' if s2['fainted'] else 'survived'}",
            "blurb": _star_blurb2(),
        },
        {
            "star": 3,
            "side": "HOME",
            "mon": {"name": s3["name"], "types": s3["types"]},
            "line": f"{s3['kos']} KO · {'fainted' if s3['fainted'] else 'survived'}",
            "blurb": _star_blurb3(),
        },
    ]

    # Auto-detect bring/use for format string
    _bring = max(bring_counts["home"], bring_counts["away"])
    _use = max(use_counts[home_pid], use_counts[away_pid])
    _is_bring_use = _bring > _use and _use > 0
    _auto_format = (
        f"Bring {_bring} / Use {_use} · Showdown replay"
        if _is_bring_use
        else "6v6 · Showdown replay"
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
        initials = "".join(w[0] for w in re.sub(r"[^A-Za-z ]", "", uname).split() if w)[
            :2
        ].upper()
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


def commentary_facts(recap: dict) -> dict:
    """Distill a finished build_recap dict into the compact fact set both the
    template commentary and an LLM prompt work from. Kept separate so the LLM
    path can hand the model clean structured data, not the whole recap."""
    home = recap.get("home", {}).get("name", "Home")
    away = recap.get("away", {}).get("name", "Away")
    totals = recap.get("totals", {})
    winner_side = totals.get("winner")  # "HOME"/"AWAY"
    winner = home if winner_side == "HOME" else away
    loser = away if winner_side == "HOME" else home
    plays = []
    for k in recap.get("koLog", []):
        by_name = home if k.get("side") == "HOME" else away
        plays.append(
            {
                "turn": k.get("t"),
                "attacker_team": by_name,
                "attacker": k.get("by") or None,
                "victim": k.get("vs"),
                "move": k.get("move"),
                "super_effective": bool(k.get("se")),
                "indirect": bool(k.get("indirect")),
            }
        )
    # Biggest lead the eventual loser held (a comeback signal).
    max_deficit = 0
    for m in recap.get("momentum", []):
        h, a = m.get("home", 0), m.get("away", 0)
        # deficit from the winner's perspective (mons remaining)
        wl = (h - a) if winner_side == "HOME" else (a - h)
        if wl < 0:
            max_deficit = min(max_deficit, wl)
    stars = [
        {
            "name": (s.get("mon") or {}).get("name", "?"),
            "team": home if s.get("side") == "HOME" else away,
            "kos": s.get("line", ""),
        }
        for s in recap.get("stars", [])
    ]
    return {
        "home": home,
        "away": away,
        "winner": winner,
        "loser": loser,
        "score": f"{totals.get('home', {}).get('ko', 0)}-{totals.get('away', {}).get('ko', 0)}",
        "turns": recap.get("facts", {}).get("turns"),
        "comeback_from": -max_deficit,  # how many mons down the winner was at worst
        "plays": plays,
        "stars": stars,
    }


def _ordinal_move_phrase(p: dict) -> str:
    """One KO play → a punchy sentence. Varies phrasing by index-free signals
    (super-effective, indirect, move) so lines don't read identically."""
    atk, vic, mv = p["attacker"], p["victim"], p["move"]
    if p["indirect"] or not atk:
        # hazard / status / self chip
        if atk:
            return f"T{p['turn']}: {vic} went down to {atk}'s {mv}."
        return f"T{p['turn']}: {vic} was worn down by {mv}."
    if p["super_effective"]:
        verbs = ["crashed through", "blew past", "melted", "steamrolled"]
        v = verbs[(p["turn"] or 0) % len(verbs)]
        return f"T{p['turn']}: {atk}'s {mv} {v} {vic} (super effective)."
    verbs = ["took down", "put away", "removed", "finished off"]
    v = verbs[(p["turn"] or 0) % len(verbs)]
    return f"T{p['turn']}: {atk}'s {mv} {v} {vic}."


def build_commentary(recap: dict) -> dict:
    """Deterministic 'both' commentary from a finished recap: a short narrative
    summary + a KO-by-KO play-by-play. Always available (no network/model). An
    LLM enhancement can replace `summary`/`plays` later; `source` marks which.
    Returns {"summary": str, "plays": [str], "source": "template"}."""
    f = commentary_facts(recap)
    winner, loser, score = f["winner"], f["loser"], f["score"]
    turns, comeback = f["turns"], f["comeback_from"]
    n_plays = len(f["plays"])

    # ── narrative summary ──
    if n_plays == 0:
        summary = f"{winner} defeated {loser} {score}."
    else:
        opener_side = f["plays"][0]["attacker_team"]
        first_vic = f["plays"][0]["victim"]
        first_atk = f["plays"][0]["attacker"] or "chip damage"
        parts = [
            f"{winner} beat {loser} {score}"
            + (f" over {turns} turns." if turns else ".")
        ]
        if opener_side == loser and comeback >= 2:
            # loser struck first / led, winner came back
            parts.append(
                f"{loser} drew first blood when {first_atk} took out {first_vic}, "
                f"and pulled ahead by {comeback}, but {winner} clawed all the way back."
            )
        elif opener_side == winner:
            parts.append(
                f"{winner} set the tone early — {first_atk} opened the scoring on {first_vic} — "
                f"and never let the lead go."
            )
        else:
            parts.append(
                f"{loser} landed the first blow ({first_atk} on {first_vic}), "
                f"but {winner} answered and took control."
            )
        # top star
        if f["stars"]:
            s0 = f["stars"][0]
            parts.append(
                f"{s0['name']} was the difference-maker for {s0['team']} ({s0['kos']})."
            )
        summary = " ".join(parts)

    plays = [_ordinal_move_phrase(p) for p in f["plays"]]
    return {"summary": summary, "plays": plays, "source": "template"}
