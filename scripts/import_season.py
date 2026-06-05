"""Import a past season from Google Sheets into the `seasons` table.

Usage:
    python scripts/import_season.py --help
    python scripts/import_season.py s8   # import Season 8 from hardcoded URL
    python scripts/import_season.py s7   # import Season 7 from per-team tabs

Run from the project root (same directory as app.py / league.db).
"""

import sys
import os
import sqlite3
import json
import csv
import io
import urllib.request
import argparse
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "league.db")

# ── Season definitions ───────────────────────────────────────────────────────
SEASONS = {
    "s8": {
        "season_num": 8,
        "name": "Yuri Cup Season 8",
        "sheet_id": "11nh0W9hdfFsGgLad3SwiLXTYdeSUAJgO-TPQYcGaB_M",
        "data_gid": 774632342,
        "format": "matchup_grid",
    },
    "s7": {
        "season_num": 7,
        "name": "Yuri Cup Season 7",
        "sheet_id": "1t9BogStMx1l_dDwysZ5uEGRE6j11ABYbQVqq8JNcG5s",
        "tabs": [
            # (gid, coach_name, team_name)  — add more as accessible
            (68400228, "Zach", "Georgia Gengars"),
        ],
        "format": "per_team",
    },
}


def fetch_csv(sheet_id, gid):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def _parse_matchup_grid(sheet_id, data_gid):
    """Parse S8-style Data sheet: horizontal weeks, per-pokemon matchup rows.

    Sheet layout:
      Row 5: Week headers at cols 3, 14, 25 ... (every 11 cols)
      Match header rows: [blank, blank, blank, Coach1, W/L, Score1, 'vs.', Score2, W/L, Coach2, ...]
      Pokemon rows:      [blank, blank, blank, poke1,  K1,  D1,     blank, D2,    K2,  poke2, ...]
    """
    raw = fetch_csv(sheet_id, data_gid)
    rows = list(csv.reader(io.StringIO(raw)))

    WEEK_COLS = [3 + 11 * i for i in range(15)]  # 0-indexed start col for each week

    coaches = {}   # name.lower() → {name, matches}
    matches = []   # [{week, c1, s1, c2, s2, pokemons: [{c1_poke, c1k, c1d, c2_poke, c2k, c2d}]}]

    for week_idx, base in enumerate(WEEK_COLS):
        week = week_idx + 1
        current_match = None

        for row in rows:
            if len(row) <= base + 7:
                continue
            vals = row[base:base + 8]  # 8 cells per match block

            # Completely empty row in this week's column range — skip but keep current_match
            # (the sheet has blank rows between match header and pokemon rows)
            if not any(v.strip() for v in vals):
                continue

            c1_cell = vals[1].strip() if len(vals) > 1 else ""
            sep_cell = vals[4].strip() if len(vals) > 4 else ""
            c2_cell = vals[7].strip() if len(vals) > 7 else ""

            if sep_cell == "vs.":
                # Match header row: Coach1, W/L, Score, vs., Score, W/L, Coach2
                c1_name = c1_cell
                c2_name = c2_cell
                try:
                    s1 = float(vals[3].strip()) if vals[3].strip() else 0
                    s2 = float(vals[5].strip()) if vals[5].strip() else 0
                except ValueError:
                    s1, s2 = 0, 0
                current_match = {
                    "week": week,
                    "c1": c1_name, "s1": s1,
                    "c2": c2_name, "s2": s2,
                    "pokemons": [],
                }
                matches.append(current_match)
                for name in (c1_name, c2_name):
                    key = name.lower().strip()
                    if key and key not in coaches:
                        coaches[key] = {"name": name}
            elif current_match is not None:
                # Pokemon row: poke1, K1, D1, blank, D2, K2, poke2
                poke1 = vals[1].strip() if len(vals) > 1 else ""
                poke2 = vals[7].strip() if len(vals) > 7 else ""
                if not poke1 and not poke2:
                    continue  # empty pokemon row — skip, don't reset match
                try:
                    k1 = float(vals[2].strip() or 0)
                    d1 = float(vals[3].strip() or 0)
                    d2 = float(vals[5].strip() or 0)
                    k2 = float(vals[6].strip() or 0)
                except (ValueError, IndexError):
                    k1 = d1 = k2 = d2 = 0
                current_match["pokemons"].append({
                    "c1_poke": poke1, "c1k": k1, "c1d": d1,
                    "c2_poke": poke2, "c2k": k2, "c2d": d2,
                })

    # Assign numeric IDs to coaches
    coach_list = []
    cid_map = {}
    for i, (key, c) in enumerate(sorted(coaches.items(), key=lambda x: x[0])):
        cid = i + 1
        cid_map[key] = cid
        coach_list.append({
            "id": cid,
            "coach_name": c["name"],
            "team_name": c["name"] + " FC",
            "pool": "A" if i < len(coaches) // 2 else "B",
            "color": "#888888",
            "logo_url": "",
        })

    schedule = []
    match_stats = []
    pokemon_roster = {}  # (cid, poke_name) → {points:0}

    for mid, m in enumerate(matches):
        c1k = cid_map.get(m["c1"].lower().strip(), 0)
        c2k = cid_map.get(m["c2"].lower().strip(), 0)
        if not c1k or not c2k:
            continue
        sid = mid + 1
        schedule.append({
            "id": sid, "week": m["week"], "pool": "A",
            "coach1_id": c1k, "score1": m["s1"],
            "coach2_id": c2k, "score2": m["s2"],
        })
        for p in m["pokemons"]:
            if p["c1_poke"]:
                match_stats.append({
                    "schedule_id": sid, "coach_id": c1k,
                    "pokemon_name": p["c1_poke"],
                    "kills": p["c1k"], "deaths": p["c1d"],
                })
                pokemon_roster[(c1k, p["c1_poke"])] = {"points": 0, "tier": "Unknown"}
            if p["c2_poke"]:
                match_stats.append({
                    "schedule_id": sid, "coach_id": c2k,
                    "pokemon_name": p["c2_poke"],
                    "kills": p["c2k"], "deaths": p["c2d"],
                })
                pokemon_roster[(c2k, p["c2_poke"])] = {"points": 0, "tier": "Unknown"}

    roster_list = [
        {"id": i + 1, "coach_id": cid, "pokemon_name": name,
         "tier": info["tier"], "points": info["points"],
         "is_free_pick": 0, "is_zmove_captain": 0}
        for i, ((cid, name), info) in enumerate(pokemon_roster.items())
    ]

    return {
        "coaches": coach_list,
        "schedule": schedule,
        "match_stats": match_stats,
        "pokemon_roster": roster_list,
        "draft_tiers": [],
        "rules": {},
        "settings": {},
        "transactions": [],
    }


