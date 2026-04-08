import sqlite3
import hashlib
import os
import json
import math
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session, send_from_directory
from functools import wraps
from contextlib import contextmanager

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "yuricup-secret-key-change-me-in-production")
DB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "league.db")
)

SPRITE_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/showdown"
SHOWDOWN_ANI = "https://play.pokemonshowdown.com/sprites/ani"
SPRITE_FALLBACK = "https://img.pokemondb.net/sprites/scarlet-violet/icon"


def _load_pokemon_id_map():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT name, pokeapi_id FROM pokemon_db").fetchall()
        conn.close()
        return {r["name"]: r["pokeapi_id"] for r in rows}
    except Exception:
        return {}


_pokemon_id_map = _load_pokemon_id_map()


def _name_to_slug(name):
    """Convert a display name to one or more candidate PokeAPI slugs."""
    base = name.lower().replace("'", "").replace(".", "").strip()

    # Hard-coded aliases for forms where the PokeAPI slug can't be derived algorithmically
    _FORM_ALIASES = {
        "primal kyogre":         "kyogre-primal",
        "primal groudon":        "groudon-primal",
        "type: null":            "type-null",
        "type null":             "type-null",
        "ogerpon-wellspring":    "ogerpon-wellspring-mask",
        "ogerpon-hearthflame":   "ogerpon-hearthflame-mask",
        "ogerpon-cornerstone":   "ogerpon-cornerstone-mask",
        "calyrex-ice-rider":     "calyrex-ice",
        "calyrex-shadow-rider":  "calyrex-shadow",
        "necrozma-dusk-mane":    "necrozma-dusk",
        "necrozma-dawn-wings":   "necrozma-dawn",
        "basculegion":           "basculegion-male",
        "palafin":               "palafin-zero",
        "giratina-origin":       "giratina-origin",
        "zamazenta-crowned":     "zamazenta-crowned",
        "zacian-crowned":        "zacian-crowned",
        # Default forms (no suffix in display name)
        "giratina":              "giratina-altered",
        "indeedee":              "indeedee-male",
        "minior":                "minior-red-meteor",
        "morpeko":               "morpeko-full-belly",
        "toxtricity":            "toxtricity-amped",
        "aegislash":             "aegislash-shield",
        "darmanitan":            "darmanitan-standard",
        "galarian darmanitan":   "darmanitan-galar-standard",
        "deoxys":                "deoxys-normal",
        "dudunsparce":           "dudunsparce-two-segment",
        "gourgeist":             "gourgeist-average",
        "jellicent":             "jellicent-male",
        "keldeo":                "keldeo-ordinary",
        "maushold":              "maushold-family-of-four",
        "meloetta":              "meloetta-aria",
        "mimikyu":               "mimikyu-disguised",
        "oricorio":              "oricorio-baile",
        "shaymin":               "shaymin-land",
        "zygarde":               "zygarde-50",
        "paldean tauros aqua":   "tauros-paldea-aqua-breed",
        "paldean tauros blaze":  "tauros-paldea-blaze-breed",
        "paldean tauros":        "tauros-paldea-combat-breed",
    }
    alias = _FORM_ALIASES.get(base)

    # Explicit Showdown CDN slug overrides (Showdown uses different naming than PokeAPI)
    _SHOWDOWN_OVERRIDES = {
        # Word order reversed
        "eternamax eternatus":   "eternatus-eternamax",
        # Compound words: Showdown removes hyphens within the compound
        "necrozma-dusk-mane":    "necrozma-duskmane",
        "necrozma-dawn-wings":   "necrozma-dawnwings",
        "urshifu-rapid-strike":  "urshifu-rapidstrike",
        "urshifu-single-strike": "urshifu",       # single-strike is base form
        "pikachu-rock-star":     "pikachu-rockstar",
        "pikachu-pop-star":      "pikachu-popstar",
        # Paldean Tauros: regional slug gives wrong word order, Showdown fuses the suffix
        "paldean tauros":        "tauros-paldeacombat",
        "paldean tauros aqua":   "tauros-paldeaaqua",
        "paldean tauros blaze":  "tauros-paldeablaze",
        # Galarian Mr. Mime: Showdown omits hyphen in "mr-mime"
        "galarian mr mime":      "mrmime-galar",
        # Nidoran gender forms
        "nidoran-female":        "nidoran-f",
        "nidoran-male":          "nidoranm",
        # Ogerpon masks: alias has -mask suffix, Showdown omits it
        "ogerpon-wellspring":    "ogerpon-wellspring",
        "ogerpon-hearthflame":   "ogerpon-hearthflame",
        "ogerpon-cornerstone":   "ogerpon-cornerstone",
        # Special forms with no Showdown sprite — fall back to base
        "pichu-spiky-eared":     "pichu",
    }
    showdown_slug = _SHOWDOWN_OVERRIDES.get(base)

    # Try the naive slug first
    naive = base.replace(" ", "-").replace(":", "")

    # Regional form rewrites: "Galarian X" → "x-galar", "Alolan X" → "x-alola", etc.
    regional_map = {
        "galarian ": "-galar",
        "alolan ":   "-alola",
        "hisuian ":  "-hisui",
        "paldean ":  "-paldea",
    }
    regional_slug = None
    for prefix, suffix in regional_map.items():
        if base.startswith(prefix):
            regional_slug = base[len(prefix):].replace(" ", "-") + suffix
            break

    # Mega forms: "Mega X" → "x-mega", "Mega Charizard X" → "charizard-megax"
    # Note: Showdown omits the hyphen before the variant letter (megax not mega-x)
    mega_slug = None
    if base.startswith("mega "):
        rest = base[5:]
        parts = rest.split()
        if len(parts) >= 2 and parts[-1].lower() in ("x", "y"):
            mega_slug = "-".join(parts[:-1]) + "-mega" + parts[-1]
        else:
            mega_slug = rest.replace(" ", "-") + "-mega"

    # Primal forms: "Primal X" → "x-primal"
    primal_slug = None
    if base.startswith("primal "):
        primal_slug = base[7:].replace(" ", "-") + "-primal"

    # showdown_slug first so slugs[0] is always the correct Showdown CDN slug
    return [s for s in [showdown_slug, regional_slug, mega_slug, primal_slug, alias, naive] if s]


def pokemon_sprite_url(name, shiny=False):
    """Return the animated GIF sprite URL for a Pokemon name.

    Priority:
    1. PokeAPI GitHub showdown GIF via numeric ID (IDs 1-9999, most reliable)
    2. Showdown CDN slug-based URL (covers alt-forms and works without ID map)
    """
    slugs = _name_to_slug(name)
    for slug in slugs:
        pid = _pokemon_id_map.get(slug)
        if pid and pid < 10000:
            folder = f"{SPRITE_BASE}/shiny" if shiny else SPRITE_BASE
            return f"{folder}/{pid}.gif"
    # Fallback: Showdown CDN uses slug filenames directly
    ani_folder = f"{SHOWDOWN_ANI}-shiny" if shiny else SHOWDOWN_ANI
    return f"{ani_folder}/{slugs[0]}.gif"


app.jinja_env.globals["pokemon_sprite_url"] = pokemon_sprite_url


SHOWDOWN_STATIC = "https://play.pokemonshowdown.com/sprites/gen5"


def pokemon_static_sprite_url(name):
    """Return static PNG sprite URL for a Pokemon name.

    Priority:
    1. PokeAPI numeric sprite (IDs 1–9999, reliable)
    2. Showdown gen5 static sprite by slug (covers alt-forms)
    """
    slugs = _name_to_slug(name)
    for slug in slugs:
        pid = _pokemon_id_map.get(slug)
        if pid and pid < 10000:
            return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pid}.png"
    return f"{SHOWDOWN_STATIC}/{slugs[0]}.png"


app.jinja_env.globals["pokemon_static_sprite_url"] = pokemon_static_sprite_url


def _extract_youtube_id(url):
    """Extract YouTube video ID from a watch/share/embed URL."""
    if not url:
        return None
    import re
    for pattern in [
        r"youtu\.be/([^?&\s]+)",
        r"youtube\.com/watch\?(?:.*&)?v=([^&\s]+)",
        r"youtube\.com/embed/([^?&\s]+)",
    ]:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


@app.context_processor
def inject_nav_coaches():
    """Make team list available in every template for the navbar dropdown."""
    try:
        with get_db() as db:
            coaches = db.execute(
                "SELECT id, team_name, coach_name, color, pool FROM coaches ORDER BY pool, team_name"
            ).fetchall()
        return {"nav_coaches": [dict(c) for c in coaches]}
    except Exception:
        return {"nav_coaches": []}


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to access that page.", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in.", "warning")
            return redirect(url_for("login", next=request.path))
        if session.get("role") != "admin":
            flash("Admin access required.", "warning")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