def _parse_per_team_tab(sheet_id, tabs):
    """Parse per-team tabs (S7-style). Each tab shows one coach's roster + schedule.

    Tab layout (from gid=68400228):
      Row 2: rank at col 2, coach_name at col 5
      Rows 5-14: pokemon roster (col 16=name, 17=type1, 18=type2, 19=speed)
      Row 15: team_name at col 2
      Row 20: 'Overall Record:' at col 2, record string at col 9, rank at col 13
      Row 21: schedule headers
      Rows 22+: schedule (col 2=week, col 3=opponent, col 12=W/L, col 13=score_diff)
      Rows 21+: per-pokemon stats (col 16=name, 19=GP, 20=K, 21=D, 22=+/-)
    """
    coaches = []
    schedule_raw = []
    pokemon_roster = {}
    match_stats_raw = {}  # coach_name.lower() → {poke: {kills, deaths, gp}}

    for gid, coach_hint, team_hint in tabs:
        try:
            raw = fetch_csv(sheet_id, gid)
        except Exception as e:
            print(f"  WARNING: could not fetch gid={gid}: {e}")
            continue

        rows = list(csv.reader(io.StringIO(raw)))
        if len(rows) < 5:
            continue

        # Find coach name and team name
        coach_name = coach_hint
        team_name = team_hint
        for row in rows[:20]:
            if len(row) > 5 and row[5].strip():
                coach_name = row[5].strip()
            if len(row) > 2 and row[2].strip() and not row[2].strip().startswith("#"):
                candidate = row[2].strip()
                if len(candidate) > 5 and "Record" not in candidate and "Schedule" not in candidate:
                    team_name = candidate

        cid = len(coaches) + 1
        coaches.append({
            "id": cid,
            "coach_name": coach_name,
            "team_name": team_name,
            "pool": "A",
            "color": "#888888",
            "logo_url": "",
        })

        # Parse pokemon roster (rows where col 16 has a pokemon name)
        poke_stats = {}
        for row in rows:
            if len(row) < 22:
                continue
            poke = row[16].strip() if len(row) > 16 else ""
            if not poke or poke in ("Pokémon", "Pokemon", "Pok�mon"):
                continue
            try:
                gp = int(row[19].strip()) if len(row) > 19 and row[19].strip().isdigit() else 0
                k = float(row[20].strip()) if len(row) > 20 and row[20].strip() else 0
                d = float(row[21].strip()) if len(row) > 21 and row[21].strip() else 0
            except (ValueError, IndexError):
                gp = k = d = 0
            if poke and (gp > 0 or k > 0 or d > 0 or len(row[16].strip()) > 1):
                poke_stats[poke] = {"gp": gp, "kills": k, "deaths": d}
                pokemon_roster[(cid, poke)] = {"points": 0, "tier": "Unknown"}

        match_stats_raw[cid] = poke_stats

        # Parse schedule (rows with week number at col 2 and opponent at col 3)
        for row in rows:
            if len(row) < 14:
                continue
            week_str = row[2].strip()
            opp = row[3].strip() if len(row) > 3 else ""
            result = row[12].strip() if len(row) > 12 else ""
            score_str = row[13].strip() if len(row) > 13 else ""
            if not week_str.isdigit() or not opp:
                continue
            try:
                week = int(week_str)
                score_diff = float(score_str) if score_str.lstrip("+-").replace(".", "").isdigit() else 0
            except ValueError:
                continue
            schedule_raw.append({
                "week": week,
                "coach_name": coach_name,
                "opponent": opp.strip(),
                "result": result.upper(),
                "score_diff": score_diff,
            })

    # Build coach lookup by name
    cname_map = {c["coach_name"].lower().strip(): c["id"] for c in coaches}

    # Assign IDs to unknown opponents
    for entry in schedule_raw:
        opp_key = entry["opponent"].lower().strip()
        if opp_key not in cname_map:
            cid = len(coaches) + 1
            coaches.append({
                "id": cid,
                "coach_name": entry["opponent"].strip(),
                "team_name": entry["opponent"].strip() + " FC",
                "pool": "B",
                "color": "#888888",
                "logo_url": "",
            })
            cname_map[opp_key] = cid
    for c in coaches:
        cname_map[c["coach_name"].lower().strip()] = c["id"]

    # Build schedule deduplicating (A vs B = B vs A for same week)
    seen_matches = {}
    schedule = []
    mid = 1
    for entry in schedule_raw:
        c1id = cname_map.get(entry["coach_name"].lower().strip(), 0)
        c2id = cname_map.get(entry["opponent"].lower().strip(), 0)
        if not c1id or not c2id:
            continue
        mk = (entry["week"], min(c1id, c2id), max(c1id, c2id))
        if mk in seen_matches:
            continue
        seen_matches[mk] = True
        if entry["result"] == "W":
            s1, s2 = max(1.0, abs(entry["score_diff"]) // 2 + 1), max(0.0, abs(entry["score_diff"]) // 2 - 1)
        elif entry["result"] == "L":
            s2, s1 = max(1.0, abs(entry["score_diff"]) // 2 + 1), max(0.0, abs(entry["score_diff"]) // 2 - 1)
        else:
            s1 = s2 = 0
        schedule.append({
            "id": mid, "week": entry["week"], "pool": "A",
            "coach1_id": c1id, "score1": round(s1, 1),
            "coach2_id": c2id, "score2": round(s2, 1),
        })
        mid += 1

    # Build match_stats from per-coach aggregated stats
    ms_list = []
    ms_id = 1
    for cid, poke_stats in match_stats_raw.items():
        for poke, stats in poke_stats.items():
            ms_list.append({
                "id": ms_id,
                "schedule_id": 0,
                "coach_id": cid,
                "pokemon_name": poke,
                "kills": stats["kills"],
                "deaths": stats["deaths"],
            })
            ms_id += 1

    roster_list = [
        {"id": i + 1, "coach_id": cid, "pokemon_name": poke,
         "tier": info["tier"], "points": info["points"],
         "is_free_pick": 0, "is_zmove_captain": 0}
        for i, ((cid, poke), info) in enumerate(pokemon_roster.items())
    ]

    return {
        "coaches": coaches,
        "schedule": schedule,
        "match_stats": ms_list,
        "pokemon_roster": roster_list,
        "draft_tiers": [],
        "rules": {},
        "settings": {},
        "transactions": [],
    }


def upsert_season(conn, season_num, name, data):
    """Insert or update a season in the DB."""
    existing = conn.execute(
        "SELECT id FROM seasons WHERE season_num=?", (season_num,)
    ).fetchone()
    data_json = json.dumps(data)
    now = datetime.utcnow().isoformat()
    if existing:
        conn.execute(
            "UPDATE seasons SET name=?, data_json=?, archived_at=? WHERE id=?",
            (name, data_json, now, existing["id"]),
        )
        print(f"  Updated season {season_num} (id={existing['id']})")
        return existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO seasons (name, season_num, archived_at, data_json) VALUES (?,?,?,?)",
            (name, season_num, now, data_json),
        )
        print(f"  Inserted season {season_num} (id={cur.lastrowid})")
        return cur.lastrowid


def main():
    parser = argparse.ArgumentParser(description="Import a past season from Google Sheets")
    parser.add_argument("season", choices=list(SEASONS.keys()), help="Season key to import")
    parser.add_argument("--dry-run", action="store_true", help="Parse but do not write to DB")
    parser.add_argument("--db", default=DB_PATH, help="Path to league.db")
    args = parser.parse_args()

    cfg = SEASONS[args.season]
    print(f"Importing {cfg['name']} from Google Sheets...")

    if cfg["format"] == "matchup_grid":
        print("  Format: matchup_grid (all-teams Data sheet)")
        data = _parse_matchup_grid(cfg["sheet_id"], cfg["data_gid"])
    elif cfg["format"] == "per_team":
        print(f"  Format: per_team ({len(cfg['tabs'])} tab(s) accessible)")
        data = _parse_per_team_tab(cfg["sheet_id"], cfg["tabs"])
    else:
        print(f"Unknown format: {cfg['format']}")
        sys.exit(1)

    print(f"  Parsed: {len(data['coaches'])} coaches, {len(data['schedule'])} matches, "
          f"{len(data['match_stats'])} stat entries, {len(data['pokemon_roster'])} roster entries")

    if args.dry_run:
        print("  Dry run — not writing to DB")
        print("  Sample coaches:", [c["coach_name"] for c in data["coaches"][:5]])
        return

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        upsert_season(conn, cfg["season_num"], cfg["name"], data)
        conn.commit()
        print(f"Done! Season {cfg['season_num']} saved to {args.db}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