def coach_or_admin_required(f):
    """Allow admin or any logged-in user (coaches can submit match stats)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in.", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_setting(key, default=""):
    with get_db() as db:
        row = db.execute("SELECT value FROM league_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def get_standings(pool=None):
    with get_db() as db:
        coaches = db.execute(
            "SELECT * FROM coaches" + (" WHERE pool=?" if pool else "") + " ORDER BY id",
            (pool,) if pool else ()
        ).fetchall()
        schedule = db.execute("SELECT * FROM schedule").fetchall()

    results = {}
    for c in coaches:
        results[c["id"]] = {
            "coach": dict(c), "W": 0, "L": 0, "T": 0,
            "diff": 0.0, "weeks": {}
        }

    for m in schedule:
        c1, c2 = m["coach1_id"], m["coach2_id"]
        if c1 not in results or c2 not in results:
            continue
        s1, s2 = m["score1"], m["score2"]
        wk = m["week"]
        if s1 is None or s2 is None:
            results[c1]["weeks"][wk] = ""
            results[c2]["weeks"][wk] = ""
            continue
        diff = s1 - s2
        if diff > 0:
            results[c1]["W"] += 1
            results[c1]["weeks"][wk] = "W"
            results[c2]["L"] += 1
            results[c2]["weeks"][wk] = "L"
        elif diff < 0:
            results[c1]["L"] += 1
            results[c1]["weeks"][wk] = "L"
            results[c2]["W"] += 1
            results[c2]["weeks"][wk] = "W"
        else:
            results[c1]["T"] += 1
            results[c1]["weeks"][wk] = "T"
            results[c2]["T"] += 1
            results[c2]["weeks"][wk] = "T"
        results[c1]["diff"] += diff
        results[c2]["diff"] -= diff

    rows = sorted(results.values(), key=lambda x: (-x["W"], -x["diff"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return rows


def get_mvp_data():
    with get_db() as db:
        stats = db.execute("""
            SELECT ms.pokemon_name, c.coach_name, c.team_name,
                   SUM(ms.kills) as total_kills, SUM(ms.deaths) as total_deaths,
                   COUNT(DISTINCT ms.schedule_id) as games
            FROM match_stats ms
            JOIN coaches c ON ms.coach_id = c.id
            GROUP BY ms.pokemon_name, ms.coach_id
            ORDER BY (SUM(ms.kills) - SUM(ms.deaths)) DESC, SUM(ms.kills) DESC
        """).fetchall()
    return [dict(s) for s in stats]


# ─── Auth Routes ─────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with get_db() as db:
            user = db.execute(
                "SELECT * FROM users WHERE username=? AND password_hash=?",
                (username, hash_pw(password))
            ).fetchone()
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(request.args.get("next") or url_for("index"))
        flash("Invalid username or password.", "warning")
    return render_template("login.html",
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


# ─── Public Routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    league_name = get_setting("league_name", "Pokemon Draft League")
    standings_a = get_standings("A")
    standings_b = get_standings("B")
    standings_all = get_standings(None)
    # Get max weeks played
    with get_db() as db:
        weeks = db.execute("SELECT DISTINCT week FROM schedule ORDER BY week").fetchall()
    all_weeks = [w["week"] for w in weeks]
    return render_template("index.html",
                           league_name=league_name,
                           standings_a=standings_a,
                           standings_b=standings_b,
                           standings_all=standings_all,
                           all_weeks=all_weeks)


@app.route("/teams")
def teams():
    with get_db() as db:
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
    standings_a = {s["coach"]["id"]: s for s in get_standings("A")}
    standings_b = {s["coach"]["id"]: s for s in get_standings("B")}
    standings = {**standings_a, **standings_b}
    return render_template("teams.html",
                           coaches=coaches,
                           standings=standings,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


def _pokemon_slug(name):
    """Convert display name to best-guess pokeapi slug for lookups."""
    return _name_to_slug(name)[0]


def _speed_tiers(base_spe):
    """Return (0ev, 252ev, 252+) speed stats at level 100, 31 IVs."""
    if not base_spe:
        return None, None, None
    s0   = 2 * base_spe + 36
    s252 = 2 * base_spe + 99
    s252p = int(s252 * 1.1)
    return s0, s252, s252p


@app.route("/team/<int:coach_id>")
def team_detail(coach_id):
    with get_db() as db:
        coach = db.execute("SELECT * FROM coaches WHERE id=?", (coach_id,)).fetchone()
        if not coach:
            return "Team not found", 404
        coach = dict(coach)

        roster_rows = db.execute(
            "SELECT * FROM pokemon_roster WHERE coach_id=? ORDER BY points DESC",
            (coach_id,)
        ).fetchall()

        # Fetch pokedex data for roster pokemon
        slugs = [_pokemon_slug(p["pokemon_name"]) for p in roster_rows]
        pokedex_map = {}
        if slugs:
            ph = ",".join("?" for _ in slugs)
            for row in db.execute(f"SELECT * FROM pokedex WHERE pokeapi_name IN ({ph})", slugs).fetchall():
                pokedex_map[row["pokeapi_name"]] = dict(row)

        # Match stats
        stats_map = {}
        for s in db.execute("""
            SELECT pokemon_name, SUM(kills) as k, SUM(deaths) as d,
                   COUNT(DISTINCT schedule_id) as gp
            FROM match_stats WHERE coach_id=? GROUP BY pokemon_name
        """, (coach_id,)).fetchall():
            stats_map[s["pokemon_name"]] = {
                "k": int(s["k"] or 0), "d": int(s["d"] or 0), "gp": int(s["gp"] or 0)
            }

        # Schedule
        schedule_rows = db.execute("""
            SELECT s.*,
                   c1.coach_name as c1_name, c1.team_name as c1_team, c1.color as c1_color, c1.logo_url as c1_logo,
                   c2.coach_name as c2_name, c2.team_name as c2_team, c2.color as c2_color, c2.logo_url as c2_logo
            FROM schedule s
            JOIN coaches c1 ON s.coach1_id = c1.id
            JOIN coaches c2 ON s.coach2_id = c2.id
            WHERE s.coach1_id=? OR s.coach2_id=?
            ORDER BY s.week
        """, (coach_id, coach_id)).fetchall()
        schedule = [dict(r) for r in schedule_rows]

        # Current week from settings
        cw_row = db.execute("SELECT value FROM league_settings WHERE key='current_week'").fetchone()
        current_week = int(cw_row["value"]) if cw_row else 1

        # Match history — completed matches with per-game stats + replays
        match_history = []
        for m in schedule:
            if m["score1"] is None or m["score2"] is None:
                continue
            is_c1h = (m["coach1_id"] == coach_id)
            opp_id_h = m["coach2_id"] if is_c1h else m["coach1_id"]
            my_score_h  = m["score1"] if is_c1h else m["score2"]
            opp_score_h = m["score2"] if is_c1h else m["score1"]

            # Fetch games with per-game stats
            games_rows = db.execute(
                "SELECT * FROM match_games WHERE schedule_id=? ORDER BY game_number",
                (m["id"],)
            ).fetchall()
            games_data = []
            for g in games_rows:
                my_pokes = db.execute(
                    "SELECT pokemon_name, kills, deaths FROM match_stats WHERE game_id=? AND coach_id=? ORDER BY kills DESC",
                    (g["id"], coach_id)
                ).fetchall()
                opp_pokes = db.execute(
                    "SELECT pokemon_name, kills, deaths FROM match_stats WHERE game_id=? AND coach_id=? ORDER BY kills DESC",
                    (g["id"], opp_id_h)
                ).fetchall()
                games_data.append({
                    "game_number": g["game_number"],
                    "replay_url":  g["replay_url"] or "",
                    "winner_coach_id": g["winner_coach_id"],
                    "my_won": g["winner_coach_id"] == coach_id if g["winner_coach_id"] else None,
                    "my_pokes":  [dict(p) for p in my_pokes],
                    "opp_pokes": [dict(p) for p in opp_pokes],
                })

            # Fallback: legacy stats not tied to a game
            legacy_my = db.execute(
                "SELECT pokemon_name, kills, deaths FROM match_stats WHERE schedule_id=? AND game_id IS NULL AND coach_id=? ORDER BY kills DESC",
                (m["id"], coach_id)
            ).fetchall()
            legacy_opp = db.execute(
                "SELECT pokemon_name, kills, deaths FROM match_stats WHERE schedule_id=? AND game_id IS NULL AND coach_id=? ORDER BY kills DESC",
                (m["id"], opp_id_h)
            ).fetchall()

            match_history.append({
                "week":       m["week"],
                "schedule_id": m["id"],
                "opp_id":    opp_id_h,
                "opp_team":  m["c2_team"]  if is_c1h else m["c1_team"],
                "opp_coach": m["c2_name"]  if is_c1h else m["c1_name"],
                "opp_color": m["c2_color"] if is_c1h else m["c1_color"],
                "opp_logo":  m["c2_logo"]  if is_c1h else m["c1_logo"],
                "my_score":  my_score_h,
                "opp_score": opp_score_h,
                "result": "W" if my_score_h > opp_score_h else ("L" if my_score_h < opp_score_h else "T"),
                "games":     games_data,
                "legacy_my":  [dict(p) for p in legacy_my],
                "legacy_opp": [dict(p) for p in legacy_opp],
            })

        # Current-week matchup
        matchup = None
        for m in schedule:
            if m["week"] == current_week:
                is_c1 = (m["coach1_id"] == coach_id)
                opp_id = m["coach2_id"] if is_c1 else m["coach1_id"]
                opp_roster_rows = db.execute(
                    "SELECT * FROM pokemon_roster WHERE coach_id=? ORDER BY points DESC",
                    (opp_id,)
                ).fetchall()
                opp_slugs = [_pokemon_slug(p["pokemon_name"]) for p in opp_roster_rows]
                opp_pd_map = {}
                if opp_slugs:
                    ph2 = ",".join("?" for _ in opp_slugs)
                    for row in db.execute(f"SELECT * FROM pokedex WHERE pokeapi_name IN ({ph2})", opp_slugs).fetchall():
                        opp_pd_map[row["pokeapi_name"]] = dict(row)
                matchup = {
                    "week": current_week,
                    "my_score":  m["score1"] if is_c1 else m["score2"],
                    "opp_score": m["score2"] if is_c1 else m["score1"],
                    "opp_id":    opp_id,
                    "opp_team":  m["c2_team"] if is_c1 else m["c1_team"],
                    "opp_coach": m["c2_name"] if is_c1 else m["c1_name"],
                    "opp_color": m["c2_color"] if is_c1 else m["c1_color"],
                    "opp_logo":  m["c2_logo"]  if is_c1 else m["c1_logo"],
                    "opp_roster": [dict(r) for r in opp_roster_rows],
                    "opp_pd_map": opp_pd_map,
                }
                break

    # Pool standings for record
    standing = None
    for s in get_standings(coach["pool"]):
        if s["coach"]["id"] == coach_id:
            standing = s
            break

    # Build enriched roster list
    roster = []
    for p in roster_rows:
        slug = _pokemon_slug(p["pokemon_name"])
        pd   = pokedex_map.get(slug, {})
        stat = stats_map.get(p["pokemon_name"], {"k": 0, "d": 0, "gp": 0})
        spe  = pd.get("spe") or 0
        s0, s252, s252p = _speed_tiers(spe) if spe else (None, None, None)
        roster.append({
            "name":           p["pokemon_name"],
            "points":         p["points"],
            "tier":           p["tier"] or "",
            "is_tera_captain":   bool(p["is_tera_captain"]),
            "is_zmove_captain":  bool(p["is_zmove_captain"]) if "is_zmove_captain" in p.keys() else False,
            "is_free_pick":      bool(p["is_free_pick"]) if "is_free_pick" in p.keys() else False,
            "type1": pd.get("type1", ""),
            "type2": pd.get("type2", ""),
            "hp":   pd.get("hp"),
            "atk":  pd.get("atk"),
            "def_": pd.get("def_stat"),
            "spa":  pd.get("spa"),
            "spd":  pd.get("spd"),
            "spe":  spe or None,
            "spe_0":    s0,
            "spe_252":  s252,
            "spe_252p": s252p,
            "gp": stat["gp"],
            "k":  stat["k"],
            "d":  stat["d"],
            "kd": stat["k"] - stat["d"],
        })

    with get_db() as db:
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
    youtube_id = _extract_youtube_id(coach.get("battle_music_url", ""))
    return render_template("team.html",
                           coach=coach,
                           roster=roster,
                           schedule=schedule,
                           matchup=matchup,
                           match_history=match_history,
                           standing=standing,
                           current_week=current_week,
                           settings=settings,
                           youtube_id=youtube_id,
                           league_name=settings.get("league_name", "Pokemon Draft League"))


@app.route("/schedule")
def schedule():
    with get_db() as db:
        matches = db.execute("""
            SELECT s.*,
                   c1.coach_name as c1_name, c1.team_name as c1_team, c1.color as c1_color, c1.logo_url as c1_logo,
                   c2.coach_name as c2_name, c2.team_name as c2_team, c2.color as c2_color, c2.logo_url as c2_logo
            FROM schedule s
            JOIN coaches c1 ON s.coach1_id = c1.id
            JOIN coaches c2 ON s.coach2_id = c2.id
            ORDER BY s.week, s.pool, s.id
        """).fetchall()
        weeks = db.execute("SELECT DISTINCT week FROM schedule ORDER BY week").fetchall()
        # Fetch pokemon used per match per coach
        used_rows = db.execute("""
            SELECT schedule_id, coach_id, pokemon_name
            FROM match_stats
            WHERE schedule_id IS NOT NULL AND playoff_match_id IS NULL
            GROUP BY schedule_id, coach_id, pokemon_name
            ORDER BY schedule_id, coach_id
        """).fetchall()
    # Build lookup: {schedule_id: {coach_id: [pokemon_name, ...]}}
    match_pokemon = {}
    for row in used_rows:
        sid = row["schedule_id"]
        cid = row["coach_id"]
        if sid not in match_pokemon:
            match_pokemon[sid] = {}
        if cid not in match_pokemon[sid]:
            match_pokemon[sid][cid] = []
        match_pokemon[sid][cid].append(row["pokemon_name"])
    by_week = {}
    for m in matches:
        w = m["week"]
        if w not in by_week:
            by_week[w] = []
        md = dict(m)
        sid = md["id"]
        md["c1_pokemon"] = match_pokemon.get(sid, {}).get(md["coach1_id"], [])
        md["c2_pokemon"] = match_pokemon.get(sid, {}).get(md["coach2_id"], [])
        by_week[w].append(md)
    return render_template("schedule.html",
                           by_week=by_week,
                           weeks=[w["week"] for w in weeks],
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/transactions")
def transactions():
    with get_db() as db:
        txns = db.execute("""
            SELECT t.*,
                   c1.coach_name as c1_name, c1.team_name as c1_team,
                   c2.coach_name as c2_name, c2.team_name as c2_team
            FROM transactions t
            JOIN coaches c1 ON t.coach1_id = c1.id
            LEFT JOIN coaches c2 ON t.coach2_id = c2.id
            ORDER BY t.week DESC, t.id DESC
        """).fetchall()
    return render_template("transactions.html",
                           transactions=txns,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/mvp")
def mvp():
    mvp_data = get_mvp_data()
    for i, p in enumerate(mvp_data):
        p["rank"] = i + 1
        p["diff"] = p["total_kills"] - p["total_deaths"]
    return render_template("mvp.html",
                           mvp_data=mvp_data,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/rules")
def rules():
    with get_db() as db:
        rule_sections = db.execute(
            "SELECT * FROM rules ORDER BY section_order"
        ).fetchall()
    return render_template("rules.html",
                           rule_sections=rule_sections,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


# ─── Admin: Quick points update (used from draftboard) ───────────────────────

@app.route("/admin/tiers/quick_pts", methods=["POST"])
@admin_required
def admin_tiers_quick_pts():
    tier_id = request.form.get("tier_id")
    try:
        pts = int(request.form.get("points", 0))
    except ValueError:
        return ("Invalid points", 400)
    with get_db() as db:
        db.execute("UPDATE draft_tiers SET points=? WHERE id=?", (pts, tier_id))
    return ("ok", 200)


# ─── Draft Board ─────────────────────────────────────────────────────────────

def _regular_tier_label(pts):
    """Map point value to Tier 1–5 label for regular (non-Mega) Pokemon."""
    if pts >= 16: return "Tier 1"
    if pts >= 12: return "Tier 2"
    if pts >= 8:  return "Tier 3"
    if pts >= 5:  return "Tier 4"
    if pts >= 1:  return "Tier 5"
    return ""


def _mega_tier_label(pts, settings):
    """Map point value to Bronze/Silver/Gold/Platinum for Mega Pokemon."""
    def _s(k): return int(settings.get(k, 0) or 0)
    plat   = _s("mega_platinum_pts")
    gold   = _s("mega_gold_pts")
    silver = _s("mega_silver_pts")
    bronze = _s("mega_bronze_pts")
    if plat   and pts >= plat:   return "Platinum"
    if gold   and pts >= gold:   return "Gold"
    if silver and pts >= silver: return "Silver"
    if bronze and pts >= bronze: return "Bronze"
    return ""


@app.route("/draftboard")
def draft_board():
    with get_db() as db:
        tiers = db.execute(
            "SELECT * FROM draft_tiers ORDER BY points DESC, name"
        ).fetchall()
        drafted_rows = db.execute("""
            SELECT pr.pokemon_name, c.id as coach_id, c.coach_name, c.team_name, c.color, c.logo_url,
                   pr.is_tera_captain, c.pool
            FROM pokemon_roster pr JOIN coaches c ON pr.coach_id = c.id
        """).fetchall()
        drafted = {r["pokemon_name"]: dict(r) for r in drafted_rows}
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}

    mechanic_mega = settings.get("mechanic_mega", "0") == "1"

    # Group all tiers by points into a single pool.
    # First pass: build a pts→uber_label map from non-mega pokemon so megas
    # at the same point value land in the uber column.
    uber_label_by_pts = {}
    for t in tiers:
        raw = (t["tier_label"] or "") if not isinstance(t, dict) else (t.get("tier_label") or "")
        if "uber" in raw.lower():
            uber_label_by_pts[t["points"] if isinstance(t, dict) else t["points"]] = raw

    tiers_by_pts = []
    seen_pts = {}

    for t in tiers:
        t = dict(t)
        pts = t["points"]
        raw_label = t.get("tier_label") or ""

        if "uber" in raw_label.lower():
            label = raw_label
        elif pts in uber_label_by_pts:
            # Mega (or any unlabeled) pokemon at an uber point value → same column
            label = uber_label_by_pts[pts]
        else:
            label = _regular_tier_label(pts) if pts > 0 else raw_label

        group_key = (pts, label)
        if group_key not in seen_pts:
            seen_pts[group_key] = len(tiers_by_pts)
            tiers_by_pts.append({"points": pts, "label": label, "pokemon": []})
        tiers_by_pts[seen_pts[group_key]]["pokemon"].append(t)

    # Collect all unique move categories for the filter dropdown
    all_moves = sorted({
        m for t in tiers
        for m in (t["moves"] or "").split("|") if m
    })

    return render_template("draftboard.html",
                           tiers=tiers,
                           tiers_by_pts=tiers_by_pts,
                           mechanic_mega=mechanic_mega,
                           drafted=drafted,
                           coaches=coaches,
                           settings=settings,
                           all_moves=all_moves,
                           league_name=settings.get("league_name", "Pokemon Draft League"))


# ─── Admin Routes ─────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_index():
    with get_db() as db:
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
    return render_template("admin/index.html",
                           settings=settings,
                           coaches=coaches,
                           league_name=settings.get("league_name", "Pokemon Draft League"))


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    with get_db() as db:
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
    if request.method == "POST":
        with get_db() as db:
            for key, value in request.form.items():
                if key == "uber_combination":
                    continue  # handled separately below
                db.execute(
                    "INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)",
                    (key, value)
                )
            # uber_combination is a multi-checkbox — collect all checked values
            uber_combos = request.form.getlist("uber_combination")
            db.execute(
                "INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)",
                ("uber_combination", ",".join(uber_combos) if uber_combos else "")
            )
            # Checkboxes not submitted when unchecked — force to '0' if missing
            for checkbox_key in ("mechanic_mega", "mechanic_tera", "mechanic_zmove", "mechanic_uber"):
                if checkbox_key not in request.form:
                    db.execute(
                        "INSERT OR REPLACE INTO league_settings (key, value) VALUES (?, ?)",
                        (checkbox_key, "0")
                    )
        flash("Settings saved!", "success")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html",
                           settings=settings,
                           league_name=settings.get("league_name", "Pokemon Draft League"))


LOGOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logos")
os.makedirs(LOGOS_DIR, exist_ok=True)
ALLOWED_LOGO_EXTS = {".jpg", ".jpeg", ".png"}


def _save_logo_file(file_storage):
    """Save an uploaded logo file; return the URL path or None."""
    if not file_storage or not file_storage.filename:
        return None
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_LOGO_EXTS:
        return None
    filename = uuid.uuid4().hex + ext
    file_storage.save(os.path.join(LOGOS_DIR, filename))
    return f"/static/logos/{filename}"


@app.route("/admin/teams", methods=["GET", "POST"])
@admin_required
def admin_teams():
    with get_db() as db:
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            uploaded = _save_logo_file(request.files.get("logo_file"))
            logo_url = uploaded or request.form.get("logo_url", "")
            with get_db() as db:
                db.execute(
                    "INSERT INTO coaches (coach_name, team_name, pool, color, logo_url, showdown_name, battle_music_url) VALUES (?,?,?,?,?,?,?)",
                    (request.form["coach_name"], request.form["team_name"],
                     request.form["pool"], request.form.get("color", "#3b82f6"),
                     logo_url,
                     request.form.get("showdown_name", ""),
                     request.form.get("battle_music_url", ""))
                )
            flash("Team added!", "success")
        elif action == "edit":
            cid = request.form["coach_id"]
            uploaded = _save_logo_file(request.files.get("logo_file"))
            logo_url = uploaded or request.form.get("logo_url", "")
            with get_db() as db:
                db.execute(
                    "UPDATE coaches SET coach_name=?, team_name=?, pool=?, color=?, logo_url=?, showdown_name=?, battle_music_url=? WHERE id=?",
                    (request.form["coach_name"], request.form["team_name"],
                     request.form["pool"], request.form.get("color", "#3b82f6"),
                     logo_url,
                     request.form.get("showdown_name", ""),
                     request.form.get("battle_music_url", ""), cid)
                )
            flash("Team updated!", "success")
        elif action == "delete":
            cid = request.form["coach_id"]
            with get_db() as db:
                db.execute("DELETE FROM coaches WHERE id=?", (cid,))
                db.execute("DELETE FROM pokemon_roster WHERE coach_id=?", (cid,))
            flash("Team deleted.", "warning")
        return redirect(url_for("admin_teams"))
    return render_template("admin/teams.html",
                           coaches=coaches,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/admin/roster/<int:coach_id>", methods=["GET", "POST"])
@admin_required
def admin_roster(coach_id):
    with get_db() as db:
        coach = db.execute("SELECT * FROM coaches WHERE id=?", (coach_id,)).fetchone()
        roster = db.execute(
            "SELECT * FROM pokemon_roster WHERE coach_id=? ORDER BY points DESC",
            (coach_id,)
        ).fetchall()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            with get_db() as db:
                db.execute(
                    "INSERT INTO pokemon_roster (coach_id, pokemon_name, points, tier, is_tera_captain, is_zmove_captain, is_free_pick) VALUES (?,?,?,?,?,?,?)",
                    (coach_id, request.form["pokemon_name"],
                     int(request.form.get("points", 0)),
                     request.form.get("tier", ""),
                     1 if request.form.get("is_tera_captain") else 0,
                     1 if request.form.get("is_zmove_captain") else 0,
                     1 if request.form.get("is_free_pick") else 0)
                )
            flash("Pokemon added!", "success")
        elif action == "delete":
            pid = request.form["pokemon_id"]
            with get_db() as db:
                db.execute("DELETE FROM pokemon_roster WHERE id=?", (pid,))
            flash("Pokemon removed.", "warning")
        elif action == "edit":
            pid = request.form["pokemon_id"]
            with get_db() as db:
                db.execute(
                    "UPDATE pokemon_roster SET pokemon_name=?, points=?, tier=?, is_tera_captain=?, is_zmove_captain=?, is_free_pick=? WHERE id=?",
                    (request.form["pokemon_name"],
                     int(request.form.get("points", 0)),
                     request.form.get("tier", ""),
                     1 if request.form.get("is_tera_captain") else 0,
                     1 if request.form.get("is_zmove_captain") else 0,
                     1 if request.form.get("is_free_pick") else 0,
                     pid)
                )
            flash("Pokemon updated!", "success")
        return redirect(url_for("admin_roster", coach_id=coach_id))
    with get_db() as db:
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
    return render_template("admin/roster.html",
                           coach=coach,
                           roster=roster,
                           settings=settings,
                           league_name=settings.get("league_name", "Pokemon Draft League"))


@app.route("/admin/schedule", methods=["GET", "POST"])
@admin_required
def admin_schedule():
    with get_db() as db:
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
        matches = db.execute("""
            SELECT s.*, c1.coach_name as c1_name, c2.coach_name as c2_name
            FROM schedule s
            JOIN coaches c1 ON s.coach1_id = c1.id
            JOIN coaches c2 ON s.coach2_id = c2.id
            ORDER BY s.week, s.id
        """).fetchall()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_match":
            with get_db() as db:
                db.execute(
                    "INSERT INTO schedule (week, pool, coach1_id, coach2_id, score1, score2) VALUES (?,?,?,?,?,?)",
                    (request.form["week"], request.form["pool"],
                     request.form["coach1_id"], request.form["coach2_id"],
                     None, None)
                )
            flash("Match added!", "success")
        elif action == "update_result":
            mid = request.form["match_id"]
            s1 = request.form.get("score1") or None
            s2 = request.form.get("score2") or None
            if s1 is not None:
                s1 = float(s1)
            if s2 is not None:
                s2 = float(s2)
            with get_db() as db:
                db.execute(
                    "UPDATE schedule SET score1=?, score2=? WHERE id=?",
                    (s1, s2, mid)
                )
            flash("Result updated!", "success")
        elif action == "delete_match":
            mid = request.form["match_id"]
            with get_db() as db:
                db.execute("DELETE FROM schedule WHERE id=?", (mid,))
            flash("Match deleted.", "warning")
        return redirect(url_for("admin_schedule"))
    return render_template("admin/schedule.html",
                           coaches=coaches,
                           matches=matches,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


def _recalc_match_score(db, match_id, c1_id, c2_id):
    """For BO3: set score1/score2 from game wins. For BO1 with one game, set 1-0 or 0-1."""
    games = db.execute(
        "SELECT winner_coach_id FROM match_games WHERE schedule_id=? AND winner_coach_id IS NOT NULL",
        (match_id,)
    ).fetchall()
    if not games:
        return
    s1 = sum(1 for g in games if g["winner_coach_id"] == c1_id)
    s2 = sum(1 for g in games if g["winner_coach_id"] == c2_id)
    db.execute("UPDATE schedule SET score1=?, score2=? WHERE id=?", (s1, s2, match_id))


@app.route("/admin/match_stats/<int:match_id>", methods=["GET", "POST"])
@coach_or_admin_required
def admin_match_stats(match_id):
    match_format = get_setting("match_format", "BO1")
    max_games = 3 if match_format == "BO3" else 1

    with get_db() as db:
        match = db.execute("""
            SELECT s.*, c1.coach_name as c1_name, c1.id as c1_id, c1.team_name as c1_team,
                   c2.coach_name as c2_name, c2.id as c2_id, c2.team_name as c2_team
            FROM schedule s
            JOIN coaches c1 ON s.coach1_id = c1.id
            JOIN coaches c2 ON s.coach2_id = c2.id
            WHERE s.id=?
        """, (match_id,)).fetchone()
        if not match:
            return "Match not found", 404
        match = dict(match)

        games = db.execute(
            "SELECT * FROM match_games WHERE schedule_id=? ORDER BY game_number",
            (match_id,)
        ).fetchall()
        games = [dict(g) for g in games]

        # Per-game stats keyed by game_id, plus legacy (game_id NULL) under key None
        all_stats = db.execute(
            "SELECT * FROM match_stats WHERE schedule_id=? ORDER BY coach_id, kills DESC",
            (match_id,)
        ).fetchall()
        stats_by_game = {}
        for s in all_stats:
            gid = s["game_id"]
            stats_by_game.setdefault(gid, []).append(dict(s))

        roster1 = db.execute(
            "SELECT pokemon_name FROM pokemon_roster WHERE coach_id=? ORDER BY points DESC",
            (match["c1_id"],)
        ).fetchall()
        roster2 = db.execute(
            "SELECT pokemon_name FROM pokemon_roster WHERE coach_id=? ORDER BY points DESC",
            (match["c2_id"],)
        ).fetchall()

        # Load lineups per game
        game_ids = [g["id"] for g in games]
        lineups_by_game = {}
        if game_ids:
            placeholders = ",".join("?" * len(game_ids))
            all_lineups = db.execute(
                f"SELECT * FROM match_lineups WHERE game_id IN ({placeholders})", game_ids
            ).fetchall()
            for ln in all_lineups:
                gid = ln["game_id"]
                lineups_by_game.setdefault(gid, {c["id"]: [] for c in [
                    {"id": match["c1_id"]}, {"id": match["c2_id"]}]
                })
                lineups_by_game[gid].setdefault(ln["coach_id"], []).append(dict(ln))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_game":
            gnum = int(request.form.get("game_number", 1))
            replay = request.form.get("replay_url", "").strip()
            with get_db() as db:
                db.execute(
                    "INSERT INTO match_games (schedule_id, game_number, replay_url) VALUES (?,?,?)",
                    (match_id, gnum, replay)
                )
            flash(f"Game {gnum} added!", "success")

        elif action == "update_game":
            gid = request.form["game_id"]
            replay = request.form.get("replay_url", "").strip()
            winner = request.form.get("winner_coach_id") or None
            with get_db() as db:
                db.execute(
                    "UPDATE match_games SET replay_url=?, winner_coach_id=? WHERE id=?",
                    (replay, winner, gid)
                )
                _recalc_match_score(db, match_id, match["c1_id"], match["c2_id"])
            flash("Game updated!", "success")

        elif action == "delete_game":
            gid = request.form["game_id"]
            with get_db() as db:
                db.execute("DELETE FROM match_stats WHERE game_id=?", (gid,))
                db.execute("DELETE FROM match_lineups WHERE game_id=?", (gid,))
                db.execute("DELETE FROM match_games WHERE id=?", (gid,))
                _recalc_match_score(db, match_id, match["c1_id"], match["c2_id"])
            flash("Game deleted.", "warning")

        elif action == "add_lineup":
            game_id = request.form["game_id"]
            coach_id = request.form["coach_id"]
            pokemon_name = request.form.get("pokemon_name", "").strip()
            if pokemon_name:
                with get_db() as db:
                    db.execute(
                        "INSERT OR IGNORE INTO match_lineups (game_id, coach_id, pokemon_name) VALUES (?,?,?)",
                        (game_id, coach_id, pokemon_name)
                    )
                flash("Added to lineup.", "success")

        elif action == "remove_lineup":
            lineup_id = request.form["lineup_id"]
            with get_db() as db:
                db.execute("DELETE FROM match_lineups WHERE id=?", (lineup_id,))
            flash("Removed from lineup.", "warning")

        elif action == "log_ko":
            game_id = request.form.get("game_id") or None
            attacker_coach = int(request.form["attacker_coach_id"])
            attacker_pokemon = request.form["attacker_pokemon"].strip()
            defender_coach = int(request.form["defender_coach_id"])
            defender_pokemon = request.form["defender_pokemon"].strip()
            if attacker_pokemon and defender_pokemon:
                with get_db() as db:
                    for cid, pname, kills_delta, deaths_delta in [
                        (attacker_coach, attacker_pokemon, 1, 0),
                        (defender_coach, defender_pokemon, 0, 1),
                    ]:
                        existing = db.execute(
                            "SELECT id FROM match_stats WHERE schedule_id=? AND game_id IS ? AND coach_id=? AND pokemon_name=?",
                            (match_id, game_id, cid, pname)
                        ).fetchone()
                        if existing:
                            db.execute(
                                "UPDATE match_stats SET kills=kills+?, deaths=deaths+? WHERE id=?",
                                (kills_delta, deaths_delta, existing["id"])
                            )
                        else:
                            db.execute(
                                "INSERT INTO match_stats (schedule_id, game_id, coach_id, pokemon_name, kills, deaths) VALUES (?,?,?,?,?,?)",
                                (match_id, game_id, cid, pname, kills_delta, deaths_delta)
                            )
                flash(f"{attacker_pokemon} KO'd {defender_pokemon}.", "success")

        elif action == "add_stat":
            game_id = request.form.get("game_id") or None
            with get_db() as db:
                db.execute(
                    "INSERT INTO match_stats (schedule_id, game_id, coach_id, pokemon_name, kills, deaths) VALUES (?,?,?,?,?,?)",
                    (match_id, game_id, request.form["coach_id"], request.form["pokemon_name"],
                     float(request.form.get("kills", 0)),
                     float(request.form.get("deaths", 0)))
                )
            flash("Stat added!", "success")

        elif action == "delete_stat":
            with get_db() as db:
                db.execute("DELETE FROM match_stats WHERE id=?", (request.form["stat_id"],))
            flash("Stat deleted.", "warning")

        return redirect(url_for("admin_match_stats", match_id=match_id))

    return render_template("admin/match_stats.html",
                           match=match,
                           games=games,
                           stats_by_game=stats_by_game,
                           lineups_by_game=lineups_by_game,
                           roster1=roster1,
                           roster2=roster2,
                           max_games=max_games,
                           match_format=match_format,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/admin/transactions", methods=["GET", "POST"])
@admin_required
def admin_transactions():
    with get_db() as db:
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
        txns = db.execute("""
            SELECT t.*, c1.coach_name as c1_name, c2.coach_name as c2_name
            FROM transactions t
            JOIN coaches c1 ON t.coach1_id = c1.id
            LEFT JOIN coaches c2 ON t.coach2_id = c2.id
            ORDER BY t.week DESC, t.id DESC
        """).fetchall()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            c2_id = request.form.get("coach2_id") or None
            with get_db() as db:
                db.execute(
                    "INSERT INTO transactions (week, event_type, coach1_id, pokemon_out, pokemon_in, coach2_id, notes) VALUES (?,?,?,?,?,?,?)",
                    (request.form["week"], request.form["event_type"],
                     request.form["coach1_id"],
                     request.form.get("pokemon_out", ""),
                     request.form.get("pokemon_in", ""),
                     c2_id,
                     request.form.get("notes", ""))
                )
                # Update roster if FA drop
                if request.form.get("update_roster"):
                    coach1_id = int(request.form["coach1_id"])
                    pokemon_out = request.form.get("pokemon_out", "")
                    pokemon_in = request.form.get("pokemon_in", "")
                    if pokemon_out:
                        db.execute(
                            "DELETE FROM pokemon_roster WHERE coach_id=? AND pokemon_name=?",
                            (coach1_id, pokemon_out)
                        )
                    if pokemon_in:
                        db.execute(
                            "INSERT INTO pokemon_roster (coach_id, pokemon_name, points, tier) VALUES (?,?,0,'FA')",
                            (coach1_id, pokemon_in)
                        )
            flash("Transaction added!", "success")
        elif action == "delete":
            tid = request.form["transaction_id"]
            with get_db() as db:
                db.execute("DELETE FROM transactions WHERE id=?", (tid,))
            flash("Transaction deleted.", "warning")
        return redirect(url_for("admin_transactions"))
    return render_template("admin/transactions.html",
                           coaches=coaches,
                           transactions=txns,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/admin/rules", methods=["GET", "POST"])
@admin_required
def admin_rules():
    with get_db() as db:
        rule_sections = db.execute("SELECT * FROM rules ORDER BY section_order").fetchall()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            with get_db() as db:
                max_order = db.execute("SELECT MAX(section_order) as m FROM rules").fetchone()["m"] or 0
                db.execute(
                    "INSERT INTO rules (section_order, title, content) VALUES (?,?,?)",
                    (max_order + 1, request.form["title"], request.form["content"])
                )
            flash("Rule section added!", "success")
        elif action == "edit":
            rid = request.form["rule_id"]
            with get_db() as db:
                db.execute(
                    "UPDATE rules SET title=?, content=? WHERE id=?",
                    (request.form["title"], request.form["content"], rid)
                )
            flash("Rule updated!", "success")
        elif action == "delete":
            rid = request.form["rule_id"]
            with get_db() as db:
                db.execute("DELETE FROM rules WHERE id=?", (rid,))
            flash("Rule deleted.", "warning")
        return redirect(url_for("admin_rules"))
    return render_template("admin/rules.html",
                           rule_sections=rule_sections,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


# ─── Admin: Users ─────────────────────────────────────────────────────────────

@app.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    import hashlib
    with get_db() as db:
        users = db.execute(
            "SELECT u.*, c.coach_name FROM users u LEFT JOIN coaches c ON u.coach_id = c.id ORDER BY u.role, u.username"
        ).fetchall()
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            pw = request.form.get("password", "")
            pw_hash = hashlib.sha256(pw.encode()).hexdigest()
            coach_id = request.form.get("coach_id") or None
            with get_db() as db:
                try:
                    db.execute(
                        "INSERT INTO users (username, password_hash, role, coach_id) VALUES (?,?,?,?)",
                        (request.form["username"], pw_hash, request.form.get("role", "coach"), coach_id)
                    )
                    flash(f"User '{request.form['username']}' created!", "success")
                except Exception as e:
                    flash(f"Error: {e}", "warning")
        elif action == "change_password":
            uid = request.form["user_id"]
            pw = request.form.get("password", "")
            pw_hash = hashlib.sha256(pw.encode()).hexdigest()
            with get_db() as db:
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, uid))
            flash("Password updated!", "success")
        elif action == "delete":
            uid = request.form["user_id"]
            if str(uid) != str(session.get("user_id")):
                with get_db() as db:
                    db.execute("DELETE FROM users WHERE id=?", (uid,))
                flash("User deleted.", "warning")
        return redirect(url_for("admin_users"))
    return render_template("admin/users.html",
                           users=users,
                           coaches=coaches,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


# ─── Admin: Draft Tiers ────────────────────────────────────────────────────────

@app.route("/admin/tiers", methods=["GET", "POST"])
@admin_required
def admin_tiers():
    with get_db() as db:
        tiers = db.execute("SELECT * FROM draft_tiers ORDER BY points DESC, name").fetchall()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            with get_db() as db:
                try:
                    name = request.form["name"]
                    db.execute(
                        "INSERT INTO draft_tiers (name, points, tier_label, is_banned, is_tera_banned, is_mega) VALUES (?,?,?,?,?,?)",
                        (name, int(request.form.get("points", 0)),
                         request.form.get("tier_label", ""),
                         1 if request.form.get("is_banned") else 0,
                         1 if request.form.get("is_tera_banned") else 0,
                         1 if (request.form.get("is_mega") or name.startswith("Mega ")) else 0)
                    )
                    flash("Pokemon added to tier list!", "success")
                except Exception as e:
                    flash(f"Error: {e}", "warning")
        elif action == "edit":
            tid = request.form["tier_id"]
            with get_db() as db:
                db.execute(
                    "UPDATE draft_tiers SET name=?, points=?, tier_label=?, is_banned=?, is_tera_banned=?, is_mega=? WHERE id=?",
                    (request.form["name"], int(request.form.get("points", 0)),
                     request.form.get("tier_label", ""),
                     1 if request.form.get("is_banned") else 0,
                     1 if request.form.get("is_tera_banned") else 0,
                     1 if request.form.get("is_mega") else 0,
                     tid)
                )
            flash("Pokemon updated!", "success")
        elif action == "delete":
            tid = request.form["tier_id"]
            with get_db() as db:
                db.execute("DELETE FROM draft_tiers WHERE id=?", (tid,))
            flash("Pokemon removed from tier list.", "warning")
        elif action == "bulk_import":
            # Bulk import: name,points per line
            text = request.form.get("bulk_text", "")
            count = 0
            with get_db() as db:
                for line in text.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.rsplit(",", 1)
                    if len(parts) == 2:
                        name = parts[0].strip()
                        try:
                            pts = int(parts[1].strip())
                        except ValueError:
                            continue
                        try:
                            db.execute(
                                "INSERT OR REPLACE INTO draft_tiers (name, points) VALUES (?,?)",
                                (name, pts)
                            )
                            count += 1
                        except Exception:
                            pass
            flash(f"Bulk imported {count} Pokemon!", "success")
        return redirect(url_for("admin_tiers"))
    return render_template("admin/tiers.html",
                           tiers=tiers,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


# ─── Admin: Seasons ───────────────────────────────────────────────────────────

def ensure_seasons_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS seasons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        archived_at TEXT NOT NULL,
        data_json TEXT NOT NULL
    )""")


@app.route("/admin/seasons", methods=["GET", "POST"])
@admin_required
def admin_seasons():
    with get_db() as db:
        ensure_seasons_table(db)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "archive":
            season_name = request.form.get("season_name", "").strip() or get_setting("league_name")
            with get_db() as db:
                data = {
                    "settings": {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()},
                    "coaches": [dict(r) for r in db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()],
                    "schedule": [dict(r) for r in db.execute("SELECT * FROM schedule ORDER BY week, id").fetchall()],
                    "match_stats": [dict(r) for r in db.execute("SELECT * FROM match_stats").fetchall()],
                    "transactions": [dict(r) for r in db.execute("SELECT * FROM transactions ORDER BY week, id").fetchall()],
                    "pokemon_roster": [dict(r) for r in db.execute("SELECT * FROM pokemon_roster").fetchall()],
                    "draft_tiers": [dict(r) for r in db.execute("SELECT * FROM draft_tiers ORDER BY points DESC, name").fetchall()],
                    "rules": [dict(r) for r in db.execute("SELECT * FROM rules ORDER BY section_order").fetchall()],
                }
                db.execute(
                    "INSERT INTO seasons (name, archived_at, data_json) VALUES (?, ?, ?)",
                    (season_name, datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), json.dumps(data))
                )
            flash(f"Season '{season_name}' archived successfully!", "success")

        elif action == "new_season":
            new_name = request.form.get("new_name", "").strip() or "New Season"
            keep_teams = request.form.get("keep_teams") == "1"
            keep_tiers = request.form.get("keep_tiers") == "1"
            keep_rules = request.form.get("keep_rules") == "1"
            uber_enabled = request.form.get("mechanic_uber") == "1"
            uber_combination = (",".join(request.form.getlist("uber_combination")) or "2_bronze") if uber_enabled else ""
            with get_db() as db:
                db.execute("DELETE FROM schedule")
                db.execute("DELETE FROM match_stats")
                db.execute("DELETE FROM transactions")
                db.execute("DELETE FROM pokemon_roster")
                if not keep_teams:
                    db.execute("DELETE FROM coaches")
                if not keep_tiers:
                    db.execute("DELETE FROM draft_tiers")
                if not keep_rules:
                    db.execute("DELETE FROM rules")
                db.execute(
                    "INSERT OR REPLACE INTO league_settings (key, value) VALUES ('league_name', ?)",
                    (new_name,)
                )
                db.execute(
                    "INSERT OR REPLACE INTO league_settings (key, value) VALUES ('mechanic_uber', ?)",
                    ("1" if uber_enabled else "0",)
                )
                db.execute(
                    "INSERT OR REPLACE INTO league_settings (key, value) VALUES ('uber_combination', ?)",
                    (uber_combination,)
                )
                # Playoff settings
                for key in ("playoff_format", "playoff_players", "playoff_byes", "playoff_match_format"):
                    val = request.form.get(key, "")
                    if val:
                        db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES (?,?)", (key, val))
                # Clear any existing bracket
                db.execute("CREATE TABLE IF NOT EXISTS playoff_matches (id INTEGER PRIMARY KEY AUTOINCREMENT, round INTEGER, position INTEGER, bracket TEXT DEFAULT 'W', coach1_id INTEGER, coach2_id INTEGER, seed1 INTEGER, seed2 INTEGER, score1 INTEGER, score2 INTEGER, winner_id INTEGER, next_match_id INTEGER, next_match_slot INTEGER, is_bye INTEGER DEFAULT 0)")
                db.execute("DELETE FROM playoff_matches")
            flash(f"New season '{new_name}' started! Schedule, stats, transactions, and rosters have been cleared.", "success")

        elif action == "delete_archive":
            sid = request.form.get("season_id")
            with get_db() as db:
                db.execute("DELETE FROM seasons WHERE id=?", (sid,))
            flash("Archive deleted.", "warning")

        return redirect(url_for("admin_seasons"))

    with get_db() as db:
        seasons = db.execute("SELECT id, name, archived_at FROM seasons ORDER BY id DESC").fetchall()
    return render_template("admin/seasons.html",
                           seasons=seasons,
                           current_name=get_setting("league_name"),
                           league_name=get_setting("league_name"))


# ─── Playoffs ─────────────────────────────────────────────────────────────────

def ensure_playoffs_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS playoff_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        round INTEGER NOT NULL,
        position INTEGER NOT NULL,
        bracket TEXT NOT NULL DEFAULT 'W',
        coach1_id INTEGER,
        coach2_id INTEGER,
        seed1 INTEGER,
        seed2 INTEGER,
        score1 INTEGER,
        score2 INTEGER,
        winner_id INTEGER,
        next_match_id INTEGER,
        next_match_slot INTEGER,
        is_bye INTEGER DEFAULT 0
    )""")
    # Migrate match_games to support playoff matches
    cols_games = [r[1] for r in db.execute("PRAGMA table_info(match_games)").fetchall()]
    if "playoff_match_id" not in cols_games:
        db.execute("ALTER TABLE match_games ADD COLUMN playoff_match_id INTEGER DEFAULT NULL")
    # Migrate match_stats to support playoff matches
    cols_stats = [r[1] for r in db.execute("PRAGMA table_info(match_stats)").fetchall()]
    if "playoff_match_id" not in cols_stats:
        db.execute("ALTER TABLE match_stats ADD COLUMN playoff_match_id INTEGER DEFAULT NULL")


def _bracket_seeding(size):
    """Standard single-elimination seeding order for a power-of-2 bracket."""
    if size == 2:
        return [1, 2]
    prev = _bracket_seeding(size // 2)
    result = []
    for s in prev:
        result.append(s)
        result.append(size + 1 - s)
    return result


def _next_power_of_2(n):
    p = 1
    while p < n:
        p *= 2
    return p


def _gen_single_elim(seeded_coaches, num_byes):
    """
    Generate single-elimination bracket matches.
    seeded_coaches: list of coach dicts (with 'id') in seed order (index 0 = seed 1).
    num_byes: informational only; top seeds auto-bye via empty bracket slots.
    Returns list of match dicts.
    """
    n = len(seeded_coaches)
    bracket_size = _next_power_of_2(n)
    seeding = _bracket_seeding(bracket_size)
    total_rounds = int(math.log2(bracket_size))

    match_id = 1
    round_matches = {}
    all_matches = []

    for rnd in range(1, total_rounds + 1):
        num_in_round = bracket_size // (2 ** rnd)
        for pos in range(1, num_in_round + 1):
            m = {
                'id': match_id, 'round': rnd, 'position': pos, 'bracket': 'W',
                'coach1_id': None, 'coach2_id': None,
                'seed1': None, 'seed2': None,
                'score1': None, 'score2': None,
                'winner_id': None, 'next_match_id': None, 'next_match_slot': None,
                'is_bye': 0,
            }
            round_matches[(rnd, pos)] = m
            all_matches.append(m)
            match_id += 1

    # Wire up next_match links
    for rnd in range(1, total_rounds):
        num_in_round = bracket_size // (2 ** rnd)
        for pos in range(1, num_in_round + 1):
            m = round_matches[(rnd, pos)]
            next_pos = (pos + 1) // 2
            next_m = round_matches[(rnd + 1, next_pos)]
            m['next_match_id'] = next_m['id']
            m['next_match_slot'] = 1 if pos % 2 == 1 else 2

    # Assign round-1 participants and auto-complete bye slots
    r1_count = bracket_size // 2
    for i in range(r1_count):
        seed_1 = seeding[i * 2]
        seed_2 = seeding[i * 2 + 1]
        m = round_matches[(1, i + 1)]

        coach1 = seeded_coaches[seed_1 - 1] if seed_1 <= n else None
        coach2 = seeded_coaches[seed_2 - 1] if seed_2 <= n else None

        m['seed1'] = seed_1 if coach1 else None
        m['seed2'] = seed_2 if coach2 else None
        m['coach1_id'] = coach1['id'] if coach1 else None
        m['coach2_id'] = coach2['id'] if coach2 else None

        if not coach1 and coach2:
            m['winner_id'] = coach2['id']
            m['is_bye'] = 1
            _playoff_propagate(round_matches, 1, i + 1, coach2['id'], seed_2)
        elif coach1 and not coach2:
            m['winner_id'] = coach1['id']
            m['is_bye'] = 1
            _playoff_propagate(round_matches, 1, i + 1, coach1['id'], seed_1)

    return all_matches


def _playoff_propagate(round_matches, rnd, pos, win_id, win_seed):
    """Push a match winner into the appropriate slot of the next round."""
    m = round_matches.get((rnd, pos))
    if not m or not m.get('next_match_id'):
        return
    next_pos = (pos + 1) // 2
    next_m = round_matches.get((rnd + 1, next_pos))
    if not next_m:
        return
    if m['next_match_slot'] == 1:
        next_m['coach1_id'] = win_id
        next_m['seed1'] = win_seed
    else:
        next_m['coach2_id'] = win_id
        next_m['seed2'] = win_seed


def _round_label(rnd, total_rounds):
    diff = total_rounds - rnd
    if diff == 0:
        return "Finals"
    elif diff == 1:
        return "Semifinals"
    elif diff == 2:
        return "Quarterfinals"
    else:
        return f"Round {rnd}"


def _build_playoff_rounds(matches_raw, coaches_map):
    rounds_w, rounds_l, gf = {}, {}, []
    for m in matches_raw:
        md = dict(m)
        md['coach1'] = coaches_map.get(md['coach1_id'])
        md['coach2'] = coaches_map.get(md['coach2_id'])
        md['winner'] = coaches_map.get(md['winner_id'])
        if md['bracket'] == 'GF':
            gf.append(md)
        elif md['bracket'] == 'L':
            rounds_l.setdefault(md['round'], []).append(md)
        else:
            rounds_w.setdefault(md['round'], []).append(md)
    wb = [{'round': r, 'matches': rounds_w[r]} for r in sorted(rounds_w)]
    lb = [{'round': r, 'matches': rounds_l[r]} for r in sorted(rounds_l)]
    total = len(wb)
    for rd in wb:
        rd['label'] = _round_label(rd['round'], total)
    return wb, lb, gf


@app.route("/playoffs")
def playoffs():
    with get_db() as db:
        ensure_playoffs_table(db)
        matches_raw = db.execute(
            "SELECT * FROM playoff_matches ORDER BY bracket, round, position"
        ).fetchall()
        coaches_all = db.execute("SELECT * FROM coaches").fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}

    coaches_map = {c["id"]: dict(c) for c in coaches_all}
    wb_rounds, lb_rounds, gf_matches = _build_playoff_rounds(matches_raw, coaches_map)

    return render_template(
        "playoffs.html",
        wb_rounds=wb_rounds,
        lb_rounds=lb_rounds,
        gf_matches=gf_matches,
        has_bracket=bool(matches_raw),
        playoff_format=settings.get("playoff_format", "single"),
        settings=settings,
        league_name=settings.get("league_name", "Pokemon Draft League"),
    )


@app.route("/admin/playoffs", methods=["GET", "POST"])
@admin_required
def admin_playoffs():
    with get_db() as db:
        ensure_playoffs_table(db)
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}

    if request.method == "POST":
        action = request.form.get("action")

        if action == "generate":
            num_players = int(request.form.get("num_players", settings.get("playoff_players", 12)))
            num_byes    = int(request.form.get("num_byes",    settings.get("playoff_byes",    4)))
            fmt         = request.form.get("fmt",             settings.get("playoff_format",   "single"))
            mfmt        = request.form.get("match_format",    settings.get("playoff_match_format", "BO1"))

            all_standings = get_standings(None)
            top_n = all_standings[:num_players]

            if len(top_n) < num_players:
                flash(f"Only {len(top_n)} teams in standings (need {num_players}).", "warning")
                return redirect(url_for("admin_playoffs"))

            seeded = [row["coach"] for row in top_n]
            matches = _gen_single_elim(seeded, num_byes)

            with get_db() as db:
                ensure_playoffs_table(db)
                db.execute("DELETE FROM playoff_matches")
                for m in matches:
                    db.execute(
                        """INSERT INTO playoff_matches
                           (id, round, position, bracket, coach1_id, coach2_id, seed1, seed2,
                            score1, score2, winner_id, next_match_id, next_match_slot, is_bye)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (m['id'], m['round'], m['position'], m['bracket'],
                         m['coach1_id'], m['coach2_id'], m['seed1'], m['seed2'],
                         m['score1'], m['score2'], m['winner_id'],
                         m['next_match_id'], m['next_match_slot'], m['is_bye'])
                    )
                for key, val in [("playoff_format", fmt), ("playoff_players", str(num_players)),
                                  ("playoff_byes", str(num_byes)), ("playoff_match_format", mfmt)]:
                    db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES (?,?)", (key, val))
            flash(f"Bracket generated — {len([m for m in matches if not m['is_bye']])} real matches!", "success")

        elif action == "result":
            match_id = request.form.get("match_id", type=int)
            score1   = request.form.get("score1",   type=int)
            score2   = request.form.get("score2",   type=int)

            with get_db() as db:
                ensure_playoffs_table(db)
                m = db.execute("SELECT * FROM playoff_matches WHERE id=?", (match_id,)).fetchone()

            if not m:
                flash("Match not found.", "error")
                return redirect(url_for("admin_playoffs"))
            if score1 is None or score2 is None or score1 == score2:
                flash("Enter two different scores.", "error")
                return redirect(url_for("admin_playoffs"))

            winner_id   = m["coach1_id"] if score1 > score2 else m["coach2_id"]
            winner_seed = m["seed1"]     if score1 > score2 else m["seed2"]

            with get_db() as db:
                db.execute(
                    "UPDATE playoff_matches SET score1=?, score2=?, winner_id=? WHERE id=?",
                    (score1, score2, winner_id, match_id)
                )
                if m["next_match_id"]:
                    col = "coach1_id, seed1" if m["next_match_slot"] == 1 else "coach2_id, seed2"
                    if m["next_match_slot"] == 1:
                        db.execute(
                            "UPDATE playoff_matches SET coach1_id=?, seed1=? WHERE id=?",
                            (winner_id, winner_seed, m["next_match_id"])
                        )
                    else:
                        db.execute(
                            "UPDATE playoff_matches SET coach2_id=?, seed2=? WHERE id=?",
                            (winner_id, winner_seed, m["next_match_id"])
                        )
            flash("Result saved!", "success")

        elif action == "clear_result":
            match_id = request.form.get("match_id", type=int)
            with get_db() as db:
                m = db.execute("SELECT * FROM playoff_matches WHERE id=?", (match_id,)).fetchone()
                if m and m["next_match_id"]:
                    # Clear the propagated winner from next match
                    if m["next_match_slot"] == 1:
                        db.execute("UPDATE playoff_matches SET coach1_id=NULL, seed1=NULL WHERE id=?", (m["next_match_id"],))
                    else:
                        db.execute("UPDATE playoff_matches SET coach2_id=NULL, seed2=NULL WHERE id=?", (m["next_match_id"],))
                db.execute(
                    "UPDATE playoff_matches SET score1=NULL, score2=NULL, winner_id=NULL WHERE id=?",
                    (match_id,)
                )
            flash("Result cleared.", "warning")

        elif action == "reset":
            with get_db() as db:
                ensure_playoffs_table(db)
                db.execute("DELETE FROM playoff_matches")
            flash("Bracket reset.", "warning")

        elif action == "save_settings":
            with get_db() as db:
                for key in ("playoff_format", "playoff_players", "playoff_byes", "playoff_match_format"):
                    val = request.form.get(key, "")
                    db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES (?,?)", (key, val))
            flash("Playoff settings saved!", "success")

        return redirect(url_for("admin_playoffs"))

    # GET
    with get_db() as db:
        ensure_playoffs_table(db)
        matches_raw  = db.execute("SELECT * FROM playoff_matches ORDER BY bracket, round, position").fetchall()
        coaches_all  = db.execute("SELECT * FROM coaches").fetchall()
        settings     = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}

    coaches_map = {c["id"]: dict(c) for c in coaches_all}
    wb_rounds, lb_rounds, gf_matches = _build_playoff_rounds(matches_raw, coaches_map)
    all_standings = get_standings(None)

    return render_template(
        "admin/playoffs.html",
        wb_rounds=wb_rounds,
        lb_rounds=lb_rounds,
        gf_matches=gf_matches,
        all_standings=all_standings,
        has_bracket=bool(matches_raw),
        settings=settings,
        league_name=settings.get("league_name", "Pokemon Draft League"),
    )


@app.route("/admin/playoff_stats/<int:match_id>", methods=["GET", "POST"])
@coach_or_admin_required
def admin_playoff_stats(match_id):
    playoff_match_format = get_setting("playoff_match_format", "BO1")
    max_games = 3 if playoff_match_format == "BO3" else 1

    with get_db() as db:
        ensure_playoffs_table(db)
        pm = db.execute("""
            SELECT pm.*,
                   c1.coach_name as c1_name, c1.id as c1_id, c1.team_name as c1_team,
                   c2.coach_name as c2_name, c2.id as c2_id, c2.team_name as c2_team,
                   c1.logo_url as c1_logo, c2.logo_url as c2_logo,
                   c1.color as c1_color, c2.color as c2_color
            FROM playoff_matches pm
            LEFT JOIN coaches c1 ON pm.coach1_id = c1.id
            LEFT JOIN coaches c2 ON pm.coach2_id = c2.id
            WHERE pm.id=?
        """, (match_id,)).fetchone()
        if not pm:
            return "Playoff match not found", 404
        pm = dict(pm)

        max_round = db.execute(
            "SELECT MAX(round) FROM playoff_matches WHERE bracket='W'"
        ).fetchone()[0] or 1
        round_label = _round_label(pm["round"], max_round)

        games = db.execute(
            "SELECT * FROM match_games WHERE playoff_match_id=? ORDER BY game_number",
            (match_id,)
        ).fetchall()
        games = [dict(g) for g in games]

        all_stats = db.execute(
            "SELECT * FROM match_stats WHERE playoff_match_id=? ORDER BY coach_id, kills DESC",
            (match_id,)
        ).fetchall()
        stats_by_game = {}
        for s in all_stats:
            gid = s["game_id"]
            stats_by_game.setdefault(gid, []).append(dict(s))

        roster1 = db.execute(
            "SELECT pokemon_name FROM pokemon_roster WHERE coach_id=? ORDER BY points DESC",
            (pm["c1_id"],)
        ).fetchall() if pm.get("c1_id") else []
        roster2 = db.execute(
            "SELECT pokemon_name FROM pokemon_roster WHERE coach_id=? ORDER BY points DESC",
            (pm["c2_id"],)
        ).fetchall() if pm.get("c2_id") else []

        game_ids = [g["id"] for g in games]
        lineups_by_game = {}
        if game_ids:
            placeholders = ",".join("?" * len(game_ids))
            all_lineups = db.execute(
                f"SELECT * FROM match_lineups WHERE game_id IN ({placeholders})", game_ids
            ).fetchall()
            for ln in all_lineups:
                gid = ln["game_id"]
                lineups_by_game.setdefault(gid, {})
                lineups_by_game[gid].setdefault(ln["coach_id"], []).append(dict(ln))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_game":
            gnum = int(request.form.get("game_number", 1))
            replay = request.form.get("replay_url", "").strip()
            with get_db() as db:
                db.execute(
                    "INSERT INTO match_games (schedule_id, playoff_match_id, game_number, replay_url) VALUES (0,?,?,?)",
                    (match_id, gnum, replay)
                )
            flash(f"Game {gnum} added!", "success")

        elif action == "update_game":
            gid = request.form["game_id"]
            replay = request.form.get("replay_url", "").strip()
            winner = request.form.get("winner_coach_id") or None
            with get_db() as db:
                db.execute(
                    "UPDATE match_games SET replay_url=?, winner_coach_id=? WHERE id=?",
                    (replay, winner, gid)
                )
            flash("Game updated!", "success")

        elif action == "delete_game":
            gid = request.form["game_id"]
            with get_db() as db:
                db.execute("DELETE FROM match_stats WHERE game_id=?", (gid,))
                db.execute("DELETE FROM match_lineups WHERE game_id=?", (gid,))
                db.execute("DELETE FROM match_games WHERE id=?", (gid,))
            flash("Game deleted.", "warning")

        elif action == "add_lineup":
            game_id = request.form["game_id"]
            coach_id = request.form["coach_id"]
            pokemon_name = request.form.get("pokemon_name", "").strip()
            if pokemon_name:
                with get_db() as db:
                    db.execute(
                        "INSERT OR IGNORE INTO match_lineups (game_id, coach_id, pokemon_name) VALUES (?,?,?)",
                        (game_id, coach_id, pokemon_name)
                    )
                flash("Added to lineup.", "success")

        elif action == "remove_lineup":
            with get_db() as db:
                db.execute("DELETE FROM match_lineups WHERE id=?", (request.form["lineup_id"],))
            flash("Removed from lineup.", "warning")

        elif action == "log_ko":
            game_id = request.form.get("game_id") or None
            attacker_coach = int(request.form["attacker_coach_id"])
            attacker_pokemon = request.form["attacker_pokemon"].strip()
            defender_coach = int(request.form["defender_coach_id"])
            defender_pokemon = request.form["defender_pokemon"].strip()
            if attacker_pokemon and defender_pokemon:
                with get_db() as db:
                    for cid, pname, kd, dd in [
                        (attacker_coach, attacker_pokemon, 1, 0),
                        (defender_coach, defender_pokemon, 0, 1),
                    ]:
                        existing = db.execute(
                            "SELECT id FROM match_stats WHERE playoff_match_id=? AND game_id IS ? AND coach_id=? AND pokemon_name=?",
                            (match_id, game_id, cid, pname)
                        ).fetchone()
                        if existing:
                            db.execute(
                                "UPDATE match_stats SET kills=kills+?, deaths=deaths+? WHERE id=?",
                                (kd, dd, existing["id"])
                            )
                        else:
                            db.execute(
                                "INSERT INTO match_stats (schedule_id, playoff_match_id, game_id, coach_id, pokemon_name, kills, deaths) VALUES (0,?,?,?,?,?,?)",
                                (match_id, game_id, cid, pname, kd, dd)
                            )
                flash(f"{attacker_pokemon} KO'd {defender_pokemon}.", "success")

        elif action == "add_stat":
            game_id = request.form.get("game_id") or None
            with get_db() as db:
                db.execute(
                    "INSERT INTO match_stats (schedule_id, playoff_match_id, game_id, coach_id, pokemon_name, kills, deaths) VALUES (0,?,?,?,?,?,?)",
                    (match_id, game_id, request.form["coach_id"], request.form["pokemon_name"],
                     float(request.form.get("kills", 0)), float(request.form.get("deaths", 0)))
                )
            flash("Stat added!", "success")

        elif action == "delete_stat":
            with get_db() as db:
                db.execute("DELETE FROM match_stats WHERE id=?", (request.form["stat_id"],))
            flash("Stat deleted.", "warning")

        return redirect(url_for("admin_playoff_stats", match_id=match_id))

    return render_template("admin/playoff_stats.html",
                           match=pm,
                           round_label=round_label,
                           games=games,
                           stats_by_game=stats_by_game,
                           lineups_by_game=lineups_by_game,
                           roster1=roster1,
                           roster2=roster2,
                           max_games=max_games,
                           match_format=playoff_match_format,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


# ─── Public: Past Seasons ─────────────────────────────────────────────────────

@app.route("/seasons")
def seasons_list():
    with get_db() as db:
        ensure_seasons_table(db)
        seasons = db.execute("SELECT id, name, archived_at FROM seasons ORDER BY id DESC").fetchall()
    return render_template("seasons.html",
                           seasons=seasons,
                           league_name=get_setting("league_name"))


@app.route("/seasons/<int:season_id>")
def season_archive(season_id):
    with get_db() as db:
        ensure_seasons_table(db)
        row = db.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
    if not row:
        return "Season not found", 404

    data = json.loads(row["data_json"])

    # Compute standings from archived schedule data
    results = {}
    for c in data.get("coaches", []):
        results[c["id"]] = {"coach": c, "W": 0, "L": 0, "T": 0, "diff": 0.0, "weeks": {}}

    for m in data.get("schedule", []):
        c1, c2 = m["coach1_id"], m["coach2_id"]
        if c1 not in results or c2 not in results:
            continue
        s1, s2 = m.get("score1"), m.get("score2")
        if s1 is None or s2 is None:
            continue
        wk = m["week"]
        diff = s1 - s2
        if diff > 0:
            results[c1]["W"] += 1; results[c1]["weeks"][wk] = "W"
            results[c2]["L"] += 1; results[c2]["weeks"][wk] = "L"
        elif diff < 0:
            results[c1]["L"] += 1; results[c1]["weeks"][wk] = "L"
            results[c2]["W"] += 1; results[c2]["weeks"][wk] = "W"
        else:
            results[c1]["T"] += 1; results[c1]["weeks"][wk] = "T"
            results[c2]["T"] += 1; results[c2]["weeks"][wk] = "T"
        results[c1]["diff"] += diff
        results[c2]["diff"] -= diff

    standings_a = sorted([v for v in results.values() if v["coach"].get("pool") == "A"],
                         key=lambda x: (-x["W"], -x["diff"]))
    standings_b = sorted([v for v in results.values() if v["coach"].get("pool") == "B"],
                         key=lambda x: (-x["W"], -x["diff"]))
    for i, r in enumerate(standings_a):
        r["rank"] = i + 1
    for i, r in enumerate(standings_b):
        r["rank"] = i + 1

    all_weeks = sorted(set(m["week"] for m in data.get("schedule", []) if m.get("score1") is not None))

    # Group rosters by coach
    rosters = {}
    for p in data.get("pokemon_roster", []):
        rosters.setdefault(p["coach_id"], []).append(p)

    return render_template("season_archive.html",
                           season=dict(row),
                           data=data,
                           standings_a=standings_a,
                           standings_b=standings_b,
                           all_weeks=all_weeks,
                           rosters=rosters,
                           league_name=get_setting("league_name"))


# ─── Pokedex ──────────────────────────────────────────────────────────────────

@app.route("/pokedex")
def pokedex():
    with get_db() as db:
        rows = db.execute("""
            SELECT p.*, COALESCE(dt.points, NULL) as draft_points,
                   COALESCE(dt.ability1, '') as ability1,
                   COALESCE(dt.ability2, '') as ability2,
                   COALESCE(dt.ability3, '') as ability3,
                   COALESCE(dt.moves, '') as moves
            FROM pokedex p
            LEFT JOIN draft_tiers dt ON LOWER(dt.name) = p.pokeapi_name
            ORDER BY p.pokeapi_id
        """).fetchall()
    return render_template("pokedex.html",
                           pokemon=rows,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


# ─── API endpoints ─────────────────────────────────────────────────────────────

@app.route("/api/coaches")
def api_coaches():
    with get_db() as db:
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
    return jsonify([dict(c) for c in coaches])


@app.route("/api/pokemon_search")
def api_pokemon_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    with get_db() as db:
        results = db.execute(
            "SELECT DISTINCT pokemon_name FROM pokemon_roster WHERE pokemon_name LIKE ? LIMIT 20",
            (f"%{q}%",)
        ).fetchall()
    return jsonify([r["pokemon_name"] for r in results])


# ─── Draft Sheet ──────────────────────────────────────────────────────────────

TIER_ORDER = ["Uber 1", "Uber 2", "Tier 1", "Tier 2", "Tier 3", "Tier 4", "Tier 5", "Free Pick"]

DEFAULT_ROUND_STRUCTURE = [
    {"name": "Uber 1",    "tier_filter": "uber",    "picks_per_coach": 2},
    {"name": "Uber 2",    "tier_filter": "uber",    "picks_per_coach": 2},
    {"name": "Tier 1",    "tier_filter": "Tier 1",  "picks_per_coach": 2},
    {"name": "Tier 2",    "tier_filter": "Tier 2",  "picks_per_coach": 2},
    {"name": "Tier 3",    "tier_filter": "Tier 3",  "picks_per_coach": 2},
    {"name": "Tier 4",    "tier_filter": "Tier 4",  "picks_per_coach": 2},
    {"name": "Tier 5",    "tier_filter": "Tier 5",  "picks_per_coach": 2},
    {"name": "Free Pick", "tier_filter": "any",     "picks_per_coach": 8},
]


def _get_snake_pick_sequence(snake_order, round_structure):
    """Return flat list of (pick_number, round_idx, slot_name, coach_id) tuples."""
    picks = []
    pick_num = 1
    for round_idx, rnd in enumerate(round_structure):
        picks_per = rnd["picks_per_coach"]
        for pass_num in range(picks_per):
            order = snake_order if (round_idx * picks_per + pass_num) % 2 == 0 else list(reversed(snake_order))
            for coach_id in order:
                picks.append((pick_num, round_idx, rnd["name"], coach_id))
                pick_num += 1
    return picks


def _auto_slot(pokemon_name, poke_pts, mega_names_set, existing_roster_rows):
    """Auto-assign a new pick to the correct roster slot.

    Fills paid slots (2 per tier) before free slots (1 per tier).
    Overflows to 'Free Pick' when all slots of that tier are used.
    Returns (slot_name, is_free_pick).
    """
    if pokemon_name in mega_names_set:
        return "Mega", True

    pts = poke_pts or 0
    tier = _regular_tier_label(pts)

    if not tier:
        if pts > 0:  # uber-level pokemon
            uber1 = sum(1 for p in existing_roster_rows if p["tier"] == "Uber 1")
            uber2 = sum(1 for p in existing_roster_rows if p["tier"] == "Uber 2")
            if uber1 < 2:
                return "Uber 1", False
            elif uber2 < 2:
                return "Uber 2", False
        return "Free Pick", False

    paid = sum(1 for p in existing_roster_rows if p["tier"] == tier and not p["is_free_pick"])
    free = sum(1 for p in existing_roster_rows if p["tier"] == tier and p["is_free_pick"])
    if paid < 2:
        return tier, False
    elif free < 1:
        return tier, True
    return "Free Pick", False


def _build_draft_grid(coaches_pool, roster_rows, tier_order=None):
    """Build a 2D grid structure: {tier: {coach_id: [pokemon_list]}} and max picks per tier."""
    if tier_order is None:
        tier_order = TIER_ORDER
    grid = {t: {c["id"]: [] for c in coaches_pool} for t in tier_order}
    for row in roster_rows:
        tier = row["tier"] if row["tier"] in tier_order else "Free Pick"
        cid = row["coach_id"]
        if cid in grid.get(tier, {}):
            grid[tier][cid].append(dict(row))
    # Max picks per tier (to know how many rows)
    max_picks = {}
    for t in tier_order:
        max_picks[t] = max((len(grid[t][c["id"]]) for c in coaches_pool), default=0)
        if max_picks[t] == 0:
            max_picks[t] = 1
    return grid, max_picks


@app.route("/draft")
def draft_sheet():
    with get_db() as db:
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
        roster = db.execute(
            "SELECT pr.*, c.pool FROM pokemon_roster pr JOIN coaches c ON pr.coach_id = c.id"
        ).fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
        active_session = db.execute(
            "SELECT * FROM draft_sessions WHERE status IN ('active','paused') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        mega_names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers WHERE is_mega=1").fetchall()}

    budget = int(settings.get("points_budget", 45))
    coaches_a = [c for c in coaches if c["pool"] == "A"]
    coaches_b = [c for c in coaches if c["pool"] == "B"]
    roster_a = [r for r in roster if r["pool"] == "A"]
    roster_b = [r for r in roster if r["pool"] == "B"]

    def _build_team_card(coach, roster_picks):
        picks = [dict(r) for r in roster_picks if r["coach_id"] == coach["id"]]

        def _tier(tier, free=False):
            return [p for p in picks if p.get("tier") == tier
                    and bool(p.get("is_free_pick")) == free
                    and p["pokemon_name"] not in mega_names]

        mega  = [p for p in picks if p["pokemon_name"] in mega_names]
        free  = [p for p in picks if p.get("tier") == "Free Pick"
                 and p["pokemon_name"] not in mega_names]
        spent = sum(p["points"] for p in picks if p.get("tier") == "Free Pick" and not p.get("is_free_pick"))

        return {
            "coach": dict(coach),
            "spent": spent,
            "remaining": budget - spent,
            "slots": {
                "uber1":  _tier("Uber 1"),
                "uber2":  _tier("Uber 2"),
                "tier1":  _tier("Tier 1"),  "tier1f": _tier("Tier 1", free=True),
                "tier2":  _tier("Tier 2"),  "tier2f": _tier("Tier 2", free=True),
                "tier3":  _tier("Tier 3"),  "tier3f": _tier("Tier 3", free=True),
                "tier4":  _tier("Tier 4"),  "tier4f": _tier("Tier 4", free=True),
                "tier5":  _tier("Tier 5"),  "tier5f": _tier("Tier 5", free=True),
                "mega":   mega,
                "free":   free,
            },
        }

    teams_a = [_build_team_card(c, roster_a) for c in coaches_a]
    teams_b = [_build_team_card(c, roster_b) for c in coaches_b]

    return render_template(
        "draft.html",
        teams_a=teams_a, teams_b=teams_b,
        budget=budget,
        active_session=active_session,
        settings=settings,
        league_name=settings.get("league_name", "Pokemon Draft League"),
    )


@app.route("/draft/live")
def draft_live():
    with get_db() as db:
        session_row = db.execute(
            "SELECT * FROM draft_sessions WHERE status IN ('active','paused') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}

        if session_row is None:
            return render_template(
                "draft_live.html",
                session=None, coaches=coaches,
                league_name=settings.get("league_name", "Pokemon Draft League"),
            )

        picks = db.execute(
            "SELECT * FROM draft_picks WHERE session_id=? ORDER BY pick_number",
            (session_row["id"],)
        ).fetchall()

        # Available pokemon (not yet picked)
        picked_names = {p["pokemon_name"] for p in picks}

        round_structure_str = settings.get("draft_round_structure", "")
        try:
            round_structure = json.loads(round_structure_str) if round_structure_str else DEFAULT_ROUND_STRUCTURE
        except Exception:
            round_structure = DEFAULT_ROUND_STRUCTURE

        snake_order = json.loads(session_row["snake_order"] or "[]")
        current_pick = session_row["current_pick"]
        current_round = session_row["current_round"]

        seq = _get_snake_pick_sequence(snake_order, round_structure)
        current_slot = seq[current_pick - 1] if seq and 0 < current_pick <= len(seq) else None
        next_5 = seq[current_pick - 1: current_pick + 4] if seq else []

        mega_names_set = {r["name"] for r in db.execute(
            "SELECT name FROM draft_tiers WHERE is_mega=1"
        ).fetchall()}

        all_draft = db.execute(
            "SELECT * FROM draft_tiers WHERE is_banned != 1 ORDER BY points DESC, name"
        ).fetchall()

        # All picks are free-order; first overall pick must be a regular-tier pokemon (not mega)
        is_first_pick = (current_pick == 1)
        avail_pokemon = []
        for p in all_draft:
            if p["name"] in picked_names:
                continue
            if is_first_pick and p["name"] in mega_names_set:
                continue
            computed_tier = _regular_tier_label(p["points"] or 0)
            avail_pokemon.append(dict(p, tier_label=computed_tier or p["tier_label"] or ""))

        # Fetch captain status from pokemon_roster
        captain_rows = db.execute(
            "SELECT coach_id, pokemon_name, is_tera_captain, is_zmove_captain FROM pokemon_roster"
        ).fetchall()
        captain_map = {(r["coach_id"], r["pokemon_name"]): r for r in captain_rows}

        # Build grid from draft_picks (with captain status)
        roster_from_picks = []
        for p in picks:
            capt = captain_map.get((p["coach_id"], p["pokemon_name"]))
            roster_from_picks.append({
                "coach_id": p["coach_id"], "pokemon_name": p["pokemon_name"],
                "points": p["points"], "tier": p["slot_name"],
                "is_tera_captain": int(capt["is_tera_captain"]) if capt else 0,
                "is_zmove_captain": int(capt["is_zmove_captain"]) if capt else 0,
                "is_free_pick": (p["slot_name"] == "Free Pick"),
            })
        grid_a, max_a = _build_draft_grid([c for c in coaches if c["pool"] == "A"], roster_from_picks)
        grid_b, max_b = _build_draft_grid([c for c in coaches if c["pool"] == "B"], roster_from_picks)

        coaches_map = {c["id"]: dict(c) for c in coaches}
        current_coach_id = current_slot[3] if current_slot else None

    is_admin = session.get("role") == "admin"
    my_coach_id = session.get("coach_id")
    can_pick = is_admin or (my_coach_id == current_coach_id)

    # Build current user's picks with captain data for the captain panel
    my_picks = []
    if my_coach_id:
        for p in picks:
            if p["coach_id"] == my_coach_id:
                capt = captain_map.get((my_coach_id, p["pokemon_name"]))
                my_picks.append({
                    "pokemon_name": p["pokemon_name"],
                    "points": p["points"],
                    "coach_id": my_coach_id,
                    "is_tera_captain": int(capt["is_tera_captain"]) if capt else 0,
                    "is_zmove_captain": int(capt["is_zmove_captain"]) if capt else 0,
                })

    return render_template(
        "draft_live.html",
        session=dict(session_row),
        picks=picks,
        coaches=coaches,
        coaches_a=[c for c in coaches if c["pool"] == "A"],
        coaches_b=[c for c in coaches if c["pool"] == "B"],
        grid_a=grid_a, grid_b=grid_b,
        max_a=max_a, max_b=max_b,
        tier_order=TIER_ORDER,
        avail_pokemon=avail_pokemon,
        current_slot=current_slot,
        next_5=next_5,
        coaches_map=coaches_map,
        current_coach_id=current_coach_id,
        can_pick=can_pick,
        is_admin=is_admin,
        round_structure=round_structure,
        seq=seq,
        my_coach_id=my_coach_id,
        my_picks=my_picks,
        mechanic_tera=settings.get("mechanic_tera", "0"),
        mechanic_zmove=settings.get("mechanic_zmove", "0"),
        league_name=settings.get("league_name", "Pokemon Draft League"),
    )


@app.route("/draft/live/pick", methods=["POST"])
def draft_live_pick():
    if not session.get("user_id"):
        return jsonify({"error": "Login required"}), 401

    pokemon_name = request.form.get("pokemon_name", "").strip()
    if not pokemon_name:
        flash("No Pokemon specified.", "warning")
        return redirect(url_for("draft_live"))

    with get_db() as db:
        session_row = db.execute(
            "SELECT * FROM draft_sessions WHERE status='active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not session_row:
            flash("No active draft session.", "warning")
            return redirect(url_for("draft_live"))

        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
        round_structure_str = settings.get("draft_round_structure", "")
        try:
            round_structure = json.loads(round_structure_str) if round_structure_str else DEFAULT_ROUND_STRUCTURE
        except Exception:
            round_structure = DEFAULT_ROUND_STRUCTURE

        snake_order = json.loads(session_row["snake_order"] or "[]")
        current_pick = session_row["current_pick"]
        seq = _get_snake_pick_sequence(snake_order, round_structure)

        if not seq or current_pick < 1 or current_pick > len(seq):
            flash("Draft is complete or pick number is invalid.", "warning")
            return redirect(url_for("draft_live"))

        pick_num, round_idx, slot_name, coach_id = seq[current_pick - 1]

        is_admin = session.get("role") == "admin"
        my_coach_id = session.get("coach_id")
        if not is_admin and my_coach_id != coach_id:
            flash("It's not your turn.", "warning")
            return redirect(url_for("draft_live"))

        # Check not already picked
        existing = db.execute(
            "SELECT id FROM draft_picks WHERE session_id=? AND pokemon_name=?",
            (session_row["id"], pokemon_name)
        ).fetchone()
        if existing:
            flash(f"{pokemon_name} has already been picked.", "warning")
            return redirect(url_for("draft_live"))

        # Verify pokemon exists in draft_tiers and is not banned
        poke_row = db.execute(
            "SELECT * FROM draft_tiers WHERE name=? AND is_banned != 1", (pokemon_name,)
        ).fetchone()
        if not poke_row:
            flash(f"{pokemon_name} is not in the tier list or is banned.", "warning")
            return redirect(url_for("draft_live"))

        points = poke_row["points"] or 0
        mega_names_set = {r["name"] for r in db.execute(
            "SELECT name FROM draft_tiers WHERE is_mega=1"
        ).fetchall()}
        is_mega = pokemon_name in mega_names_set

        # First overall pick must be a regular-tier pokemon (not mega, must have pts ≥ 1)
        if pick_num == 1 and (is_mega or points < 1):
            flash("The first pick must be a regular-tier Pokemon (not Mega).", "warning")
            return redirect(url_for("draft_live"))

        # Enforce max 11 picks per team
        team_pick_count = db.execute(
            "SELECT COUNT(*) FROM pokemon_roster WHERE coach_id=?", (coach_id,)
        ).fetchone()[0]
        if team_pick_count >= 11:
            flash(f"This team already has {team_pick_count} picks (max 11).", "warning")
            return redirect(url_for("draft_live"))

        # Auto-assign to the correct roster slot based on actual pokemon tier
        coach_roster = db.execute(
            "SELECT tier, is_free_pick FROM pokemon_roster WHERE coach_id=?", (coach_id,)
        ).fetchall()
        actual_slot, is_free = _auto_slot(pokemon_name, points, mega_names_set, coach_roster)

        db.execute(
            "INSERT INTO draft_picks (session_id, pick_number, round_number, slot_name, coach_id, pokemon_name, points) VALUES (?,?,?,?,?,?,?)",
            (session_row["id"], pick_num, round_idx + 1, actual_slot, coach_id, pokemon_name, points)
        )
        db.execute(
            "INSERT OR IGNORE INTO pokemon_roster (coach_id, pokemon_name, points, tier, is_tera_captain, is_zmove_captain, is_free_pick) VALUES (?,?,?,?,0,0,?)",
            (coach_id, pokemon_name, points, actual_slot, 1 if is_free else 0)
        )
        db.execute(
            "UPDATE draft_sessions SET current_pick=? WHERE id=?",
            (current_pick + 1, session_row["id"])
        )

    flash(f"Picked {pokemon_name}!", "success")
    return redirect(url_for("draft_live"))


@app.route("/draft/live/set_captain", methods=["POST"])
def draft_live_set_captain():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    pokemon_name = request.form.get("pokemon_name", "").strip()
    captain_type = request.form.get("captain_type", "")
    value = request.form.get("value", "0")
    target_coach_id = request.form.get("coach_id", "")

    if captain_type not in ("tera", "zmove") or value not in ("0", "1") or not pokemon_name:
        flash("Invalid captain data.", "error")
        return redirect(url_for("draft_live"))

    value = int(value)
    is_admin = session.get("role") == "admin"
    my_coach_id = session.get("coach_id")

    try:
        target_coach_id = int(target_coach_id)
    except (ValueError, TypeError):
        target_coach_id = my_coach_id

    if not is_admin and target_coach_id != my_coach_id:
        flash("Not authorized.", "error")
        return redirect(url_for("draft_live"))

    col = "is_tera_captain" if captain_type == "tera" else "is_zmove_captain"
    with get_db() as db:
        db.execute(
            f"UPDATE pokemon_roster SET {col}=? WHERE coach_id=? AND pokemon_name=?",
            (value, target_coach_id, pokemon_name)
        )

    return redirect(url_for("draft_live"))


# ─── Replays ──────────────────────────────────────────────────────────────────

@app.route("/replays")
def replays():
    with get_db() as db:
        rows = db.execute("""
            SELECT mg.id, mg.game_number, mg.replay_url, mg.winner_coach_id,
                   s.week, s.coach1_id, s.coach2_id, s.score1, s.score2,
                   c1.team_name AS c1_team, c1.coach_name AS c1_coach,
                   c1.logo_url AS c1_logo, c1.color AS c1_color,
                   c2.team_name AS c2_team, c2.coach_name AS c2_coach,
                   c2.logo_url AS c2_logo, c2.color AS c2_color
            FROM match_games mg
            JOIN schedule s ON mg.schedule_id = s.id
            JOIN coaches c1 ON s.coach1_id = c1.id
            JOIN coaches c2 ON s.coach2_id = c2.id
            WHERE mg.replay_url IS NOT NULL AND mg.replay_url != ''
            ORDER BY s.week, mg.id
        """).fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}

    # Group by week
    weeks = {}
    for row in rows:
        wk = row["week"]
        if wk not in weeks:
            weeks[wk] = []
        weeks[wk].append(dict(row))

    return render_template(
        "replays.html",
        weeks=weeks,
        league_name=settings.get("league_name", "Pokemon Draft League"),
    )


# ─── Admin: Draft ─────────────────────────────────────────────────────────────

@app.route("/admin/draft", methods=["GET", "POST"])
@admin_required
def admin_draft():
    with get_db() as db:
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
        sessions = db.execute("SELECT * FROM draft_sessions ORDER BY id DESC").fetchall()
        active_session = db.execute(
            "SELECT * FROM draft_sessions WHERE status IN ('active','paused') ORDER BY id DESC LIMIT 1"
        ).fetchone()

    round_structure_str = settings.get("draft_round_structure", "")
    try:
        round_structure = json.loads(round_structure_str) if round_structure_str else DEFAULT_ROUND_STRUCTURE
    except Exception:
        round_structure = DEFAULT_ROUND_STRUCTURE

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create_session":
            name = request.form.get("name", "Draft Session").strip()
            season = request.form.get("season", "").strip()
            snake_ids = request.form.getlist("snake_order")
            snake_json = json.dumps([int(x) for x in snake_ids if x])
            with get_db() as db:
                db.execute(
                    "INSERT INTO draft_sessions (name, season, status, snake_order, current_round, current_pick) VALUES (?,?,?,?,?,?)",
                    (name, season, "setup", snake_json, 1, 1)
                )
            flash("Draft session created.", "success")

        elif action == "save_rounds":
            rounds_json = request.form.get("rounds_json", "[]")
            with get_db() as db:
                db.execute(
                    "INSERT OR REPLACE INTO league_settings (key, value) VALUES (?,?)",
                    ("draft_round_structure", rounds_json)
                )
            flash("Round structure saved.", "success")

        elif action == "start":
            sid = request.form.get("session_id")
            with get_db() as db:
                db.execute("UPDATE draft_sessions SET status='active', current_pick=1 WHERE id=?", (sid,))
            flash("Draft started.", "success")

        elif action == "pause":
            sid = request.form.get("session_id")
            with get_db() as db:
                db.execute("UPDATE draft_sessions SET status='paused' WHERE id=?", (sid,))
            flash("Draft paused.", "success")

        elif action == "resume":
            sid = request.form.get("session_id")
            with get_db() as db:
                db.execute("UPDATE draft_sessions SET status='active' WHERE id=?", (sid,))
            flash("Draft resumed.", "success")

        elif action == "complete":
            sid = request.form.get("session_id")
            with get_db() as db:
                db.execute("UPDATE draft_sessions SET status='completed' WHERE id=?", (sid,))
            flash("Draft marked complete.", "success")

        elif action == "reset":
            sid = request.form.get("session_id")
            with get_db() as db:
                db.execute("UPDATE draft_sessions SET status='setup', current_pick=1, current_round=1 WHERE id=?", (sid,))
                db.execute("DELETE FROM draft_picks WHERE session_id=?", (sid,))
            flash("Draft reset.", "warning")

        elif action == "set_pick":
            sid = request.form.get("session_id")
            try:
                pick_num = int(request.form.get("pick_number", 1))
            except ValueError:
                pick_num = 1
            with get_db() as db:
                db.execute("UPDATE draft_sessions SET current_pick=? WHERE id=?", (pick_num, sid))
            flash(f"Current pick set to {pick_num}.", "success")

        elif action == "update_snake":
            sid = request.form.get("session_id")
            snake_ids = request.form.getlist("snake_order")
            snake_json = json.dumps([int(x) for x in snake_ids if x])
            with get_db() as db:
                db.execute("UPDATE draft_sessions SET snake_order=? WHERE id=?", (snake_json, sid))
            flash("Snake order updated.", "success")

        return redirect(url_for("admin_draft"))

    # Build snake order coach list for active session
    active_snake = []
    if active_session:
        snake_ids = json.loads(active_session["snake_order"] or "[]")
        coaches_map = {c["id"]: dict(c) for c in coaches}
        active_snake = [coaches_map[cid] for cid in snake_ids if cid in coaches_map]

    return render_template(
        "admin/draft.html",
        coaches=coaches,
        sessions=sessions,
        active_session=active_session,
        active_snake=active_snake,
        round_structure=round_structure,
        round_structure_json=json.dumps(round_structure, indent=2),
        league_name=settings.get("league_name", "Pokemon Draft League"),
    )


@app.route("/draft-prep")
def draft_prep():
    with get_db() as db:
        tiers = db.execute(
            """SELECT name, points, tier_label, is_mega,
                      ability1, ability2, ability3, moves
               FROM draft_tiers
               WHERE is_banned != 1
               ORDER BY points DESC, name"""
        ).fetchall()
        # Build pokedex lookup: pokeapi_name (slug) → row
        pokedex_rows = db.execute(
            "SELECT pokeapi_name, type1, type2, hp, atk, def_stat, spa, spd, spe FROM pokedex"
        ).fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}

    pokedex_map = {r["pokeapi_name"]: r for r in pokedex_rows}

    pokemon_data = []
    for t in tiers:
        # Resolve type/stat from pokedex using slug candidates
        pd = None
        for slug in _name_to_slug(t["name"]):
            if slug in pokedex_map:
                pd = pokedex_map[slug]
                break

        type1   = pd["type1"]    if pd else ""
        type2   = pd["type2"]    if pd else ""
        hp      = pd["hp"]       if pd else 0
        atk     = pd["atk"]      if pd else 0
        defense = pd["def_stat"] if pd else 0
        spa     = pd["spa"]      if pd else 0
        spd     = pd["spd"]      if pd else 0
        spe     = pd["spe"]      if pd else 0
        bst     = (hp + atk + defense + spa + spd + spe) if pd else 0

        pokemon_data.append({
            "name":     t["name"],
            "points":   t["points"] or 0,
            "tier":     t["tier_label"] or "",
            "is_mega":  bool(t["is_mega"]),
            "ability1": t["ability1"] or "",
            "ability2": t["ability2"] or "",
            "ability3": t["ability3"] or "",
            "moves":    (t["moves"] or "").split("|") if t["moves"] else [],
            "type1":    type1 or "",
            "type2":    type2 or "",
            "hp":       hp  or 0,
            "atk":      atk or 0,
            "defense":  defense or 0,
            "spa":      spa or 0,
            "spd":      spd or 0,
            "spe":      spe or 0,
            "bst":      bst or 0,
            "sprite":   pokemon_static_sprite_url(t["name"]),
        })

    budget = int(settings.get("points_budget", 45))
    league_name = settings.get("league_name", "Pokemon Draft League")

    return render_template(
        "draft_prep.html",
        pokemon_json=json.dumps(pokemon_data),
        budget=budget,
        league_name=league_name,
        mechanic_tera=settings.get("mechanic_tera", "0"),
        mechanic_zmove=settings.get("mechanic_zmove", "0"),
    )


@app.route("/battle-prep")
def battle_prep():
    with get_db() as db:
        coaches = db.execute(
            "SELECT id, coach_name, team_name, color FROM coaches ORDER BY coach_name"
        ).fetchall()
        roster_rows = db.execute(
            """SELECT pr.coach_id, pr.pokemon_name, pr.points, pr.tier,
                      dt.ability1, dt.ability2, dt.ability3, dt.moves
               FROM pokemon_roster pr
               LEFT JOIN draft_tiers dt ON LOWER(pr.pokemon_name) = LOWER(dt.name)
               ORDER BY pr.points DESC, pr.pokemon_name"""
        ).fetchall()
        pokedex_rows = db.execute(
            "SELECT pokeapi_name, type1, type2, hp, atk, def_stat, spa, spd, spe FROM pokedex"
        ).fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}

    pokedex_map = {r["pokeapi_name"]: r for r in pokedex_rows}

    coaches_data = {}
    for c in coaches:
        coaches_data[c["id"]] = {
            "id": c["id"],
            "name": c["coach_name"],
            "team_name": c["team_name"] or c["coach_name"],
            "color": c["color"] or "#6b7280",
            "pokemon": [],
        }

    for r in roster_rows:
        if r["coach_id"] not in coaches_data:
            continue
        pd = None
        for slug in _name_to_slug(r["pokemon_name"]):
            if slug in pokedex_map:
                pd = pokedex_map[slug]
                break
        type1   = pd["type1"]    if pd else ""
        type2   = pd["type2"]    if pd else ""
        hp      = pd["hp"]       if pd else 0
        atk     = pd["atk"]      if pd else 0
        defense = pd["def_stat"] if pd else 0
        spa     = pd["spa"]      if pd else 0
        spd     = pd["spd"]      if pd else 0
        spe     = pd["spe"]      if pd else 0
        coaches_data[r["coach_id"]]["pokemon"].append({
            "name":     r["pokemon_name"],
            "points":   r["points"] or 0,
            "tier":     r["tier"] or "",
            "ability1": r["ability1"] or "",
            "ability2": r["ability2"] or "",
            "ability3": r["ability3"] or "",
            "moves":    (r["moves"] or "").split("|") if r["moves"] else [],
            "type1":    type1 or "",
            "type2":    type2 or "",
            "hp": hp or 0, "atk": atk or 0, "defense": defense or 0,
            "spa": spa or 0, "spd": spd or 0, "spe": spe or 0,
            "bst": (hp + atk + defense + spa + spd + spe) if pd else 0,
            "sprite": pokemon_static_sprite_url(r["pokemon_name"]),
        })

    return render_template(
        "battle_prep.html",
        coaches_json=json.dumps(list(coaches_data.values())),
        league_name=settings.get("league_name", "Pokemon Draft League"),
    )


@app.route("/damage-calc")
def damage_calc():
    with get_db() as db:
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
    return render_template("damage_calc.html", league_name=settings.get("league_name", "Pokemon Draft League"))


@app.route("/damage-calc/static/<path:filename>")
def damage_calc_static(filename):
    return send_from_directory(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "calc"),
        filename
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
