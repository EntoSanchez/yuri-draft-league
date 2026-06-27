import sqlite3
import hashlib
import os
import json
import math
import re
import secrets
import uuid
import urllib.request
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from contextlib import contextmanager
from replay_utils import (fetch_replay as _replay_fetch, parse_log as _replay_parse_log,
                          resolve_poke_name as _replay_resolve_poke, remap_dict as _replay_remap,
                          parse_log_recap as _replay_parse_recap, build_recap as _replay_build_recap,
                          TYPE_COLORS as _RECAP_TYPE_COLORS)

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


def _migrate_db():
    """Safe additive migrations for Plan Griffin columns."""
    with get_db() as db:
        for stmt in [
            "ALTER TABLE coaches ADD COLUMN draft_mode TEXT",
            "ALTER TABLE draft_picks ADD COLUMN ticket_used TEXT",
            "ALTER TABLE coaches ADD COLUMN is_defending_champ INTEGER DEFAULT 0",
            "ALTER TABLE draft_sessions ADD COLUMN current_pick_a INTEGER DEFAULT 1",
            "ALTER TABLE draft_sessions ADD COLUMN current_pick_b INTEGER DEFAULT 1",
            "ALTER TABLE draft_sessions ADD COLUMN bank_pending_a INTEGER DEFAULT 0",
            "ALTER TABLE draft_sessions ADD COLUMN bank_pending_b INTEGER DEFAULT 0",
            "ALTER TABLE draft_sessions ADD COLUMN banked_picks TEXT DEFAULT '{}'",
            "ALTER TABLE pokemon_roster ADD COLUMN is_zmove_captain INTEGER DEFAULT 0",
            "ALTER TABLE pokemon_roster ADD COLUMN is_free_pick INTEGER DEFAULT 0",
            "ALTER TABLE seasons ADD COLUMN season_num INTEGER DEFAULT 0",
            "ALTER TABLE match_games ADD COLUMN recap_json TEXT",
        ]:
            try:
                db.execute(stmt)
            except Exception:
                pass
        # Rename legacy "Test Archive" to proper season name
        try:
            if not db.execute(
                "SELECT 1 FROM league_settings WHERE key='_migration_season_rename_v1'"
            ).fetchone():
                db.execute(
                    "UPDATE seasons SET name='Yuri Cup Season 8', season_num=8 WHERE name='Test Archive'"
                )
                db.execute("INSERT INTO league_settings (key, value) VALUES ('_migration_season_rename_v1', '1')")
        except Exception:
            pass
        # One-time reset: coaches got 'points' auto-assigned by the old DEFAULT clause.
        try:
            if not db.execute(
                "SELECT 1 FROM league_settings WHERE key='_migration_draft_mode_reset_v1'"
            ).fetchone():
                db.execute("UPDATE coaches SET draft_mode = NULL WHERE draft_mode = 'points'")
                db.execute("INSERT INTO league_settings (key, value) VALUES ('_migration_draft_mode_reset_v1', '1')")
        except Exception:
            pass
        db.execute("INSERT OR IGNORE INTO league_settings (key, value) VALUES ('points_budget_griffin', '70')")
        db.execute("INSERT OR IGNORE INTO league_settings (key, value) VALUES ('draft_format', '')")
        db.execute("""
            CREATE TABLE IF NOT EXISTS match_preview_lineups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id INTEGER NOT NULL,
                coach_id INTEGER NOT NULL,
                pokemon_name TEXT NOT NULL,
                UNIQUE(schedule_id, coach_id, pokemon_name)
            )
        """)


def _effective_draft_mode(coach, draft_format):
    if draft_format != "griffin":
        return "legacy"
    return (coach["draft_mode"] or "tier_tickets")


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
        "basculin":              "basculin-red-striped",
        "eiscue":                "eiscue-ice",
        "frillish":              "frillish-male",
        "meowstic":              "meowstic-male",
        "nidoran-male":          "nidoran-m",
        "nidoran-female":        "nidoran-f",
        "oinkologne":            "oinkologne-male",
        "pumpkaboo":             "pumpkaboo-average",
        "pyroar":                "pyroar-male",
        "squawkabilly":          "squawkabilly-green-plumage",
        "wishiwashi":            "wishiwashi-solo",
        "wormadam":              "wormadam-plant",
        "tatsugiri":             "tatsugiri-curly",
        "zygarde":               "zygarde-50",
        "zygarde 10%":           "zygarde-10",
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

    # PokeAPI-format mega-X/Y/Z slugs need Showdown adjustment: Showdown omits the
    # hyphen before the variant letter. e.g. "charizard-mega-x" → "charizard-megax"
    _xy = re.match(r'^(.+)-mega-([xyz])$', base)
    xy_mega_slug = f"{_xy.group(1)}-mega{_xy.group(2)}" if _xy and not showdown_slug else None

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
    # Note: Showdown omits the hyphen before the variant letter (megax not mega-x).
    # For X/Y/Z variants also include the PokeAPI-format slug (with hyphen) so the
    # ID map can resolve canonical sprites: "charizard-mega-x" → ID 10034.
    mega_slug = None
    mega_slug_pokeapi = None
    if base.startswith("mega "):
        rest = base[5:]
        parts = rest.split()
        if len(parts) >= 2 and parts[-1].lower() in ("x", "y", "z"):
            pokemon_part = "-".join(parts[:-1])
            variant = parts[-1].lower()
            mega_slug = pokemon_part + "-mega" + variant         # Showdown: "charizard-megax"
            mega_slug_pokeapi = pokemon_part + "-mega-" + variant  # PokeAPI:  "charizard-mega-x"
        else:
            mega_slug = rest.replace(" ", "-") + "-mega"

    # Primal forms: "Primal X" → "x-primal"
    primal_slug = None
    if base.startswith("primal "):
        primal_slug = base[7:].replace(" ", "-") + "-primal"

    # showdown_slug first so slugs[0] is always the correct Showdown CDN slug
    return [s for s in [showdown_slug, xy_mega_slug, regional_slug, mega_slug, mega_slug_pokeapi, primal_slug, alias, naive] if s]


# Legends Z-A / Champions megas that no public sprite source hosts yet —
# self-hosted official artwork (static/sprites/megas/, sourced from Serebii).
_MEGA_SPRITE_OVERRIDES = {
    "mega absol z":            "/static/sprites/megas/mega-absol-z.png",
    "mega barbaracle":         "/static/sprites/megas/mega-barbaracle.png",
    "mega baxcalibur":         "/static/sprites/megas/mega-baxcalibur.png",
    "mega chandelure":         "/static/sprites/megas/mega-chandelure.png",
    "mega chesnaught":         "/static/sprites/megas/mega-chesnaught.png",
    "mega chimecho":           "/static/sprites/megas/mega-chimecho.png",
    "mega clefable":           "/static/sprites/megas/mega-clefable.png",
    "mega crabominable":       "/static/sprites/megas/mega-crabominable.png",
    "mega darkrai":            "/static/sprites/megas/mega-darkrai.png",
    "mega delphox":            "/static/sprites/megas/mega-delphox.png",
    "mega dragalge":           "/static/sprites/megas/mega-dragalge.png",
    "mega dragonite":          "/static/sprites/megas/mega-dragonite.png",
    "mega drampa":             "/static/sprites/megas/mega-drampa.png",
    "mega eelektross":         "/static/sprites/megas/mega-eelektross.png",
    "mega emboar":             "/static/sprites/megas/mega-emboar.png",
    "mega excadrill":          "/static/sprites/megas/mega-excadrill.png",
    "mega falinks":            "/static/sprites/megas/mega-falinks.png",
    "mega feraligatr":         "/static/sprites/megas/mega-feraligatr.png",
    "mega floette":            "/static/sprites/megas/mega-floette.png",
    "mega froslass":           "/static/sprites/megas/mega-froslass.png",
    "mega garchomp z":         "/static/sprites/megas/mega-garchomp-z.png",
    "mega glimmora":           "/static/sprites/megas/mega-glimmora.png",
    "mega golisopod":          "/static/sprites/megas/mega-golisopod.png",
    "mega golurk":             "/static/sprites/megas/mega-golurk.png",
    "mega greninja":           "/static/sprites/megas/mega-greninja.png",
    "mega hawlucha":           "/static/sprites/megas/mega-hawlucha.png",
    "mega heatran":            "/static/sprites/megas/mega-heatran.png",
    "mega lucario z":          "/static/sprites/megas/mega-lucario-z.png",
    "mega magearna":           "/static/sprites/megas/mega-magearna.png",
    "mega magearna original":  "/static/sprites/megas/mega-magearna-original.png",
    "mega malamar":            "/static/sprites/megas/mega-malamar.png",
    "mega meganium":           "/static/sprites/megas/mega-meganium.png",
    "mega meowstic":           "/static/sprites/megas/mega-meowstic.png",
    "mega pyroar":             "/static/sprites/megas/mega-pyroar.png",
    "mega raichu x":           "/static/sprites/megas/mega-raichu-x.png",
    "mega raichu y":           "/static/sprites/megas/mega-raichu-y.png",
    "mega scolipede":          "/static/sprites/megas/mega-scolipede.png",
    "mega scovillain":         "/static/sprites/megas/mega-scovillain.png",
    "mega scrafty":            "/static/sprites/megas/mega-scrafty.png",
    "mega skarmory":           "/static/sprites/megas/mega-skarmory.png",
    "mega staraptor":          "/static/sprites/megas/mega-staraptor.png",
    "mega starmie":            "/static/sprites/megas/mega-starmie.png",
    "mega tatsugiri curly":    "/static/sprites/megas/mega-tatsugiri-curly.png",
    "mega tatsugiri droopy":   "/static/sprites/megas/mega-tatsugiri-droopy.png",
    "mega tatsugiri stretchy": "/static/sprites/megas/mega-tatsugiri-stretchy.png",
    "mega victreebel":         "/static/sprites/megas/mega-victreebel.png",
    "mega zeraora":            "/static/sprites/megas/mega-zeraora.png",
    "mega zygarde":            "/static/sprites/megas/mega-zygarde.png",
}


def _local_mega_sprite(name):
    """Self-hosted sprite path for new megas with no public sprite source, else None."""
    return _MEGA_SPRITE_OVERRIDES.get((name or "").strip().lower())


def pokemon_sprite_url(name, shiny=False):
    """Return the animated GIF sprite URL for a Pokemon name.

    Priority:
    1. PokeAPI GitHub showdown GIF via numeric ID (Gen 1-8, IDs 1-905 only —
       PokeAPI GitHub does not have animated GIFs for Gen 9+)
    2. Showdown CDN slug-based URL (covers all gens including Gen 9)
    """
    ov = _local_mega_sprite(name)
    if ov:
        return ov
    slugs = _name_to_slug(name)
    for slug in slugs:
        pid = _pokemon_id_map.get(slug)
        if pid and 1 <= pid <= 905:
            folder = f"{SPRITE_BASE}/shiny" if shiny else SPRITE_BASE
            return f"{folder}/{pid}.gif"
    # Fallback: Showdown CDN (has animated sprites for all gens including Gen 9)
    ani_folder = f"{SHOWDOWN_ANI}-shiny" if shiny else SHOWDOWN_ANI
    return f"{ani_folder}/{slugs[0]}.gif"


app.jinja_env.globals["pokemon_sprite_url"] = pokemon_sprite_url
app.jinja_env.globals["enumerate"] = enumerate


SHOWDOWN_STATIC = "https://play.pokemonshowdown.com/sprites/gen5"
SHOWDOWN_DEX = "https://play.pokemonshowdown.com/sprites/dex"


def pokemon_static_sprite_url(name):
    """Return static PNG sprite URL for a Pokemon name.

    Priority:
    1. PokeAPI numeric sprite for canonical IDs (IDs < 10200; custom league megas
       use IDs >= 10200 which do not exist in PokeAPI's sprite repo)
    2. Base-form PokeAPI sprite for custom mega/primal forms (strips the mega suffix)
    3. Explicit overrides for megas whose base form has a non-obvious DB slug
    4. Showdown DEX sprite by slug (covers many custom megas from fan games)
    """
    # Megas whose base form uses a suffixed slug in pokemon_db rather than the bare name
    ov = _local_mega_sprite(name)
    if ov:
        return ov

    _MEGA_BASE_OVERRIDES = {
        "pyroar-mega":           "pyroar-male",
        "zygarde-mega":          "zygarde-50",
        "meowstic-mega":         "meowstic-male",
        "tatsugiri-droopy-mega": "tatsugiri-curly",
        "tatsugiri-stretchy-mega":"tatsugiri-curly",
    }

    slugs = _name_to_slug(name)
    primary_slug = slugs[0]

    # 1. Canonical PokeAPI IDs have sprites; custom league IDs (>= 10278) do not.
    # Real alternate-form IDs up to 10277 (e.g. Hisuian forms 10229-10244,
    # Enamorus-Therian 10249) are valid PokeAPI sprites.
    for slug in slugs:
        pid = _pokemon_id_map.get(slug)
        if pid and pid < 10278:
            return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pid}.png"

    # 2. Custom league ID (>= 10278) found — no PokeAPI sprite exists.
    # Go straight to Showdown DEX so the client-side onerror can handle a 404
    # gracefully (fading the image) rather than showing the wrong base-form sprite.
    if any(_pokemon_id_map.get(s, 0) >= 10278 for s in slugs):
        return f"{SHOWDOWN_DEX}/{primary_slug}.png"

    # 3. No recognized ID — try base form extraction.
    # Iterate ALL candidate slugs: the mega-suffixed slug (e.g. "meowstic-mega")
    # strips cleanly, whereas the naive slug ("mega-meowstic") has "mega" as a prefix.
    for candidate in slugs:
        stripped = re.sub(r'(-mega(-[xyz])?|-original-mega|-primal)$', '', candidate)
        if stripped != candidate:
            pid = _pokemon_id_map.get(stripped)
            if pid and pid < 10278:
                return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pid}.png"
            override = _MEGA_BASE_OVERRIDES.get(candidate)
            if override:
                pid = _pokemon_id_map.get(override)
                if pid and pid < 10278:
                    return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pid}.png"

    # 4. Showdown DEX (last resort for fully unrecognized forms)
    return f"{SHOWDOWN_DEX}/{primary_slug}.png"


def pokemon_pokedex_sprite_url(name):
    """Return a guaranteed-valid PokeAPI sprite URL for the pokedex page.

    Unlike pokemon_static_sprite_url (which routes custom-league megas through
    Showdown DEX, causing a second 404), this function resolves everything to a
    real PokeAPI URL server-side so no JS fallback chain is needed.

    - Canonical forms (ID < 10278): exact PokeAPI sprite (correct mega form).
    - Custom league megas (ID >= 10278): base-form PokeAPI sprite via suffix strip.
    - Handles both PokeAPI ("raichu-mega-x") and Showdown ("raichu-megax") slugs.
    """
    ov = _local_mega_sprite(name)
    if ov:
        return ov

    _OVERRIDES = {
        "meowstic-mega":          "meowstic-male",
        "pyroar-mega":            "pyroar-male",
        "zygarde-mega":           "zygarde-50",
        "tatsugiri-mega":         "tatsugiri-curly",
        "tatsugiri-droopy-mega":  "tatsugiri-curly",
        "tatsugiri-stretchy-mega":"tatsugiri-curly",
    }
    slugs = _name_to_slug(name)
    primary_slug = slugs[0]

    # 1. Canonical PokeAPI ID — return the exact form sprite
    for slug in slugs:
        pid = _pokemon_id_map.get(slug)
        if pid and pid < 10278:
            return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pid}.png"

    # 2. Custom league ID (>= 10278) — strip suffix to get base form
    for slug in slugs:
        override = _OVERRIDES.get(slug)
        if override:
            pid = _pokemon_id_map.get(override)
            if pid and pid < 10278:
                return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pid}.png"
        stripped = re.sub(r'(-mega(-[xyz])?|-mega[xyz]|-original-mega|-primal)$', '', slug)
        if stripped != slug:
            pid = _pokemon_id_map.get(stripped)
            if pid and pid < 10278:
                return f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pid}.png"

    # 3. Last resort: Showdown DEX
    return f"{SHOWDOWN_DEX}/{primary_slug}.png"


app.jinja_env.globals["pokemon_static_sprite_url"] = pokemon_static_sprite_url
app.jinja_env.globals["pokemon_pokedex_sprite_url"] = pokemon_pokedex_sprite_url


@app.template_filter("safejson")
def _safejson(s):
    """Make an already-serialized JSON string safe to embed inside <script>.

    Escapes the characters that could break out of the script context (a team
    or coach name containing '</script>', a quote, etc.) without re-encoding the
    JSON. The \\uXXXX escapes are valid inside JS string literals, so the data
    round-trips unchanged.
    """
    from markupsafe import Markup
    text = "" if s is None else str(s)
    for bad, esc in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                     (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(bad, esc)
    return Markup(text)


# ─── CSRF protection (dependency-free, session double-submit token) ───────────
def csrf_token():
    """Return this session's CSRF token, generating one on first use."""
    tok = session.get("_csrf_token")
    if not tok:
        tok = secrets.token_hex(32)
        session["_csrf_token"] = tok
    return tok


app.jinja_env.globals["csrf_token"] = csrf_token

_CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


@app.before_request
def _csrf_protect():
    csrf_token()  # ensure the session has a token to embed in pages
    if request.method in _CSRF_SAFE_METHODS:
        return None
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    if not sent or not secrets.compare_digest(str(sent), session.get("_csrf_token", "")):
        return ("CSRF token missing or invalid — please reload the page and try again.", 400)
    return None


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
                "SELECT id, team_name, coach_name, color, pool, logo_url FROM coaches ORDER BY pool, team_name"
            ).fetchall()
        return {"nav_coaches": [dict(c) for c in coaches]}
    except Exception:
        return {"nav_coaches": []}


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def hash_pw(password):
    """Salted, slow password hash (PBKDF2 via werkzeug). Replaces bare SHA-256."""
    return generate_password_hash(password)


def verify_pw(password, stored_hash):
    """Check a password against a stored hash.

    Supports both the new werkzeug format (contains '$' separators) and the
    legacy bare-SHA-256 hex so existing accounts keep working; legacy hashes are
    transparently upgraded on next successful login (see the login route).
    """
    if not stored_hash:
        return False
    if "$" in stored_hash:  # werkzeug format: method$salt$hash
        try:
            return check_password_hash(stored_hash, password)
        except Exception:
            return False
    # Legacy bare SHA-256 hex (constant-time compare)
    legacy = hashlib.sha256(password.encode()).hexdigest()
    return secrets.compare_digest(stored_hash, legacy)


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


_migrate_db()

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_setting(key, default=""):
    with get_db() as db:
        row = db.execute("SELECT value FROM league_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def post_discord(webhook_url, content):
    """Fire-and-forget POST to a Discord webhook. Silently ignores errors."""
    if not webhook_url:
        return
    try:
        payload = json.dumps({"content": content}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # Never let Discord errors break the app


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
            SELECT ms.pokemon_name, c.id as team_id, c.coach_name, c.team_name,
                   c.logo_url as team_logo,
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
            row = db.execute(
                "SELECT * FROM users WHERE username=?", (username,)
            ).fetchone()
            user = row if (row and verify_pw(password, row["password_hash"])) else None
            # Transparently upgrade legacy SHA-256 hashes to salted PBKDF2
            if user and "$" not in (user["password_hash"] or ""):
                db.execute("UPDATE users SET password_hash=? WHERE id=?",
                           (hash_pw(password), user["id"]))
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            session["coach_id"] = user["coach_id"]
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


# ─── Coach: My Matches ────────────────────────────────────────────────────────

@app.route("/my-matches", methods=["GET", "POST"])
@login_required
def my_matches():
    coach_id = session.get("coach_id")
    is_admin = session.get("role") == "admin"
    match_format = get_setting("match_format", "BO1")
    max_games = 3 if match_format == "BO3" else 1

    if request.method == "POST":
        action = request.form.get("action")
        match_id = request.form.get("match_id", type=int)

        # Verify the requesting user is in this match (or is admin)
        with get_db() as db:
            row = db.execute(
                "SELECT coach1_id, coach2_id FROM schedule WHERE id=?", (match_id,)
            ).fetchone()
        if not row:
            flash("Match not found.", "warning")
            return redirect(url_for("my_matches"))
        if not is_admin and coach_id not in (row["coach1_id"], row["coach2_id"]):
            flash("You are not in that match.", "warning")
            return redirect(url_for("my_matches"))

        if action == "submit_result":
            s1 = request.form.get("score1") or None
            s2 = request.form.get("score2") or None
            try:
                if s1 is not None:
                    s1 = float(s1)
                if s2 is not None:
                    s2 = float(s2)
            except (ValueError, TypeError):
                flash("Scores must be numbers.", "error")
                return redirect(url_for("my_matches"))
            with get_db() as db:
                db.execute(
                    "UPDATE schedule SET score1=?, score2=? WHERE id=?",
                    (s1, s2, match_id)
                )
                match_row = db.execute("""
                    SELECT s.week, c1.team_name as t1, c2.team_name as t2
                    FROM schedule s
                    JOIN coaches c1 ON s.coach1_id = c1.id
                    JOIN coaches c2 ON s.coach2_id = c2.id
                    WHERE s.id=?
                """, (match_id,)).fetchone()
                webhook = db.execute(
                    "SELECT value FROM league_settings WHERE key='discord_webhook_url'"
                ).fetchone()
            flash("Result submitted!", "success")
            if s1 is not None and s2 is not None and match_row and webhook and webhook["value"]:
                s1i, s2i = int(s1), int(s2)
                t1, t2 = match_row["t1"], match_row["t2"]
                winner = t1 if s1i > s2i else (t2 if s2i > s1i else None)
                result_line = (f"**{t1}** {s1i}–{s2i} **{t2}** → 🏆 **{winner}** wins!"
                               if winner else f"**{t1}** {s1i}–{s2i} **{t2}** → 🤝 Tie!")
                league = get_setting("league_name", "Pokemon Draft League")
                post_discord(webhook["value"],
                    f"📣 **{league}** — Week {match_row['week']} Result\n{result_line}")

        elif action == "save_replay":
            game_number = request.form.get("game_number", type=int, default=1)
            replay_url = request.form.get("replay_url", "").strip()
            winner_coach_id = request.form.get("winner_coach_id") or None
            with get_db() as db:
                existing = db.execute(
                    "SELECT id FROM match_games WHERE schedule_id=? AND game_number=?",
                    (match_id, game_number)
                ).fetchone()
                if existing:
                    db.execute(
                        "UPDATE match_games SET replay_url=?, winner_coach_id=? WHERE id=?",
                        (replay_url, winner_coach_id, existing["id"])
                    )
                else:
                    db.execute(
                        "INSERT INTO match_games (schedule_id, game_number, replay_url, winner_coach_id) VALUES (?,?,?,?)",
                        (match_id, game_number, replay_url, winner_coach_id)
                    )
            flash(f"Game {game_number} saved!", "success")

        elif action == "add_preview":
            pokemon_name = request.form.get("pokemon_name", "").strip()
            target_coach = request.form.get("coach_id", type=int) or coach_id
            if (is_admin or target_coach == coach_id) and pokemon_name:
                with get_db() as db:
                    count = db.execute(
                        "SELECT COUNT(*) FROM match_preview_lineups WHERE schedule_id=? AND coach_id=?",
                        (match_id, target_coach)
                    ).fetchone()[0]
                    if count < 6:
                        db.execute(
                            "INSERT OR IGNORE INTO match_preview_lineups (schedule_id, coach_id, pokemon_name) VALUES (?,?,?)",
                            (match_id, target_coach, pokemon_name)
                        )

        elif action == "remove_preview":
            preview_id = request.form.get("preview_id", type=int)
            with get_db() as db:
                row = db.execute(
                    "SELECT schedule_id, coach_id FROM match_preview_lineups WHERE id=?", (preview_id,)
                ).fetchone()
                if row and row["schedule_id"] == match_id and (is_admin or row["coach_id"] == coach_id):
                    db.execute("DELETE FROM match_preview_lineups WHERE id=?", (preview_id,))

        elif action == "add_lineup":
            game_number = request.form.get("game_number", type=int)
            target_coach = request.form.get("coach_id", type=int) or coach_id
            pokemon_name = request.form.get("pokemon_name", "").strip()
            if (is_admin or target_coach == coach_id) and pokemon_name and game_number:
                with get_db() as db:
                    existing_game = db.execute(
                        "SELECT id FROM match_games WHERE schedule_id=? AND game_number=?",
                        (match_id, game_number)
                    ).fetchone()
                    if existing_game:
                        game_id = existing_game["id"]
                    else:
                        cur = db.execute(
                            "INSERT INTO match_games (schedule_id, game_number) VALUES (?,?)",
                            (match_id, game_number)
                        )
                        game_id = cur.lastrowid
                    count = db.execute(
                        "SELECT COUNT(*) FROM match_lineups WHERE game_id=? AND coach_id=?",
                        (game_id, target_coach)
                    ).fetchone()[0]
                    if count < 4:
                        db.execute(
                            "INSERT OR IGNORE INTO match_lineups (game_id, coach_id, pokemon_name) VALUES (?,?,?)",
                            (game_id, target_coach, pokemon_name)
                        )

        elif action == "remove_lineup":
            lineup_id = request.form.get("lineup_id", type=int)
            with get_db() as db:
                row = db.execute(
                    "SELECT ml.coach_id, mg.schedule_id FROM match_lineups ml JOIN match_games mg ON ml.game_id=mg.id WHERE ml.id=?",
                    (lineup_id,)
                ).fetchone()
                if row and row["schedule_id"] == match_id and (is_admin or row["coach_id"] == coach_id):
                    db.execute("DELETE FROM match_lineups WHERE id=?", (lineup_id,))

        elif action == "save_game_stats":
            game_number = request.form.get("game_number", type=int)
            with get_db() as db:
                existing_game = db.execute(
                    "SELECT id FROM match_games WHERE schedule_id=? AND game_number=?",
                    (match_id, game_number)
                ).fetchone()
                if existing_game:
                    game_id = existing_game["id"]
                else:
                    cur = db.execute(
                        "INSERT INTO match_games (schedule_id, game_number) VALUES (?,?)",
                        (match_id, game_number)
                    )
                    game_id = cur.lastrowid
                if True:
                    i = 0
                    while True:
                        pname = request.form.get(f"stat_pokemon_{i}")
                        if pname is None:
                            break
                        c_id = request.form.get(f"stat_coach_{i}", type=int)
                        kills = float(request.form.get(f"stat_kills_{i}") or 0)
                        deaths = float(request.form.get(f"stat_deaths_{i}") or 0)
                        if is_admin or c_id == coach_id:
                            existing = db.execute(
                                "SELECT id FROM match_stats WHERE schedule_id=? AND game_id=? AND coach_id=? AND pokemon_name=?",
                                (match_id, game_id, c_id, pname)
                            ).fetchone()
                            if existing:
                                db.execute("UPDATE match_stats SET kills=?, deaths=? WHERE id=?",
                                           (kills, deaths, existing["id"]))
                            else:
                                db.execute(
                                    "INSERT INTO match_stats (schedule_id, game_id, coach_id, pokemon_name, kills, deaths) VALUES (?,?,?,?,?,?)",
                                    (match_id, game_id, c_id, pname, kills, deaths)
                                )
                        i += 1
            flash("Stats saved!", "success")

        return redirect(url_for("my_matches"))

    # GET — fetch this coach's matches (admin sees all)
    with get_db() as db:
        if is_admin:
            matches = db.execute("""
                SELECT s.*, c1.coach_name as c1_name, c1.team_name as c1_team, c1.id as c1_id,
                       c2.coach_name as c2_name, c2.team_name as c2_team, c2.id as c2_id
                FROM schedule s
                JOIN coaches c1 ON s.coach1_id = c1.id
                JOIN coaches c2 ON s.coach2_id = c2.id
                ORDER BY s.week DESC, s.id
            """).fetchall()
        else:
            matches = db.execute("""
                SELECT s.*, c1.coach_name as c1_name, c1.team_name as c1_team, c1.id as c1_id,
                       c2.coach_name as c2_name, c2.team_name as c2_team, c2.id as c2_id
                FROM schedule s
                JOIN coaches c1 ON s.coach1_id = c1.id
                JOIN coaches c2 ON s.coach2_id = c2.id
                WHERE s.coach1_id=? OR s.coach2_id=?
                ORDER BY s.week DESC, s.id
            """, (coach_id, coach_id)).fetchall()
        matches = [dict(m) for m in matches]

        match_ids = [m["id"] for m in matches]

        # Fetch games/replays for each match
        games_by_match = {}
        if match_ids:
            placeholders = ",".join("?" * len(match_ids))
            all_games = db.execute(
                f"SELECT * FROM match_games WHERE schedule_id IN ({placeholders}) ORDER BY game_number",
                match_ids
            ).fetchall()
            for g in all_games:
                games_by_match.setdefault(g["schedule_id"], []).append(dict(g))

        # Fetch team preview lineups (6 per coach per match)
        preview_by_match = {}
        if match_ids:
            ph = ",".join("?" * len(match_ids))
            for ln in db.execute(
                f"SELECT * FROM match_preview_lineups WHERE schedule_id IN ({ph})", match_ids
            ).fetchall():
                preview_by_match.setdefault(ln["schedule_id"], {}).setdefault(ln["coach_id"], []).append(dict(ln))

        # Fetch per-game lineups and stats
        all_game_ids = [g["id"] for glist in games_by_match.values() for g in glist]
        lineups_by_game = {}
        stats_by_game = {}
        if all_game_ids:
            ph = ",".join("?" * len(all_game_ids))
            for ln in db.execute(
                f"SELECT * FROM match_lineups WHERE game_id IN ({ph})", all_game_ids
            ).fetchall():
                lineups_by_game.setdefault(ln["game_id"], {}).setdefault(ln["coach_id"], []).append(dict(ln))
            for s in db.execute(
                f"SELECT * FROM match_stats WHERE game_id IN ({ph})", all_game_ids
            ).fetchall():
                stats_by_game.setdefault(s["game_id"], {}).setdefault(s["coach_id"], []).append(dict(s))

        # Fetch rosters for all coaches in these matches
        all_coach_ids = list({cid for m in matches for cid in (m["c1_id"], m["c2_id"])})
        rosters_by_coach = {}
        if all_coach_ids:
            ph = ",".join("?" * len(all_coach_ids))
            for r in db.execute(
                f"SELECT coach_id, pokemon_name FROM pokemon_roster WHERE coach_id IN ({ph}) ORDER BY pokemon_name",
                all_coach_ids
            ).fetchall():
                rosters_by_coach.setdefault(r["coach_id"], []).append(r["pokemon_name"])

    for m in matches:
        games = games_by_match.get(m["id"], [])
        preview = preview_by_match.get(m["id"], {})
        for g in games:
            g["lineups"] = lineups_by_game.get(g["id"], {})
            g["stats"] = stats_by_game.get(g["id"], {})
        m["games"] = games
        m["preview"] = preview
        m["c1_roster"] = rosters_by_coach.get(m["c1_id"], [])
        m["c2_roster"] = rosters_by_coach.get(m["c2_id"], [])
        m["c1_preview"] = preview.get(m["c1_id"], [])
        m["c2_preview"] = preview.get(m["c2_id"], [])
        has_result = m["score1"] is not None and m["score2"] is not None and (m["score1"] > 0 or m["score2"] > 0)
        m["has_result"] = has_result

    return render_template("my_matches.html",
                           matches=matches,
                           max_games=max_games,
                           match_format=match_format,
                           coach_id=coach_id,
                           is_admin=is_admin,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


# ─── Public Routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Esports-style home / landing page."""
    league_name = get_setting("league_name", "Pokemon Draft League")
    season = get_setting("season", "")
    with get_db() as db:
        total_teams = db.execute("SELECT COUNT(*) FROM coaches").fetchone()[0]
        weeks = db.execute("SELECT DISTINCT week FROM schedule ORDER BY week").fetchall()
        total_matches = db.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
        completed_matches = db.execute(
            "SELECT COUNT(*) FROM schedule WHERE score1 IS NOT NULL AND score2 IS NOT NULL"
        ).fetchone()[0]
        current_week_row = db.execute("SELECT value FROM league_settings WHERE key='current_week'").fetchone()
        current_week = int(current_week_row["value"]) if current_week_row else (weeks[-1]["week"] if weeks else 1)
        # Recent 6 results
        recent_rows = db.execute("""
            SELECT s.week, s.pool, s.score1, s.score2,
                   c1.team_name as t1, c1.color as c1_color, c1.logo_url as c1_logo, c1.id as c1_id,
                   c2.team_name as t2, c2.color as c2_color, c2.logo_url as c2_logo, c2.id as c2_id
            FROM schedule s
            JOIN coaches c1 ON s.coach1_id = c1.id
            JOIN coaches c2 ON s.coach2_id = c2.id
            WHERE s.score1 IS NOT NULL AND s.score2 IS NOT NULL
            ORDER BY s.week DESC, s.id DESC
            LIMIT 6
        """).fetchall()
    all_weeks = [w["week"] for w in weeks]
    total_weeks = len(all_weeks)
    completed_weeks = 0
    with get_db() as db:
        for w in all_weeks:
            wk_total = db.execute("SELECT COUNT(*) FROM schedule WHERE week=?", (w,)).fetchone()[0]
            wk_done = db.execute(
                "SELECT COUNT(*) FROM schedule WHERE week=? AND score1 IS NOT NULL AND score2 IS NOT NULL", (w,)
            ).fetchone()[0]
            if wk_total > 0 and wk_total == wk_done:
                completed_weeks += 1
    # Top 3 overall for the leaderboard strip
    standings_all = get_standings(None)
    top3 = standings_all[:3]
    recent_results = [dict(r) for r in recent_rows]

    # Hot team — longest current win streak
    hot_team = None
    max_streak = 0
    with get_db() as db:
        for row in standings_all:
            cid = row["coach"]["id"]
            results = db.execute("""
                SELECT score1, score2, coach1_id FROM schedule
                WHERE (coach1_id=? OR coach2_id=?) AND score1 IS NOT NULL AND score2 IS NOT NULL
                ORDER BY week DESC
            """, (cid, cid)).fetchall()
            streak = 0
            for r in results:
                my_s  = r["score1"] if r["coach1_id"] == cid else r["score2"]
                opp_s = r["score2"] if r["coach1_id"] == cid else r["score1"]
                if my_s > opp_s:
                    streak += 1
                else:
                    break
            if streak > max_streak:
                max_streak = streak
                hot_team = {"coach": row["coach"], "streak": streak,
                            "W": row["W"], "L": row["L"], "T": row["T"]}

    # Pick'em top 3 leaders (all-time)
    with get_db() as db:
        try:
            pickems_rows = db.execute("""
                SELECT pv.voter_name,
                       SUM(CASE WHEN (s.score1 > s.score2 AND pv.picked_coach_id = s.coach1_id)
                                  OR (s.score2 > s.score1 AND pv.picked_coach_id = s.coach2_id)
                                THEN 1 ELSE 0 END) as correct,
                       COUNT(*) as total_picks
                FROM pickem_votes pv
                JOIN schedule s ON pv.match_id = s.id
                WHERE s.score1 IS NOT NULL AND s.score2 IS NOT NULL AND s.score1 != s.score2
                GROUP BY pv.voter_name
                HAVING total_picks > 0
                ORDER BY correct DESC, total_picks ASC
                LIMIT 3
            """).fetchall()
            pickems_top3 = [dict(r) for r in pickems_rows]
        except Exception:
            pickems_top3 = []

    return render_template("home.html",
                           league_name=league_name,
                           season=season,
                           total_teams=total_teams,
                           total_weeks=total_weeks,
                           completed_weeks=completed_weeks,
                           current_week=current_week,
                           total_matches=total_matches,
                           completed_matches=completed_matches,
                           recent_results=recent_results,
                           top3=top3,
                           hot_team=hot_team,
                           pickems_top3=pickems_top3)


@app.route("/standings")
def standings():
    league_name = get_setting("league_name", "Pokemon Draft League")
    standings_a = get_standings("A")
    standings_b = get_standings("B")
    standings_all = get_standings(None)
    with get_db() as db:
        weeks = db.execute("SELECT DISTINCT week FROM schedule ORDER BY week").fetchall()
        total_matches = db.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
        completed_matches = db.execute(
            "SELECT COUNT(*) FROM schedule WHERE score1 IS NOT NULL AND score2 IS NOT NULL"
        ).fetchone()[0]
        current_week_row = db.execute("SELECT value FROM league_settings WHERE key='current_week'").fetchone()
    all_weeks = [w["week"] for w in weeks]
    total_weeks = len(all_weeks)
    current_week = int(current_week_row["value"]) if current_week_row else (all_weeks[-1] if all_weeks else 1)
    completed_weeks = 0
    with get_db() as db:
        for w in all_weeks:
            wk_total = db.execute("SELECT COUNT(*) FROM schedule WHERE week=?", (w,)).fetchone()[0]
            wk_done = db.execute(
                "SELECT COUNT(*) FROM schedule WHERE week=? AND score1 IS NOT NULL AND score2 IS NOT NULL", (w,)
            ).fetchone()[0]
            if wk_total > 0 and wk_total == wk_done:
                completed_weeks += 1
    import json as _json
    def _row_json(r):
        return {
            "coach": {
                "id": r["coach"]["id"],
                "team_name": r["coach"]["team_name"],
                "coach_name": r["coach"]["coach_name"],
                "pool": r["coach"].get("pool", ""),
                "logo_url": r["coach"].get("logo_url", "") or "",
                "color": r["coach"].get("color", "") or "",
                "is_champ": bool(r["coach"].get("is_defending_champ", 0)),
            },
            "W": r["W"], "L": r["L"], "T": r["T"],
            "diff": int(round(float(r["diff"]))),
            "rank": r["rank"],
            "form": [r["weeks"].get(w, "") for w in all_weeks],
        }
    standings_all_json = _json.dumps([_row_json(r) for r in standings_all])
    standings_a_json   = _json.dumps([_row_json(r) for r in standings_a])
    standings_b_json   = _json.dumps([_row_json(r) for r in standings_b])
    return render_template("index.html",
                           league_name=league_name,
                           standings_a=standings_a,
                           standings_b=standings_b,
                           standings_all=standings_all,
                           standings_all_json=standings_all_json,
                           standings_a_json=standings_a_json,
                           standings_b_json=standings_b_json,
                           all_weeks=all_weeks,
                           total_weeks=total_weeks,
                           completed_weeks=completed_weeks,
                           current_week=current_week,
                           total_matches=total_matches,
                           completed_matches=completed_matches)


def _list_seasons():
    """Return list of all archived seasons sorted by season_num desc."""
    with get_db() as db:
        rows = db.execute(
            "SELECT id, name, season_num FROM seasons ORDER BY season_num DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def _build_stats_data(season_id=None):
    """Aggregate stats for the Stats & Meta Hub. season_id=None → live tables; int → archive."""
    TYPE_COLORS = {
        "Normal": "#a3a3a3", "Fire": "#ff6830", "Water": "#6390f0",
        "Electric": "#f7d02c", "Grass": "#7ac74c", "Ice": "#96d9d6",
        "Fighting": "#ff7a59", "Poison": "#a33ea1", "Ground": "#e2bf65",
        "Flying": "#89aae4", "Psychic": "#f95587", "Bug": "#a6b91a",
        "Rock": "#b6a136", "Ghost": "#735797", "Dragon": "#7b6cff",
        "Dark": "#705746", "Steel": "#a7b3c4", "Fairy": "#ff8fd0",
    }
    with get_db() as db:
        # ── always need live pokedex for type/speed fallback ─────────────────
        pdex_rows = db.execute(
            "SELECT display_name, type1, type2, spe FROM pokedex"
        ).fetchall()
        pdex_map = {r["display_name"].lower().strip(): dict(r) for r in pdex_rows}

        if season_id is not None:
            # ── load from archive JSON ────────────────────────────────────────
            row = db.execute(
                "SELECT data_json, name, season_num FROM seasons WHERE id=?", (season_id,)
            ).fetchone()
            if not row:
                return None
            sd = json.loads(row["data_json"])
            season_label = row["name"]
            coaches_map = {c["id"]: c for c in sd.get("coaches", [])}
            # Enrich archived coaches with live logo/color from the coaches table
            live_coaches = db.execute(
                "SELECT coach_name, team_name, logo_url, color FROM coaches"
            ).fetchall()
            live_by_coach = {r["coach_name"].lower().strip(): dict(r) for r in live_coaches}
            live_by_team  = {r["team_name"].lower().strip(): dict(r) for r in live_coaches}
            for c in coaches_map.values():
                live = (live_by_coach.get(c.get("coach_name", "").lower().strip())
                        or live_by_team.get(c.get("team_name", "").lower().strip())
                        or {})
                if live.get("logo_url"):
                    c["logo_url"] = live["logo_url"]
                if live.get("color") and live["color"] != "#888":
                    c["color"] = live["color"]
            roster_rows = sd.get("pokemon_roster", [])
            sched_rows = [
                s for s in sd.get("schedule", [])
                if s.get("score1") is not None and s.get("score2") is not None
            ]
            ms_raw = sd.get("match_stats", [])
            dt_map = {
                r["name"].lower().strip(): r
                for r in sd.get("draft_tiers", [])
                if r.get("name")
            }
        else:
            # ── load from live tables ────────────────────────────────────────
            season_label = get_setting("season", "Current Season")
            coaches_raw = db.execute("SELECT * FROM coaches ORDER BY id").fetchall()
            if coaches_raw:
                coaches_map = {c["id"]: dict(c) for c in coaches_raw}
            else:
                season_row = db.execute(
                    "SELECT data_json FROM seasons ORDER BY season_num DESC LIMIT 1"
                ).fetchone()
                if season_row:
                    sd = json.loads(season_row["data_json"])
                    coaches_map = {c["id"]: c for c in sd.get("coaches", [])}
                else:
                    coaches_map = {}
            roster_rows = [dict(r) for r in db.execute("SELECT * FROM pokemon_roster").fetchall()]
            sched_rows = [dict(r) for r in db.execute(
                "SELECT * FROM schedule WHERE score1 IS NOT NULL AND score2 IS NOT NULL"
            ).fetchall()]
            ms_raw = [dict(r) for r in db.execute(
                "SELECT coach_id, pokemon_name, SUM(kills) as kills, SUM(deaths) as deaths "
                "FROM match_stats GROUP BY coach_id, pokemon_name"
            ).fetchall()]
            dt_rows = db.execute(
                "SELECT name, type1, type2, spe, points FROM draft_tiers"
            ).fetchall()
            dt_map = {r["name"].lower().strip(): dict(r) for r in dt_rows}

        def _types(name):
            k = name.lower().strip()
            d = dt_map.get(k, {})
            if d.get("type1"):
                return [t for t in [d.get("type1"), d.get("type2")] if t]
            p = pdex_map.get(k, {})
            return [t for t in [p.get("type1"), p.get("type2")] if t]

        def _spe(name):
            k = name.lower().strip()
            d = dt_map.get(k, {})
            if d.get("spe"):
                return int(d["spe"])
            p = pdex_map.get(k, {})
            return int(p["spe"]) if p.get("spe") else 0

        # aggregate per-pokemon kills/deaths (raw ms_raw may be per-game or pre-aggregated)
        stats_map = {}
        for r in ms_raw:
            key = (r["coach_id"], r["pokemon_name"].lower())
            if key not in stats_map:
                stats_map[key] = {"kills": 0.0, "deaths": 0.0}
            stats_map[key]["kills"] += float(r.get("kills") or 0)
            stats_map[key]["deaths"] += float(r.get("deaths") or 0)

        mon_dex = []
        for r in roster_rows:
            cid = r["coach_id"]
            name = r["pokemon_name"]
            coach = coaches_map.get(cid, {})
            st = stats_map.get((cid, name.lower()), {"kills": 0, "deaths": 0})
            kills = float(st.get("kills") or 0)
            deaths = float(st.get("deaths") or 0)
            types = _types(name)
            spe = _spe(name)
            cost = int(r["points"] or 0)
            primary_type = types[0] if types else "Normal"
            orb_color = TYPE_COLORS.get(primary_type, "#a3a3a3")
            glyph = name[:2].upper()
            sprite = pokemon_static_sprite_url(name)
            kpp = round(kills / cost, 2) if cost > 0 else 0.0
            mon_dex.append({
                "id": f"{cid}_{name}",
                "name": name,
                "types": types,
                "glyph": glyph,
                "sprite": sprite,
                "orb_color": orb_color,
                "kills": kills,
                "deaths": deaths,
                "diff": round(kills - deaths, 1),
                "spe": spe,
                "cost": cost,
                "kpp": kpp,
                "team": {
                    "id": cid,
                    "name": coach.get("team_name", f"Team {cid}"),
                    "logo": coach.get("logo_url", ""),
                    "color": coach.get("color", "#888"),
                    "pool": coach.get("pool", "A"),
                },
            })

        total_kos = sum(m["kills"] for m in mon_dex)

        # TYPE_META
        type_kos = {}
        type_spend = {}
        type_mons_set = {}
        for m in mon_dex:
            for t in m["types"]:
                type_kos[t] = type_kos.get(t, 0) + m["kills"]
                type_spend[t] = type_spend.get(t, 0) + m["cost"]
                type_mons_set.setdefault(t, set()).add(m["name"])
        type_meta = []
        for t, kos in sorted(type_kos.items(), key=lambda x: -x[1]):
            share = round(kos / total_kos * 100, 1) if total_kos else 0
            type_meta.append({
                "type": t, "kos": round(kos, 1),
                "used": len(type_mons_set[t]),
                "spend": round(type_spend[t]),
                "share": share,
                "color": TYPE_COLORS.get(t, "#888"),
            })

        # TYPE_VOE
        total_spend_pts = sum(type_spend.values())
        type_voe = []
        for tm in type_meta:
            t = tm["type"]
            ko_s = (type_kos[t] / total_kos * 100) if total_kos else 0
            sp_s = (type_spend[t] / total_spend_pts * 100) if total_spend_pts else 0
            delta = round(ko_s - sp_s, 1)
            type_voe.append({
                "type": t, "color": TYPE_COLORS.get(t, "#888"),
                "koShare": round(ko_s, 1), "spendShare": round(sp_s, 1),
                "delta": delta,
            })
        type_voe.sort(key=lambda x: -x["delta"])
        voe_max = max((abs(t["delta"]) for t in type_voe), default=1) or 1

        # FIREPOWER
        fp_data = {}
        for r in sched_rows:
            for cid, mine, opp in [
                (r["coach1_id"], float(r["score1"]), float(r["score2"])),
                (r["coach2_id"], float(r["score2"]), float(r["score1"])),
            ]:
                d = fp_data.setdefault(cid, {"gf": 0, "ga": 0, "w": 0, "l": 0, "gp": 0})
                d["gf"] += mine
                d["ga"] += opp
                d["gp"] += 1
                if mine > opp:
                    d["w"] += 1
                elif opp > mine:
                    d["l"] += 1
        firepower = []
        for cid, coach in coaches_map.items():
            d = fp_data.get(int(cid) if isinstance(cid, str) else cid,
                            {"gf": 0, "ga": 0, "w": 0, "l": 0, "gp": 0})
            firepower.append({
                "team": {
                    "id": cid,
                    "name": coach.get("team_name", f"Team {cid}"),
                    "logo": coach.get("logo_url", ""),
                    "color": coach.get("color", "#888"),
                    "pool": coach.get("pool", "A"),
                },
                "gp": d["gp"], "w": d["w"], "l": d["l"],
                "gf": round(d["gf"]), "ga": round(d["ga"]),
                "diff": round(d["gf"] - d["ga"]),
                "kos": round(sum(m["kills"] for m in mon_dex if m["team"]["id"] == cid)),
            })
        firepower.sort(key=lambda x: -x["gf"])
        fp_max_gf = max((f["gf"] for f in firepower), default=1) or 1

        # DRAFT_ECON
        TIER_COLORS = {
            "Uber 1": "#ffc94d", "Uber 2": "#e8a82a",
            "Mega": "#ff7e9d",
            "Tier 1": "#5a9bff", "Tier 2": "#b07dff",
            "Tier 3": "#3dd9c2", "Tier 4": "#7ddc6a", "Tier 5": "#9a9aa8",
        }
        TIER_ORDER = ["Uber 1", "Uber 2", "Mega", "Tier 1", "Tier 2", "Tier 3", "Tier 4", "Tier 5"]
        tier_cnt = {}
        for r in roster_rows:
            tier = r.get("tier") if isinstance(r, dict) else r["tier"]
            is_fp = r.get("is_free_pick", 0) if isinstance(r, dict) else r["is_free_pick"]
            if not is_fp and tier and tier != "Free Pick":
                tier_cnt[tier] = tier_cnt.get(tier, 0) + 1
        bands = []
        for tier in TIER_ORDER:
            if tier in tier_cnt:
                bands.append({
                    "band": tier, "count": tier_cnt[tier],
                    "color": TIER_COLORS.get(tier, "#666"),
                })
        total_drafted = sum(b["count"] for b in bands)

        non_free = [m for m in mon_dex if 0 < m["cost"] < 90]
        avg_cost = round(sum(m["cost"] for m in non_free) / len(non_free), 1) if non_free else 0
        priciest = max(non_free, key=lambda m: m["cost"]) if non_free else None
        has_kills = [m for m in non_free if m["kills"] > 0]
        value_pick = max(has_kills, key=lambda m: m["kpp"]) if has_kills else None

        # SPEED_TIERS
        speed_bands = [
            ("120+", 120, 999, "FASTEST — outspeeds most"),
            ("100–119", 100, 119, "TOP SPEED — speed tie bracket"),
            ("80–99", 80, 99, "MID TIER — fringe speed"),
            ("50–79", 50, 79, "LOW TIER — needs TR / trick"),
            ("<50", 0, 49, "TRICK ROOM USERS"),
        ]
        speed_tiers = []
        for label, lo, hi, hint in speed_bands:
            mons_in = sorted(
                [m for m in mon_dex if lo <= m["spe"] <= hi],
                key=lambda m: -m["spe"]
            )
            speed_tiers.append({"label": label, "hint": hint, "count": len(mons_in), "mons": mons_in})

        # ARCHETYPES
        team_arch = {}
        for m in mon_dex:
            cid = m["team"]["id"]
            d = team_arch.setdefault(cid, {"team": m["team"], "mons": [], "kos": 0.0})
            d["mons"].append(m)
            d["kos"] += m["kills"]
        # TEAM_MVPS: highest-KO pokemon per team
        team_mvps = []
        for cid, coach in coaches_map.items():
            team_mons = [m for m in mon_dex if m["team"]["id"] == cid]
            if not team_mons:
                continue
            mvp = max(team_mons, key=lambda m: m["kills"])
            team_mvps.append({
                "team": {
                    "id": cid,
                    "name": coach.get("team_name", f"Team {cid}"),
                    "logo": coach.get("logo_url", ""),
                    "color": coach.get("color", "#888"),
                    "pool": coach.get("pool", "A"),
                },
                "mvp": mvp,
            })
        team_mvps.sort(key=lambda x: -x["mvp"]["kills"])

        archetypes = []
        arch_spe_max = 1
        for cid, d in team_arch.items():
            mons = d["mons"]
            if not mons:
                continue
            avg_spe = round(sum(m["spe"] for m in mons) / len(mons))
            avg_c = round(sum(m["cost"] for m in mons) / len(mons), 1)
            kos = round(d["kos"], 1)
            if avg_spe >= 112:
                arch = "Hyper Offense"
            elif avg_spe >= 88:
                arch = "Offense"
            elif avg_spe >= 58:
                arch = "Balanced"
            else:
                arch = "Trick Room"
            archetypes.append({
                "team": coaches_map.get(cid, {"id": cid, "team_name": f"Team {cid}",
                                              "logo_url": "", "color": "#888", "pool": "A"}),
                "n": len(mons), "kos": kos, "avgSpe": avg_spe, "avgCost": avg_c,
                "arch": arch, "topHeavy": avg_c >= 15.5,
            })
            arch_spe_max = max(arch_spe_max, avg_spe)
        archetypes.sort(key=lambda a: -a["kos"])

        # VALUE_INDEX
        eligible = sorted(
            [m for m in mon_dex if 0 < m["cost"] < 90],
            key=lambda m: -m["kpp"]
        )
        bargains = eligible[:6]
        busts = sorted(
            [m for m in eligible if m["cost"] >= 13],
            key=lambda m: m["kpp"]
        )[:4]
        max_kpp = max((m["kpp"] for m in eligible), default=1) or 1

        # SURVIVORS
        for m in mon_dex:
            m["ratio"] = round(m["kills"] / max(1.0, m["deaths"]), 2)
        survivors = sorted(mon_dex, key=lambda m: -m["ratio"])[:8]
        surv_max = max((m["ratio"] for m in survivors), default=1) or 1

        # QUADRANT
        all_kos = [m["kills"] for m in mon_dex]
        all_deaths = [m["deaths"] for m in mon_dex]
        mean_k = sum(all_kos) / len(all_kos) if all_kos else 0
        mean_f = sum(all_deaths) / len(all_deaths) if all_deaths else 0
        max_k = max(all_kos) if all_kos else 1
        max_f = max(all_deaths) if all_deaths else 1
        max_k = max_k or 1
        max_f = max_f or 1
        quad_counts = {"MVP": 0, "CANNON": 0, "WALL": 0, "LIABILITY": 0}
        quad_points = []
        for m in mon_dex:
            if m["kills"] >= mean_k and m["deaths"] <= mean_f:
                q = "MVP"
            elif m["kills"] >= mean_k:
                q = "CANNON"
            elif m["deaths"] <= mean_f:
                q = "WALL"
            else:
                q = "LIABILITY"
            quad_counts[q] += 1
            quad_points.append({**m, "quad": q})
        quadrant = {
            "meanK": round(mean_k, 2), "meanF": round(mean_f, 2),
            "maxK": round(max_k), "maxF": round(max_f),
            "points": quad_points, "counts": quad_counts,
        }

        # RECORDS
        played = len(sched_rows)
        fp_by_id = {cid: d["gf"] for cid, d in fp_data.items()}
        sweeps = one_point = ties = 0
        sweep_ex = one_point_ex = highest_ex = blowout = upset = None
        highest_total = blowout_diff = upset_score = 0
        for r in sched_rows:
            s1, s2 = float(r["score1"]), float(r["score2"])
            total = s1 + s2
            diff = abs(s1 - s2)
            c1 = coaches_map.get(r["coach1_id"], {"team_name": "?"})
            c2 = coaches_map.get(r["coach2_id"], {"team_name": "?"})
            win_c = c1 if s1 > s2 else c2
            los_c = c2 if s1 > s2 else c1
            win_s, los_s = (int(max(s1, s2)), int(min(s1, s2)))
            if s1 == 0 or s2 == 0:
                sweeps += 1
                if sweep_ex is None:
                    sweep_ex = {"a": {"name": win_c.get("team_name", "?")},
                                "b": {"name": los_c.get("team_name", "?")},
                                "scoreA": win_s, "scoreB": los_s}
            if diff == 1:
                one_point += 1
                if one_point_ex is None:
                    one_point_ex = {"a": {"name": win_c.get("team_name", "?")},
                                    "b": {"name": los_c.get("team_name", "?")},
                                    "scoreA": win_s, "scoreB": los_s}
            if s1 == s2:
                ties += 1
            if total > highest_total:
                highest_total = int(total)
                highest_ex = {"a": {"name": win_c.get("team_name", "?")},
                              "b": {"name": los_c.get("team_name", "?")},
                              "scoreA": win_s, "scoreB": los_s}
            if diff > blowout_diff:
                blowout_diff = diff
                blowout = {"match": {"a": {"name": win_c.get("team_name", "?")},
                                     "b": {"name": los_c.get("team_name", "?")},
                                     "scoreA": win_s, "scoreB": los_s}}
            gf1 = fp_by_id.get(r["coach1_id"], 0)
            gf2 = fp_by_id.get(r["coach2_id"], 0)
            if s1 > s2 and gf2 > gf1 and (gf2 - gf1) > upset_score:
                upset_score = gf2 - gf1
                upset = {"week": r["week"], "match": {
                    "a": {"name": c2.get("team_name", "?")},
                    "b": {"name": c1.get("team_name", "?")},
                    "scoreA": int(s1), "scoreB": int(s2)}}
            elif s2 > s1 and gf1 > gf2 and (gf1 - gf2) > upset_score:
                upset_score = gf1 - gf2
                upset = {"week": r["week"], "match": {
                    "a": {"name": c1.get("team_name", "?")},
                    "b": {"name": c2.get("team_name", "?")},
                    "scoreA": int(s2), "scoreB": int(s1)}}

        records = {
            "played": played, "sweeps": sweeps, "sweepEx": sweep_ex,
            "onePoint": one_point, "onePointEx": one_point_ex, "ties": ties,
            "highestTotal": highest_total, "highest": highest_ex,
            "blowout": blowout, "upset": upset,
        }

    return {
        "season": season_label,
        "season_id": season_id,
        "mon_dex": mon_dex,
        "total_kos": round(total_kos),
        "type_meta": type_meta,
        "type_voe": type_voe,
        "voe_max": voe_max,
        "firepower": firepower,
        "fp_max_gf": fp_max_gf,
        "draft_econ": {"totalPool": 650, "drafted": total_drafted, "bands": bands},
        "draft_stats": {
            "avgCost": avg_cost,
            "priciest": {"name": priciest["name"], "cost": priciest["cost"]} if priciest else None,
            "valuePick": {
                "name": value_pick["name"],
                "kills": value_pick["kills"],
                "cost": value_pick["cost"],
            } if value_pick else None,
        },
        "speed_tiers": speed_tiers,
        "team_mvps": team_mvps,
        "archetypes": archetypes,
        "arch_spe_max": arch_spe_max,
        "value_index": {"bargains": bargains, "busts": busts, "maxKpp": max_kpp},
        "survivors": survivors,
        "surv_max": surv_max,
        "quadrant": quadrant,
        "records": records,
    }


@app.route("/stats")
def stats():
    import traceback as _tb
    try:
        season_id = request.args.get("season", type=int)
        data = _build_stats_data(season_id)
        if data is None:
            return "Season not found", 404
        stats_json = json.dumps(data)
        seasons = _list_seasons()
    except Exception:
        app.logger.error("page render failed:\n%s", _tb.format_exc())
        return "Sorry — something went wrong loading this page.", 500
    try:
        return render_template(
            "stats.html",
            stats=data,
            seasons=seasons,
            stats_json=stats_json,
            league_name=get_setting("league_name", "Pokemon Draft League"),
        )
    except Exception:
        app.logger.error("page render failed:\n%s", _tb.format_exc())
        return "Sorry — something went wrong loading this page.", 500


@app.route("/history")
def history():
    """Coach career stats across all archived seasons."""
    import traceback as _tb
    try:
        seasons = _list_seasons()

        # Build per-coach career record from all archived seasons
        # key = coach_name (case-insensitive), value = list of season records
        career = {}  # coach_name.lower() → {coach_name, seasons: []}

        for s in seasons:
            with get_db() as db:
                row = db.execute(
                    "SELECT data_json, name, season_num FROM seasons WHERE id=?", (s["id"],)
                ).fetchone()
            if not row:
                continue
            sd = json.loads(row["data_json"])
            season_label = row["name"]
            season_num = row["season_num"] or 0

            coaches = {c["id"]: c for c in sd.get("coaches", [])}
            sched = [r for r in sd.get("schedule", [])
                     if r.get("score1") is not None and r.get("score2") is not None]
            ms = sd.get("match_stats", [])

            # W/L per coach
            wl = {}
            for m in sched:
                c1, c2 = m["coach1_id"], m["coach2_id"]
                s1, s2 = float(m["score1"]), float(m["score2"])
                for cid in (c1, c2):
                    wl.setdefault(cid, {"w": 0, "l": 0, "gf": 0, "ga": 0, "gp": 0})
                wl[c1]["gf"] += s1; wl[c1]["ga"] += s2; wl[c1]["gp"] += 1
                wl[c2]["gf"] += s2; wl[c2]["ga"] += s1; wl[c2]["gp"] += 1
                if s1 > s2:
                    wl[c1]["w"] += 1; wl[c2]["l"] += 1
                elif s2 > s1:
                    wl[c2]["w"] += 1; wl[c1]["l"] += 1

            # Per-coach total KOs from match_stats
            ko_agg = {}
            for r in ms:
                cid = r["coach_id"]
                ko_agg[cid] = ko_agg.get(cid, 0) + float(r.get("kills") or 0)

            # Rank coaches by W, then KO diff
            all_cids = list(coaches.keys())
            ranked = sorted(
                all_cids,
                key=lambda cid: (
                    -wl.get(cid, {}).get("w", 0),
                    -(wl.get(cid, {}).get("gf", 0) - wl.get(cid, {}).get("ga", 0)),
                )
            )
            rank_map = {cid: i + 1 for i, cid in enumerate(ranked)}

            for cid, coach in coaches.items():
                cname = coach.get("coach_name", "")
                key = cname.lower().strip()
                if not key:
                    continue
                if key not in career:
                    career[key] = {
                        "coach_name": cname,
                        "seasons": [],
                        "total_w": 0, "total_l": 0,
                        "total_kos": 0.0,
                        "team_names": [],
                    }
                rec = wl.get(cid, {"w": 0, "l": 0, "gf": 0, "ga": 0, "gp": 0})
                kos = round(ko_agg.get(cid, 0), 1)
                diff = round(rec["gf"] - rec["ga"], 1)
                career[key]["seasons"].append({
                    "season_id": s["id"],
                    "season_name": season_label,
                    "season_num": season_num,
                    "team_name": coach.get("team_name", ""),
                    "color": coach.get("color", "#888"),
                    "logo": coach.get("logo_url", ""),
                    "w": rec["w"], "l": rec["l"],
                    "gf": round(rec["gf"], 1), "ga": round(rec["ga"], 1),
                    "diff": diff,
                    "kos": kos,
                    "rank": rank_map.get(cid, 0),
                    "gp": rec["gp"],
                })
                career[key]["total_w"] += rec["w"]
                career[key]["total_l"] += rec["l"]
                career[key]["total_kos"] += kos
                if coach.get("team_name") and coach["team_name"] not in career[key]["team_names"]:
                    career[key]["team_names"].append(coach["team_name"])

        # Pull logo/color from live coaches table to override archive blanks
        with get_db() as db:
            live_coaches = db.execute(
                "SELECT coach_name, team_name, logo_url, color FROM coaches"
            ).fetchall()
        live_by_coach = {
            r["coach_name"].lower().strip(): {"logo": r["logo_url"] or "", "color": r["color"] or "#888"}
            for r in live_coaches
        }
        live_by_team = {
            r["team_name"].lower().strip(): {"logo": r["logo_url"] or "", "color": r["color"] or "#888"}
            for r in live_coaches
        }

        # Sort seasons within each coach by season_num desc
        coaches_list = []
        for c in career.values():
            c["seasons"].sort(key=lambda x: -x["season_num"])
            c["total_kos"] = round(c["total_kos"], 1)
            c["seasons_count"] = len(c["seasons"])
            # Stamp the latest season with live logo/color (match by name, then team name)
            if c["seasons"]:
                latest_team = c["seasons"][0].get("team_name", "").lower().strip()
                live = (live_by_coach.get(c["coach_name"].lower().strip())
                        or live_by_team.get(latest_team)
                        or {})
                if live.get("logo"):
                    c["seasons"][0]["logo"] = live["logo"]
                if live.get("color") and live["color"] != "#888":
                    c["seasons"][0]["color"] = live["color"]
            coaches_list.append(c)

        # Sort coaches by total wins desc
        coaches_list.sort(key=lambda c: (-c["total_w"], -c["total_kos"]))

        return render_template(
            "history.html",
            coaches=coaches_list,
            seasons=seasons,
            league_name=get_setting("league_name", "Pokemon Draft League"),
        )
    except Exception:
        app.logger.error("page render failed:\n%s", _tb.format_exc())
        return "Sorry — something went wrong loading this page.", 500


@app.route("/h2h")
def h2h():
    """Head-to-head win/loss matrix for all coaches across all seasons."""
    # Build matrix keyed by coach_name.lower()
    matrix = {}   # {a_key: {b_key: wins_by_a_over_b}}
    all_keys = set()

    def _record(winner_name, loser_name):
        w = winner_name.strip().lower()
        lo = loser_name.strip().lower()
        if not w or not lo or w == lo:
            return
        all_keys.add(w)
        all_keys.add(lo)
        matrix.setdefault(w, {}).setdefault(lo, 0)
        matrix[w][lo] += 1
        matrix.setdefault(lo, {}).setdefault(w, 0)  # ensure entry exists

    # Live season matches
    with get_db() as db:
        live_matches = db.execute("""
            SELECT s.score1, s.score2,
                   c1.coach_name AS c1n, c2.coach_name AS c2n
            FROM schedule s
            JOIN coaches c1 ON s.coach1_id = c1.id
            JOIN coaches c2 ON s.coach2_id = c2.id
            WHERE s.score1 IS NOT NULL AND s.score2 IS NOT NULL
        """).fetchall()
        live_coaches = db.execute(
            "SELECT coach_name, team_name, color, logo_url FROM coaches ORDER BY coach_name"
        ).fetchall()

    for m in live_matches:
        s1, s2 = float(m["score1"] or 0), float(m["score2"] or 0)
        if s1 > s2:
            _record(m["c1n"], m["c2n"])
        elif s2 > s1:
            _record(m["c2n"], m["c1n"])

    # Archived seasons
    seasons = _list_seasons()
    for s in seasons:
        with get_db() as db:
            row = db.execute("SELECT data_json FROM seasons WHERE id=?", (s["id"],)).fetchone()
        if not row:
            continue
        try:
            sd = json.loads(row["data_json"])
        except Exception:
            continue
        cmap = {c["id"]: c.get("coach_name", "") for c in sd.get("coaches", [])}
        for m in sd.get("schedule", []):
            s1 = float(m.get("score1") or 0)
            s2 = float(m.get("score2") or 0)
            c1n = cmap.get(m.get("coach1_id"), "")
            c2n = cmap.get(m.get("coach2_id"), "")
            if not c1n or not c2n:
                continue
            if s1 > s2:
                _record(c1n, c2n)
            elif s2 > s1:
                _record(c2n, c1n)

    # Build ordered coach list
    live_info = {r["coach_name"].strip().lower(): dict(r) for r in live_coaches}
    sorted_keys = sorted(all_keys)
    coaches_out = []
    for k in sorted_keys:
        info = live_info.get(k, {})
        coaches_out.append({
            "key": k,
            "coach_name": info.get("coach_name") or k.title(),
            "team_name": info.get("team_name", ""),
            "color": info.get("color", "#888"),
            "logo_url": info.get("logo_url", ""),
        })

    return render_template(
        "h2h.html",
        coaches=coaches_out,
        matrix=matrix,
        league_name=get_setting("league_name", "Pokemon Draft League"),
    )


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


def _schedule_motw(matches, state):
    """Return the match id for Match of the Week given the week state."""
    motw_id = None
    if state == "DONE":
        best_gap = -1
        for m in matches:
            if m["status"] != "FINAL" or m["fav_id"] is None:
                continue
            tie = m["score1"] == m["score2"]
            if tie:
                continue
            fav_won = (m["fav_id"] == m["c1_id"] and m["score1"] > m["score2"]) or \
                      (m["fav_id"] == m["c2_id"] and m["score2"] > m["score1"])
            gap = abs(m["vote1"] - 50)
            if not fav_won and gap > best_gap:
                best_gap = gap
                motw_id = m["id"]
    if motw_id is None:
        best_d = float("inf")
        for m in matches:
            d = abs(m["vote1"] - 50)
            if d < best_d:
                best_d = d
                motw_id = m["id"]
    return motw_id


@app.route("/schedule")
def schedule():
    import json as _json
    with get_db() as db:
        matches = db.execute("""
            SELECT s.*,
                   c1.coach_name as c1_name, c1.team_name as c1_team, c1.color as c1_color, c1.logo_url as c1_logo,
                   c1.is_defending_champ as c1_is_champ,
                   c2.coach_name as c2_name, c2.team_name as c2_team, c2.color as c2_color, c2.logo_url as c2_logo,
                   c2.is_defending_champ as c2_is_champ
            FROM schedule s
            JOIN coaches c1 ON s.coach1_id = c1.id
            JOIN coaches c2 ON s.coach2_id = c2.id
            ORDER BY s.week, s.pool, s.id
        """).fetchall()
        weeks_rows = db.execute("SELECT DISTINCT week FROM schedule ORDER BY week").fetchall()
        vote_rows = db.execute(
            "SELECT match_id, picked_coach_id FROM pickem_votes"
        ).fetchall()
        coaches = db.execute(
            "SELECT id, coach_name, team_name, pool, logo_url FROM coaches ORDER BY pool, team_name"
        ).fetchall()
        cw_row = db.execute("SELECT value FROM league_settings WHERE key='current_week'").fetchone()
        recap_ids = {r["schedule_id"] for r in db.execute(
            "SELECT DISTINCT schedule_id FROM match_games WHERE recap_json IS NOT NULL"
        ).fetchall()}

    all_weeks = [r["week"] for r in weeks_rows]
    current_week = int(cw_row["value"]) if cw_row else (all_weeks[-1] if all_weeks else 1)

    # Vote counts per match: {match_id: {coach_id: n}}
    vote_counts = {}
    for v in vote_rows:
        vote_counts.setdefault(v["match_id"], {})
        vote_counts[v["match_id"]][v["picked_coach_id"]] = \
            vote_counts[v["match_id"]].get(v["picked_coach_id"], 0) + 1

    # Group matches by week
    by_week_raw = {}
    for m in matches:
        by_week_raw.setdefault(m["week"], []).append(dict(m))

    # Build structured JSON weeks array
    schedule_weeks = []
    total_matches = 0
    for w in all_weeks:
        raw = by_week_raw.get(w, [])
        match_list = []
        for m in raw:
            s1 = int(m.get("score1") or 0)
            s2 = int(m.get("score2") or 0)
            has_result = s1 > 0 or s2 > 0
            status = "FINAL" if has_result else "UPCOMING"
            mv = vote_counts.get(m["id"], {})
            v1 = mv.get(m["coach1_id"], 0)
            v2 = mv.get(m["coach2_id"], 0)
            total_v = v1 + v2
            vote1 = round(v1 / total_v * 100) if total_v else 50
            vote2 = 100 - vote1
            fav_id = (m["coach1_id"] if vote1 > vote2 else m["coach2_id"]) if vote1 != vote2 else None
            match_list.append({
                "id": m["id"],
                "pool": m.get("pool", ""),
                "status": status,
                "c1_id": m["coach1_id"],
                "c1_team": m.get("c1_team") or "",
                "c1_name": m.get("c1_name") or "",
                "c1_logo": m.get("c1_logo") or "",
                "c2_id": m["coach2_id"],
                "c2_team": m.get("c2_team") or "",
                "c2_name": m.get("c2_name") or "",
                "c2_logo": m.get("c2_logo") or "",
                "score1": s1, "score2": s2,
                "vote1": vote1, "vote2": vote2,
                "fav_id": fav_id,
                "motw": False,
                "has_recap": m["id"] in recap_ids,
            })
        total_matches += len(match_list)
        all_done = all(m["status"] == "FINAL" for m in match_list) and bool(match_list)
        state = "DONE" if all_done else "UPCOMING"
        motw_id = _schedule_motw(match_list, state)
        for md in match_list:
            md["motw"] = (md["id"] == motw_id)
        schedule_weeks.append({"week": w, "state": state, "motwId": motw_id, "matches": match_list})

    coaches_list = [{"id": r["id"], "name": r["team_name"] or r["coach_name"], "pool": r["pool"] or ""} for r in coaches]
    num_teams = len(coaches_list)

    return render_template("schedule.html",
                           schedule_json=_json.dumps(schedule_weeks),
                           coaches_json=_json.dumps(coaches_list),
                           current_week=current_week,
                           num_teams=num_teams,
                           total_matches=total_matches,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/pickems")
def pickems():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pickem_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voter_name TEXT NOT NULL,
                week INTEGER NOT NULL,
                match_id INTEGER NOT NULL,
                picked_coach_id INTEGER NOT NULL,
                voter_token TEXT,
                UNIQUE(voter_name, week, match_id)
            )
        """)
        # Determine current week: latest week without all scores finalized
        weeks = [r[0] for r in db.execute("SELECT DISTINCT week FROM schedule ORDER BY week").fetchall()]
        current_week = weeks[-1] if weeks else 1
        for w in weeks:
            unplayed = db.execute(
                "SELECT COUNT(*) FROM schedule WHERE week=? AND (score1 IS NULL OR score1=0) AND (score2 IS NULL OR score2=0)", (w,)
            ).fetchone()[0]
            if unplayed > 0:
                current_week = w
                break

        selected_week = request.args.get("week", current_week, type=int)

        matches = db.execute("""
            SELECT s.*,
                   c1.coach_name as c1_name, c1.team_name as c1_team, c1.color as c1_color, c1.logo_url as c1_logo,
                   c1.is_defending_champ as c1_is_champ,
                   c2.coach_name as c2_name, c2.team_name as c2_team, c2.color as c2_color, c2.logo_url as c2_logo,
                   c2.is_defending_champ as c2_is_champ
            FROM schedule s
            JOIN coaches c1 ON s.coach1_id = c1.id
            JOIN coaches c2 ON s.coach2_id = c2.id
            WHERE s.week = ?
            ORDER BY s.pool, s.id
        """, (selected_week,)).fetchall()
        matches = [dict(m) for m in matches]

        # Attach votes for each match
        vote_rows = db.execute(
            "SELECT * FROM pickem_votes WHERE week=?", (selected_week,)
        ).fetchall()
        # {match_id: {coach_id: [voter_names]}}
        votes_by_match = {}
        for v in vote_rows:
            mid = v["match_id"]
            cid = v["picked_coach_id"]
            votes_by_match.setdefault(mid, {}).setdefault(cid, []).append(v["voter_name"])
        for m in matches:
            m["votes"] = votes_by_match.get(m["id"], {})
            # determine winner (score1 > score2 → coach1, else coach2, 0-0 → None)
            s1 = m["score1"] or 0
            s2 = m["score2"] or 0
            if s1 > s2:
                m["winner_id"] = m["coach1_id"]
            elif s2 > s1:
                m["winner_id"] = m["coach2_id"]
            else:
                m["winner_id"] = None

        # Leaderboard: only count weeks that are fully played
        lb_rows = db.execute("""
            SELECT pv.voter_name,
                   COUNT(*) as total_picks,
                   SUM(CASE WHEN
                       (s.score1 > s.score2 AND pv.picked_coach_id = s.coach1_id) OR
                       (s.score2 > s.score1 AND pv.picked_coach_id = s.coach2_id)
                   THEN 1 ELSE 0 END) as correct
            FROM pickem_votes pv
            JOIN schedule s ON pv.match_id = s.id
            WHERE (s.score1 > 0 OR s.score2 > 0)
            GROUP BY pv.voter_name
            ORDER BY correct DESC, total_picks ASC
        """).fetchall()
        leaderboard = [dict(r) for r in lb_rows]

    return render_template("pickems.html",
                           matches=matches,
                           weeks=weeks,
                           selected_week=selected_week,
                           current_week=current_week,
                           leaderboard=leaderboard,
                           league_name=get_setting("league_name", "Pokemon Draft League"))


@app.route("/pickems/vote", methods=["POST"])
def pickems_vote():
    voter_name = request.form.get("voter_name", "").strip()[:40]
    week = request.form.get("week", type=int)
    match_id = request.form.get("match_id", type=int)
    picked_coach_id = request.form.get("picked_coach_id", type=int)
    if not voter_name or not week or not match_id or not picked_coach_id:
        return jsonify({"error": "Missing fields"}), 400

    # Stable per-browser identity → one vote per browser per match (anti-stuffing).
    token = request.cookies.get("pickem_voter") or secrets.token_hex(16)

    with get_db() as db:
        try:  # ensure the column exists on DBs created before this change
            db.execute("ALTER TABLE pickem_votes ADD COLUMN voter_token TEXT")
        except Exception:
            pass

        match_row = db.execute(
            "SELECT coach1_id, coach2_id FROM schedule WHERE id=?", (match_id,)
        ).fetchone()
        if not match_row:
            return jsonify({"error": "Match not found"}), 404
        c1_id, c2_id = match_row["coach1_id"], match_row["coach2_id"]
        # Integrity: may only vote for one of the two coaches actually in this match
        if picked_coach_id not in (c1_id, c2_id):
            return jsonify({"error": "Invalid pick"}), 400

        # This browser's prior vote for this match (identity = cookie token, not name)
        existing = db.execute(
            "SELECT id FROM pickem_votes WHERE week=? AND match_id=? AND voter_token=?",
            (week, match_id, token)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE pickem_votes SET picked_coach_id=?, voter_name=? WHERE id=?",
                (picked_coach_id, voter_name, existing["id"])
            )
        else:
            try:
                db.execute(
                    "INSERT INTO pickem_votes (voter_name, week, match_id, picked_coach_id, voter_token) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (voter_name, week, match_id, picked_coach_id, token)
                )
            except sqlite3.IntegrityError:
                return jsonify({"error": "That name already voted on this match — pick another."}), 409

        votes = db.execute(
            "SELECT picked_coach_id, COUNT(*) as n FROM pickem_votes WHERE match_id=? GROUP BY picked_coach_id",
            (match_id,)
        ).fetchall()
        vote_map = {r["picked_coach_id"]: r["n"] for r in votes}
        c1_n = vote_map.get(c1_id, 0)
        c2_n = vote_map.get(c2_id, 0)
        total = c1_n + c2_n
        c1_pct = round(c1_n / total * 100) if total > 0 else 50

    resp = jsonify({"ok": True, "c1_pct": c1_pct, "c2_pct": 100 - c1_pct})
    if not request.cookies.get("pickem_voter"):
        resp.set_cookie("pickem_voter", token, max_age=60 * 60 * 24 * 365,
                        httponly=True, samesite="Lax")
    return resp


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
        p["diff"] = int(round(float(p["total_kills"] or 0) - float(p["total_deaths"] or 0)))
        p["kills"] = int(round(float(p["total_kills"] or 0)))
        p["deaths"] = int(round(float(p["total_deaths"] or 0)))
    # Batch-lookup types from pokedex
    if mvp_data:
        slugs = [_pokemon_slug(p["pokemon_name"]) for p in mvp_data]
        with get_db() as db:
            ph = ",".join("?" for _ in slugs)
            pd_rows = db.execute(
                f"SELECT pokeapi_name, type1, type2 FROM pokedex WHERE pokeapi_name IN ({ph})",
                slugs
            ).fetchall()
        pd_map = {r["pokeapi_name"]: (r["type1"] or "Normal", r["type2"] or "") for r in pd_rows}
        for p, slug in zip(mvp_data, slugs):
            t = pd_map.get(slug, ("Normal", ""))
            p["type1"] = t[0]
            p["type2"] = t[1]
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
        # Always clear uber tier_label when changing points — the draftboard grouper
        # will reassign the correct uber label based on the new point value.
        # Keeping a stale label creates a unique (pts, label) group key.
        row = db.execute("SELECT tier_label FROM draft_tiers WHERE id=?", (tier_id,)).fetchone()
        current_label = (row["tier_label"] or "") if row else ""
        if "uber" in current_label.lower():
            db.execute("UPDATE draft_tiers SET points=?, tier_label='' WHERE id=?", (pts, tier_id))
        else:
            db.execute("UPDATE draft_tiers SET points=? WHERE id=?", (pts, tier_id))
    return ("ok", 200)


# ─── Draft Board ─────────────────────────────────────────────────────────────

def _regular_tier_label(pts):
    """Map point value to Tier 1–5 label for regular (non-Mega) Pokemon."""
    if pts >= 16: return "Tier 1"
    if pts >= 13: return "Tier 2"
    if pts >= 9:  return "Tier 3"
    if pts >= 5:  return "Tier 4"
    if pts >= 0:  return "Tier 5"
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
        # Pools A and B draft independently, so track each pool separately:
        # a mon taken in A is still available in B (and vice versa).
        drafted = {}
        for r in drafted_rows:
            entry = drafted.setdefault(r["pokemon_name"], {"A": None, "B": None})
            p = r["pool"]
            if p in ("A", "B") and entry[p] is None:
                entry[p] = dict(r)
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
            label = _regular_tier_label(pts)

        group_key = (pts, label)
        if group_key not in seen_pts:
            seen_pts[group_key] = len(tiers_by_pts)
            tiers_by_pts.append({"points": pts, "label": label, "pokemon": []})
        tiers_by_pts[seen_pts[group_key]]["pokemon"].append(t)

    # Collect all unique move categories for the filter dropdown
    # Seed with key moves that must always be present regardless of DB coverage
    _seed = {
        "Final Gambit", "Expanding Force", "Rising Voltage", "Misty Explosion",
        "Grassy Glide", "Grassy Terrain", "Electric Terrain", "Misty Terrain",
        "Psychic Terrain",
    }
    all_moves = sorted({
        m for t in tiers
        for m in (t["moves"] or "").split("|") if m
    } | _seed)

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


@app.route("/admin/set_week", methods=["POST"])
@admin_required
def admin_set_week():
    week = request.form.get("current_week", "").strip()
    if week.isdigit():
        with get_db() as db:
            db.execute("INSERT OR REPLACE INTO league_settings (key, value) VALUES ('current_week', ?)", (week,))
        flash(f"Current week set to {week}.", "success")
    else:
        flash("Invalid week number.", "warning")
    return redirect(url_for("admin_index"))


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
            is_champ = 1 if request.form.get("is_defending_champ") else 0
            with get_db() as db:
                if is_champ:
                    db.execute("UPDATE coaches SET is_defending_champ=0")
                db.execute(
                    "INSERT INTO coaches (coach_name, team_name, pool, color, logo_url, showdown_name, battle_music_url, draft_mode, is_defending_champ) VALUES (?,?,?,?,?,?,?,?,?)",
                    (request.form["coach_name"], request.form["team_name"],
                     request.form["pool"], request.form.get("color", "#3b82f6"),
                     logo_url,
                     request.form.get("showdown_name", ""),
                     request.form.get("battle_music_url", ""),
                     request.form.get("draft_mode") or None,
                     is_champ)
                )
            flash("Team added!", "success")
        elif action == "edit":
            cid = request.form["coach_id"]
            uploaded = _save_logo_file(request.files.get("logo_file"))
            is_champ = 1 if request.form.get("is_defending_champ") else 0
            with get_db() as db:
                existing = db.execute("SELECT logo_url FROM coaches WHERE id=?", (cid,)).fetchone()
                existing_logo = existing["logo_url"] if existing else ""
                logo_url = uploaded or request.form.get("logo_url", "") or existing_logo or ""
                if is_champ:
                    db.execute("UPDATE coaches SET is_defending_champ=0 WHERE id!=?", (cid,))
                db.execute(
                    "UPDATE coaches SET coach_name=?, team_name=?, pool=?, color=?, logo_url=?, showdown_name=?, battle_music_url=?, draft_mode=?, is_defending_champ=? WHERE id=?",
                    (request.form["coach_name"], request.form["team_name"],
                     request.form["pool"], request.form.get("color", "#3b82f6"),
                     logo_url,
                     request.form.get("showdown_name", ""),
                     request.form.get("battle_music_url", ""),
                     request.form.get("draft_mode") or None,
                     is_champ, cid)
                )
            flash("Team updated!", "success")
        elif action == "delete":
            cid = request.form["coach_id"]
            with get_db() as db:
                db.execute("DELETE FROM coaches WHERE id=?", (cid,))
                db.execute("DELETE FROM pokemon_roster WHERE coach_id=?", (cid,))
            flash("Team deleted.", "warning")
        return redirect(url_for("admin_teams"))
    with get_db() as db:
        _df_row = db.execute("SELECT value FROM league_settings WHERE key='draft_format'").fetchone()
        draft_format = _df_row["value"] if _df_row else ""
    return render_template("admin/teams.html",
                           coaches=coaches,
                           draft_format=draft_format,
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
                    "INSERT INTO schedule (week, coach1_id, coach2_id) VALUES (?,?,?)",
                    (request.form["week"],
                     request.form["coach1_id"], request.form["coach2_id"])
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
                # Fetch match info for Discord notification
                match_row = db.execute("""
                    SELECT s.week, s.pool, c1.team_name as t1, c2.team_name as t2
                    FROM schedule s
                    JOIN coaches c1 ON s.coach1_id = c1.id
                    JOIN coaches c2 ON s.coach2_id = c2.id
                    WHERE s.id=?
                """, (mid,)).fetchone()
                webhook = db.execute(
                    "SELECT value FROM league_settings WHERE key='discord_webhook_url'"
                ).fetchone()
            flash("Result updated!", "success")
            if s1 is not None and s2 is not None and match_row and webhook and webhook["value"]:
                s1i, s2i = int(s1), int(s2)
                t1, t2 = match_row["t1"], match_row["t2"]
                winner = t1 if s1i > s2i else (t2 if s2i > s1i else None)
                if winner:
                    result_line = f"**{t1}** {s1i}–{s2i} **{t2}** → 🏆 **{winner}** wins!"
                else:
                    result_line = f"**{t1}** {s1i}–{s2i} **{t2}** → 🤝 Tie!"
                league = get_setting("league_name", "Pokemon Draft League")
                post_discord(webhook["value"],
                    f"📣 **{league}** — Week {match_row['week']} Result (Pool {match_row['pool']})\n{result_line}"
                )
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


def _import_replays_for_match(match_id, c1_id, c2_id, urls):
    """Parse replay URLs and write game stats for the given schedule entry.

    Returns a list of error strings (empty = success).
    """
    errors = []
    parsed_games = []
    for url in urls:
        try:
            data = _replay_fetch(url)
        except Exception as e:
            errors.append(f"Could not fetch {url}: {e}")
            return errors
        log_text = data["log"]
        parsed_games.append((url, _replay_parse_log(log_text), _replay_parse_recap(log_text), data))

    with get_db() as db:
        # Load coaches and build showdown-name lookup
        c1_row = db.execute("SELECT * FROM coaches WHERE id=?", (c1_id,)).fetchone()
        c2_row = db.execute("SELECT * FROM coaches WHERE id=?", (c2_id,)).fetchone()
        if not c1_row or not c2_row:
            errors.append("Could not load coach rows from DB.")
            return errors
        c1 = dict(c1_row)
        c2 = dict(c2_row)

        # Validate that all replay players map to these two coaches
        sn1 = (c1.get("showdown_name") or "").lower().strip()
        sn2 = (c2.get("showdown_name") or "").lower().strip()
        if not sn1 or not sn2:
            missing = []
            if not sn1:
                missing.append(c1["coach_name"])
            if not sn2:
                missing.append(c2["coach_name"])
            errors.append(
                f"Showdown Name not set for: {', '.join(missing)}. "
                "Set it in Admin → Edit Coach before importing replays."
            )
            return errors

        for url, parsed, _pr, _rd in parsed_games:
            replay_players = {parsed["p1"]["username"].lower(), parsed["p2"]["username"].lower()}
            if not ({sn1, sn2} & replay_players):
                errors.append(
                    f"Replay players {replay_players} don't match coaches "
                    f"'{c1['coach_name']}' ({sn1}) / '{c2['coach_name']}' ({sn2})."
                )
                return errors

        # Determine starting game number
        row = db.execute(
            "SELECT MAX(game_number) as mx FROM match_games WHERE schedule_id=?",
            (match_id,),
        ).fetchone()
        start_game = (row["mx"] or 0) + 1

        for i, (url, parsed, parsed_recap, replay_data) in enumerate(parsed_games):
            game_number = start_game + i

            # Map p1/p2 → coach
            by_pkey = {}
            for pkey in ("p1", "p2"):
                uname = parsed[pkey]["username"].lower()
                if sn1 == uname:
                    by_pkey[pkey] = c1
                elif sn2 == uname:
                    by_pkey[pkey] = c2
                else:
                    by_pkey[pkey] = c1 if pkey == "p1" else c2

            winner_pkey = parsed["winner_player"]
            winner_cid = by_pkey[winner_pkey]["id"] if winner_pkey else None

            # Build roster-aware name maps
            name_maps = {}
            rosters_by_pkey = {}
            for pkey in ("p1", "p2"):
                cid = by_pkey[pkey]["id"]
                roster = [r["pokemon_name"] for r in db.execute(
                    "SELECT pokemon_name FROM pokemon_roster WHERE coach_id=?", (cid,)
                ).fetchall()]
                rosters_by_pkey[pkey] = roster
                all_raw = (set(parsed[pkey]["pokemon_used"])
                           | set(parsed["kills"][pkey])
                           | set(parsed["deaths"][pkey])
                           | set(parsed_recap.get("rosters", {}).get(pkey, []))
                           | set(parsed_recap.get("brought", {}).get(pkey, set())))
                all_raw.update(
                    e["victim"] for e in parsed_recap.get("ko_log", [])
                    if e["victimSide"] == pkey
                )
                all_raw.update(
                    e["by"] for e in parsed_recap.get("ko_log", [])
                    if e.get("bySide") == pkey and e.get("by")
                )
                name_maps[pkey] = {raw: _replay_resolve_poke(raw, roster) for raw in all_raw if raw}

            resolved = {}
            for pkey in ("p1", "p2"):
                nmap = name_maps[pkey]
                resolved[pkey] = {
                    "used":   sorted({nmap.get(m, m) for m in parsed[pkey]["pokemon_used"]}),
                    "kills":  _replay_remap(parsed["kills"][pkey],  nmap),
                    "deaths": _replay_remap(parsed["deaths"][pkey], nmap),
                }

            # Build recap JSON for the match recap page
            match_row = db.execute(
                "SELECT s.week, s.pool, c1.coach_name as c1_name, c1.team_name as c1_team, "
                "c1.logo_url as c1_logo, c2.coach_name as c2_name, c2.team_name as c2_team, "
                "c2.logo_url as c2_logo FROM schedule s "
                "JOIN coaches c1 ON s.coach1_id=c1.id "
                "JOIN coaches c2 ON s.coach2_id=c2.id WHERE s.id=?",
                (match_id,)
            ).fetchone()
            replay_meta = {}
            if match_row:
                replay_meta["week"] = match_row["week"]
                replay_meta["pool"] = match_row["pool"] or "LADDER"
            else:
                replay_meta["pool"] = "LADDER"
            replay_meta["replay"] = url.replace("https://", "").replace("http://", "")
            home_pid = parsed_recap.get("winner_player") or "p1"
            away_pid = "p2" if home_pid == "p1" else "p1"
            replay_meta["logo_home"] = by_pkey[home_pid].get("logo_url")
            replay_meta["logo_away"] = by_pkey[away_pid].get("logo_url")
            replay_meta["id_home"] = by_pkey[home_pid].get("id")
            replay_meta["id_away"] = by_pkey[away_pid].get("id")
            try:
                recap = _replay_build_recap(
                    parsed_recap,
                    meta=replay_meta,
                    name_map_p1=name_maps.get("p1", {}),
                    name_map_p2=name_maps.get("p2", {}),
                )
                recap_json_str = json.dumps(recap)
            except Exception:
                recap_json_str = None

            # Upsert match_games
            existing = db.execute(
                "SELECT id FROM match_games WHERE schedule_id=? AND game_number=?",
                (match_id, game_number),
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE match_games SET replay_url=?, winner_coach_id=?, recap_json=? WHERE id=?",
                    (url, winner_cid, recap_json_str, existing["id"]),
                )
                game_id = existing["id"]
                db.execute("DELETE FROM match_lineups WHERE game_id=?", (game_id,))
                db.execute("DELETE FROM match_stats WHERE game_id=?", (game_id,))
            else:
                db.execute(
                    "INSERT INTO match_games "
                    "(schedule_id, game_number, replay_url, winner_coach_id, recap_json) VALUES (?,?,?,?,?)",
                    (match_id, game_number, url, winner_cid, recap_json_str),
                )
                game_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]

            for pkey in ("p1", "p2"):
                cid = by_pkey[pkey]["id"]
                r = resolved[pkey]
                for mon in sorted(set(r["used"]) | set(r["kills"]) | set(r["deaths"])):
                    db.execute(
                        "INSERT OR IGNORE INTO match_lineups (game_id, coach_id, pokemon_name) "
                        "VALUES (?,?,?)",
                        (game_id, cid, mon),
                    )
                    db.execute(
                        "INSERT INTO match_stats "
                        "(schedule_id, game_id, coach_id, pokemon_name, kills, deaths) "
                        "VALUES (?,?,?,?,?,?)",
                        (match_id, game_id, cid, mon,
                         float(r["kills"].get(mon, 0)), float(r["deaths"].get(mon, 0))),
                    )

        _recalc_match_score(db, match_id, c1_id, c2_id)

    return errors


@app.route("/match/<int:match_id>")
def match_recap(match_id):
    """Public match recap / highlights page. Handles BO1 and BO3 bring-6-use-4."""
    with get_db() as db:
        match = db.execute("""
            SELECT s.*, c1.coach_name as c1_name, c1.team_name as c1_team, c1.logo_url as c1_logo,
                   c1.id as c1_id, c2.coach_name as c2_name, c2.team_name as c2_team,
                   c2.logo_url as c2_logo, c2.id as c2_id
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

    def _enrich_recap(recap, game_number):
        """Attach match context and team logos to a parsed recap."""
        facts = recap.get("facts", {})
        if not facts.get("week") or facts.get("week") == "—":
            facts["week"] = match.get("week", "—")
        if not facts.get("pool"):
            facts["pool"] = match.get("pool", "—")
        if not facts.get("date") and match.get("match_date"):
            facts["date"] = match["match_date"]
        recap["_game_number"] = game_number

        # Map home/away names to DB coaches for logo lookup
        home_name = recap.get("home", {}).get("name", "").lower()
        away_name = recap.get("away", {}).get("name", "").lower()
        c1_sn = (match.get("c1_name") or "").lower()
        c2_sn = (match.get("c2_name") or "").lower()

        home = recap.get("home", {})
        away = recap.get("away", {})
        if not home.get("logo_url"):
            # Match by coach name proximity
            if home_name == c1_sn or c1_sn in home_name:
                home["logo_url"] = match.get("c1_logo")
            elif home_name == c2_sn or c2_sn in home_name:
                home["logo_url"] = match.get("c2_logo")
        if not away.get("logo_url"):
            if away_name == c2_sn or c2_sn in away_name:
                away["logo_url"] = match.get("c2_logo")
            elif away_name == c1_sn or c1_sn in away_name:
                away["logo_url"] = match.get("c1_logo")
        return recap

    # Load ALL games that have recap_json (BO3 may have up to 3)
    all_recaps = []
    for g in games:
        if g.get("recap_json"):
            try:
                r = json.loads(g["recap_json"])
                r["_game_id"] = g["id"]
                r["_replay_url"] = g.get("replay_url", "")
                _enrich_recap(r, g["game_number"])
                all_recaps.append(r)
            except Exception:
                pass

    # Build series summary for BO3.
    # Each game's recap labels its winner as "HOME" (build_recap always does this),
    # so we cannot use totals.winner to count wins per coach across games.
    # Instead we count from match_games.winner_coach_id which holds the DB coach ID.
    series = None
    if len(all_recaps) > 1:
        c1_id = match.get("c1_id") or match.get("coach1_id")
        c2_id = match.get("c2_id") or match.get("coach2_id")
        c1_wins = sum(1 for g in games if g.get("recap_json") and g.get("winner_coach_id") == c1_id)
        c2_wins = sum(1 for g in games if g.get("recap_json") and g.get("winner_coach_id") == c2_id)
        series_winner = "c1" if c1_wins > c2_wins else ("c2" if c2_wins > c1_wins else None)
        series = {
            "c1_wins": c1_wins,
            "c2_wins": c2_wins,
            "winner": series_winner,   # "c1", "c2", or None (tied/in-progress)
            "c1_name": match.get("c1_team", ""),
            "c2_name": match.get("c2_team", ""),
            "c1_logo": match.get("c1_logo"),
            "c2_logo": match.get("c2_logo"),
            "games": len(all_recaps),
        }

    # Featured = last game (deciding game for BO3, only game for BO1)
    featured = all_recaps[-1] if all_recaps else None

    return render_template(
        "match_recap.html",
        match=match,
        featured=featured,
        all_recaps=all_recaps,
        series=series,
        games=games,
        type_colors=_RECAP_TYPE_COLORS,
        static_mode="static" in request.args,
    )


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
        # Access control: only the two coaches in this match (or an admin) may edit it.
        if session.get("role") != "admin" and session.get("coach_id") not in (match["c1_id"], match["c2_id"]):
            return "Forbidden — you are not a coach in this match.", 403
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

        elif action == "import_replays":
            raw_urls = request.form.get("replay_urls", "")
            urls = [u.strip() for u in raw_urls.splitlines() if u.strip()]
            if not urls:
                flash("No replay URLs provided.", "warning")
            else:
                try:
                    errors = _import_replays_for_match(match_id, match["c1_id"], match["c2_id"], urls)
                    if errors:
                        for e in errors:
                            flash(e, "danger")
                    else:
                        flash(f"Imported {len(urls)} game(s) from replay.", "success")
                except Exception as e:
                    flash(f"Replay import failed: {e}", "danger")

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
    with get_db() as db:
        users = db.execute(
            "SELECT u.*, c.coach_name FROM users u LEFT JOIN coaches c ON u.coach_id = c.id ORDER BY u.role, u.username"
        ).fetchall()
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            pw = request.form.get("password", "")
            pw_hash = hash_pw(pw)
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
            pw_hash = hash_pw(pw)
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
    # Add LIVE-status column for bracket display
    cols_pm = [r[1] for r in db.execute("PRAGMA table_info(playoff_matches)").fetchall()]
    if "match_status" not in cols_pm:
        db.execute("ALTER TABLE playoff_matches ADD COLUMN match_status TEXT DEFAULT NULL")


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


def _build_bracket_json(matches_raw, coaches_map, settings):
    """Build structured bracket data for the classic playoff bracket view."""
    wb = [m for m in matches_raw if m["bracket"] == "W"]
    if not wb:
        return None

    max_round = max(m["round"] for m in wb)

    def rcode(r):
        d = max_round - r
        if d == 0: return "F"
        if d == 1: return "SF"
        if d == 2: return "QF"
        if d == 3: return "WC"
        return f"R{r}"

    by_id = {m["id"]: dict(m) for m in wb}

    # (target_match_id, next_match_slot) → feeder_match_id
    feeder_of = {}
    for m in wb:
        if m["next_match_id"]:
            feeder_of[(m["next_match_id"], m["next_match_slot"])] = m["id"]

    # Assign match codes; WC round shows only non-bye matches
    db_to_code = {}
    for rnd in sorted(set(m["round"] for m in wb)):
        rnd_ms = sorted([m for m in wb if m["round"] == rnd], key=lambda x: x["position"])
        rc = rcode(rnd)
        visible = [m for m in rnd_ms if not m["is_bye"]] if rc == "WC" else rnd_ms
        for i, m in enumerate(visible):
            db_to_code[m["id"]] = f"{rc}{i + 1}"

    # FEEDS list for JS wire drawing
    feeds = []
    for m in wb:
        if m["id"] not in db_to_code:
            continue
        if m["next_match_id"] and m["next_match_id"] in db_to_code:
            feeds.append([db_to_code[m["id"]], db_to_code[m["next_match_id"]]])
    final_m = next((m for m in wb if m["round"] == max_round), None)
    if final_m and final_m["id"] in db_to_code:
        feeds.append([db_to_code[final_m["id"]], "CROWN"])

    result = []
    for rnd in sorted(set(m["round"] for m in wb)):
        rnd_ms = sorted([m for m in wb if m["round"] == rnd], key=lambda x: x["position"])
        rc = rcode(rnd)
        visible = [m for m in rnd_ms if not m["is_bye"]] if rc == "WC" else rnd_ms

        for i, m in enumerate(visible):
            m = dict(m)
            code = f"{rc}{i + 1}"
            c1 = coaches_map.get(m["coach1_id"])
            c2 = coaches_map.get(m["coach2_id"])

            fa_id = feeder_of.get((m["id"], 1))
            fb_id = feeder_of.get((m["id"], 2))

            def feeder_code(fid):
                if not fid:
                    return None
                if by_id.get(fid, {}).get("is_bye"):
                    return None
                return db_to_code.get(fid)

            feeder_a = feeder_code(fa_id) if not c1 else None
            feeder_b = feeder_code(fb_id) if not c2 else None
            is_bye_a = bool(fa_id and by_id.get(fa_id, {}).get("is_bye"))
            is_bye_b = bool(fb_id and by_id.get(fb_id, {}).get("is_bye"))

            w_id = m["winner_id"]
            ms_val = m.get("match_status") or ""
            if w_id:
                status = "FINAL"
            elif ms_val == "LIVE":
                status = "LIVE"
            elif c1 and c2:
                status = "UPCOMING"
            else:
                status = "TBD"

            winner = None
            if w_id:
                winner = "a" if w_id == m["coach1_id"] else "b"

            s1, s2 = m["seed1"], m["seed2"]
            upset = bool(
                (winner == "a" and s1 and s2 and s1 > s2) or
                (winner == "b" and s1 and s2 and s2 > s1)
            )

            def team_dict(c, seed):
                if not c:
                    return None
                return {
                    "id": c["id"],
                    "name": c["team_name"],
                    "logo": c.get("logo_url") or "",
                    "color": c.get("color") or "#374151",
                    "seed": seed,
                }

            result.append({
                "code": code,
                "db_id": m["id"],
                "round": rc,
                "pos": i,
                "team_a": team_dict(c1, m["seed1"]),
                "team_b": team_dict(c2, m["seed2"]),
                "seed_a": m["seed1"],
                "seed_b": m["seed2"],
                "score_a": m["score1"],
                "score_b": m["score2"],
                "status": status,
                "winner": winner,
                "upset": upset,
                "feeder_a": feeder_a,
                "feeder_b": feeder_b,
                "is_bye_a": is_bye_a,
                "is_bye_b": is_bye_b,
            })

    done = sum(1 for m in result if m["status"] == "FINAL")
    total = len(result)
    live_m = next((m for m in result if m["status"] == "LIVE"), None)

    final_match = next((m for m in result if m["round"] == "F"), None)
    champion = None
    if final_match and final_match["winner"]:
        champion = final_match[f"team_{final_match['winner']}"]

    season = settings.get("season", "?")
    try:
        next_season = str(int(season) + 1)
    except (ValueError, TypeError):
        next_season = season

    return {
        "matches": result,
        "feeds": feeds,
        "progress": {"done": done, "total": total},
        "live": live_m["code"] if live_m else None,
        "champion": champion,
        "season": season,
        "next_season": next_season,
        "num_teams": settings.get("playoff_players", "12"),
        "match_fmt": settings.get("playoff_match_format", "BO3"),
        "byes": settings.get("playoff_byes", "4"),
        "max_round": max_round,
    }


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
    bracket = _build_bracket_json(list(matches_raw), coaches_map, settings) if matches_raw else None

    if bracket:
        mr = bracket["max_round"]
        if mr >= 4:
            round_cols = [("WC", "WILD CARD"), ("QF", "QUARTERFINALS"), ("SF", "SEMIFINALS"), ("F", "GRAND FINAL")]
            col_template = "1fr 1fr 0.92fr 0.88fr 0.78fr"
        elif mr == 3:
            round_cols = [("QF", "QUARTERFINALS"), ("SF", "SEMIFINALS"), ("F", "GRAND FINAL")]
            col_template = "1fr 0.92fr 0.88fr 0.78fr"
        else:
            round_cols = [("SF", "SEMIFINALS"), ("F", "GRAND FINAL")]
            col_template = "1fr 0.88fr 0.78fr"
    else:
        round_cols = []
        col_template = ""

    return render_template(
        "playoffs.html",
        bracket=bracket,
        bracket_json=json.dumps(bracket) if bracket else "null",
        has_bracket=bool(matches_raw),
        round_cols=round_cols,
        col_template=col_template,
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
                # Fetch team names for Discord
                c1_row = db.execute("SELECT team_name FROM coaches WHERE id=?", (m["coach1_id"],)).fetchone()
                c2_row = db.execute("SELECT team_name FROM coaches WHERE id=?", (m["coach2_id"],)).fetchone()
                webhook = db.execute("SELECT value FROM league_settings WHERE key='discord_webhook_url'").fetchone()
            flash("Result saved!", "success")
            if c1_row and c2_row and webhook and webhook["value"]:
                t1 = c1_row["team_name"]
                t2 = c2_row["team_name"]
                winner_name = t1 if score1 > score2 else t2
                round_name = f"Round {m['round']}"
                league = get_setting("league_name", "Pokemon Draft League")
                post_discord(webhook["value"],
                    f"🏆 **{league} Playoffs** — {round_name} Result\n**{t1}** {score1}–{score2} **{t2}** → 🥊 **{winner_name}** advances!"
                )

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
        # Access control: only the two coaches in this playoff match (or an admin) may edit it.
        if session.get("role") != "admin" and session.get("coach_id") not in (pm["c1_id"], pm["c2_id"]):
            return "Forbidden — you are not a coach in this match.", 403
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

# Plan Griffin draft system
UBER_NAMED_TIERS = {"Platinum", "Gold", "Silver", "Bronze"}
UBER_POINTS = {27: "Bronze", 28: "Silver", 29: "Gold", 30: "Platinum"}


def _uber_named(label):
    """Bare uber tier (Bronze/Silver/Gold/Platinum) for a tier_label that may be
    stored with an 'Uber ' prefix (e.g. 'Uber Platinum'); '' if not an uber tier.
    Uber labels in the DB carry the prefix, but all uber logic compares against
    the bare names — normalize here so the prefix never silently fails the match."""
    name = (label or "").replace("Uber ", "").strip()
    return name if name in UBER_NAMED_TIERS else ""
TICKET_ALLOC   = {"T1": 1, "T2": 1, "T3": 2, "T4": 2, "T5": 2}
TICKET_RANK    = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}
TIER_TO_TICKET = {"Tier 1": "T1", "Tier 2": "T2", "Tier 3": "T3", "Tier 4": "T4", "Tier 5": "T5"}

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


def _get_pool_sequence(snake_order, pool_coach_ids, round_structure):
    """Return snake sequence for a single pool (filters snake_order to pool coaches only)."""
    pool_order = [c for c in snake_order if c in pool_coach_ids]
    return _get_snake_pick_sequence(pool_order, round_structure)


def _auto_slot(pokemon_name, poke_pts, mega_names_set, existing_roster_rows):
    """Auto-assign a new pick to the correct roster slot.

    Fills paid slots (2 per tier) before free slots (1 per tier).
    Overflows to 'Free Pick' when all slots of that tier are used.
    Returns (slot_name, is_free_pick).

    Megas are NOT special-cased — they take a regular tier slot based on their
    point value, exactly like any other pick.
    """
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


# ─── Plan Griffin helpers ──────────────────────────────────────────────────────

def _can_add_uber(existing_named, new_named):
    """True if new_named is a valid next uber pick given existing uber named tiers."""
    if new_named not in UBER_NAMED_TIERS:
        return False
    slots_used = sum(2 if t == "Platinum" else 1 for t in existing_named)
    if slots_used >= 2:
        return False
    if slots_used == 0:
        return True
    first = existing_named[0]
    valid_seconds = {
        "Platinum": set(),
        "Gold":     {"Bronze"},
        "Silver":   {"Silver", "Bronze"},
        "Bronze":   {"Silver", "Bronze"},
    }
    return new_named in valid_seconds.get(first, set())


def _valid_uber_second_choices(existing_named):
    """Returns set of valid named tiers for the next uber pick."""
    slots_used = sum(2 if t == "Platinum" else 1 for t in existing_named)
    if slots_used >= 2:
        return set()
    if slots_used == 0:
        return set(UBER_NAMED_TIERS)
    first = existing_named[0]
    return {
        "Platinum": set(),
        "Gold":     {"Bronze"},
        "Silver":   {"Silver", "Bronze"},
        "Bronze":   {"Silver", "Bronze"},
    }.get(first, set())


def _get_coach_uber_named_tiers(db, coach_id, session_id):
    """Named tier labels for a coach's uber picks in a session (e.g. ['Gold']).
    Detects by tier_label first, falls back to points for picks made via UBER_POINTS."""
    rows = db.execute("""
        SELECT dt.tier_label, dt.points
        FROM draft_picks dp
        JOIN draft_tiers dt ON dp.pokemon_name = dt.name
        WHERE dp.session_id=? AND dp.coach_id=? AND dp.slot_name IN ('Uber 1','Uber 2')
    """, (session_id, coach_id)).fetchall()
    result = []
    for r in rows:
        named = _uber_named(r["tier_label"])
        if named:
            result.append(named)
        elif (r["points"] or 0) in UBER_POINTS:
            result.append(UBER_POINTS[r["points"]])
    return result


def _get_coach_draft_state(db, coach_id, session_id):
    """Returns remaining budget or tickets for a coach, plus uber pick status."""
    coach = db.execute("SELECT draft_mode FROM coaches WHERE id=?", (coach_id,)).fetchone()
    mode = (coach["draft_mode"] or "legacy") if coach else "legacy"

    picks = db.execute(
        "SELECT points, ticket_used, slot_name FROM draft_picks WHERE session_id=? AND coach_id=?",
        (session_id, coach_id)
    ).fetchall()

    regular_picks = [p for p in picks if p["slot_name"] not in ("Uber 1", "Uber 2")]
    existing_uber_named = _get_coach_uber_named_tiers(db, coach_id, session_id)
    uber_count = len(existing_uber_named)
    slots_used = sum(2 if t == "Platinum" else 1 for t in existing_uber_named)
    valid_next_uber = _valid_uber_second_choices(existing_uber_named)

    base = {
        "mode": mode,
        "uber_count": uber_count,
        "uber_slots_used": slots_used,
        "uber_named": existing_uber_named,
        "valid_next_uber": sorted(valid_next_uber),
    }

    if mode == "legacy":
        return base
    elif mode == "points":
        setting = db.execute(
            "SELECT value FROM league_settings WHERE key='points_budget_griffin'"
        ).fetchone()
        budget = int(setting["value"]) if setting else 70
        spent = sum(p["points"] or 0 for p in regular_picks)
        return {**base, "budget": budget, "spent": spent, "remaining": budget - spent}
    else:
        used = {}
        for p in regular_picks:
            t = p["ticket_used"]
            if t and t != "uber":
                used[t] = used.get(t, 0) + 1
        remaining_tickets = {t: TICKET_ALLOC[t] - used.get(t, 0) for t in TICKET_ALLOC}
        return {**base, "remaining_tickets": remaining_tickets}


@app.route("/draft")
def draft_sheet():
    with get_db() as db:
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
        roster = db.execute("""
            SELECT pr.*, c.pool, COALESCE(dt.tier_label,'') as poke_tier_label
            FROM pokemon_roster pr
            JOIN coaches c ON pr.coach_id = c.id
            LEFT JOIN draft_tiers dt ON LOWER(pr.pokemon_name) = LOWER(dt.name)
        """).fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
        active_session = db.execute(
            "SELECT * FROM draft_sessions WHERE status IN ('active','paused') ORDER BY id DESC LIMIT 1"
        ).fetchone()
        mega_names = {r["name"] for r in db.execute("SELECT name FROM draft_tiers WHERE is_mega=1").fetchall()}

    budget = int(settings.get("points_budget_griffin", "70"))
    draft_format = settings.get("draft_format", "")
    coaches_a = [c for c in coaches if c["pool"] == "A"]
    coaches_b = [c for c in coaches if c["pool"] == "B"]
    roster_a = [r for r in roster if r["pool"] == "A"]
    roster_b = [r for r in roster if r["pool"] == "B"]

    def _build_team_card(coach, roster_picks):
        picks = [dict(r) for r in roster_picks if r["coach_id"] == coach["id"]]
        draft_mode = _effective_draft_mode(coach, draft_format)
        _empty = {"uber1": [], "uber2": [], "tier1": [], "tier1f": [], "tier2": [], "tier2f": [],
                  "tier3": [], "tier3f": [], "tier4": [], "tier4f": [], "tier5": [], "tier5f": [],
                  "mega": [], "free": [], "all_picks": [], "tier_slots": {}, "uber": []}

        UBER_TIERS = {"Uber 1", "Uber 2"}

        def _is_uber(p):
            return (p.get("tier") in UBER_TIERS
                    or bool(_uber_named(p.get("poke_tier_label"))))

        if draft_mode == "points":
            non_mega = [p for p in picks if p["pokemon_name"] not in mega_names]
            uber = [p for p in non_mega if _is_uber(p)]
            regular = sorted([p for p in non_mega if not _is_uber(p)],
                             key=lambda p: -(p.get("points") or 0))
            spent = sum(p.get("points") or 0 for p in regular)
            return {"mode": draft_mode, "coach": dict(coach), "spent": spent,
                    "remaining": budget - spent,
                    "slots": dict(_empty, all_picks=regular, uber=uber)}

        if draft_mode == "tier_tickets":
            ticket_tiers = ["Tier 1", "Tier 2", "Tier 3", "Tier 4", "Tier 5"]
            tier_slots = {t: [p for p in picks if p.get("tier") == t] for t in ticket_tiers}
            uber = [p for p in picks if _is_uber(p)]
            return {"mode": draft_mode, "coach": dict(coach), "spent": 0, "remaining": 0,
                    "slots": dict(_empty, tier_slots=tier_slots, uber=uber)}

        # Legacy mode
        def _tier(tier, free=False):
            return [p for p in picks if p.get("tier") == tier
                    and bool(p.get("is_free_pick")) == free
                    and p["pokemon_name"] not in mega_names]
        mega = [p for p in picks if p["pokemon_name"] in mega_names]
        free = [p for p in picks if p.get("tier") == "Free Pick"
                and p["pokemon_name"] not in mega_names]
        spent = sum(p.get("points") or 0 for p in picks
                    if p.get("tier") == "Free Pick" and not p.get("is_free_pick"))
        return {
            "mode": draft_mode, "coach": dict(coach), "spent": spent,
            "remaining": budget - spent,
            "slots": dict(_empty,
                uber1=_tier("Uber 1"), uber2=_tier("Uber 2"),
                tier1=_tier("Tier 1"), tier1f=_tier("Tier 1", True),
                tier2=_tier("Tier 2"), tier2f=_tier("Tier 2", True),
                tier3=_tier("Tier 3"), tier3f=_tier("Tier 3", True),
                tier4=_tier("Tier 4"), tier4f=_tier("Tier 4", True),
                tier5=_tier("Tier 5"), tier5f=_tier("Tier 5", True),
                mega=mega, free=free),
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

        coaches_a = [c for c in coaches if c["pool"] == "A"]
        coaches_b = [c for c in coaches if c["pool"] == "B"]
        coaches_map = {c["id"]: dict(c) for c in coaches}
        pool_a_ids = {c["id"] for c in coaches_a}
        pool_b_ids = {c["id"] for c in coaches_b}

        # Build grid from pokemon_roster — always, so the grid shows even without an active session
        try:
            _roster_rows_base = db.execute("""
                SELECT pr.*, COALESCE(dt.tier_label,'') as poke_tier_label
                FROM pokemon_roster pr
                LEFT JOIN draft_tiers dt ON LOWER(pr.pokemon_name) = LOWER(dt.name)
            """).fetchall()
        except Exception:
            _roster_rows_base = []
        _uber_counts_base = {}
        _roster_base = []
        _base_keys = _roster_rows_base[0].keys() if _roster_rows_base else []
        for r in _roster_rows_base:
            tier = r["tier"]
            if tier not in TIER_ORDER and _uber_named(r["poke_tier_label"]):
                cid = r["coach_id"]
                count = _uber_counts_base.get(cid, 0)
                tier = "Uber 2" if count >= 1 else "Uber 1"
                _uber_counts_base[cid] = count + 1
            try:
                _roster_base.append({
                    "coach_id": r["coach_id"], "pokemon_name": r["pokemon_name"],
                    "points": r["points"], "tier": tier,
                    "poke_tier_label": r["poke_tier_label"],
                    "is_tera_captain": int(r["is_tera_captain"]) if "is_tera_captain" in _base_keys and r["is_tera_captain"] else 0,
                    "is_zmove_captain": int(r["is_zmove_captain"]) if "is_zmove_captain" in _base_keys and r["is_zmove_captain"] else 0,
                    "is_free_pick": (r["is_free_pick"] or 0) if "is_free_pick" in _base_keys else 0,
                    "ticket_used": "",
                })
            except Exception:
                pass
        grid_a, max_a = _build_draft_grid(coaches_a, _roster_base)
        grid_b, max_b = _build_draft_grid(coaches_b, _roster_base)

        if session_row is None:
            is_admin = session.get("role") == "admin"
            return render_template(
                "draft_live.html",
                draft_session=None,
                coaches=coaches,
                coaches_a=coaches_a,
                coaches_b=coaches_b,
                coaches_map=coaches_map,
                grid_a=grid_a, grid_b=grid_b,
                max_a=max_a, max_b=max_b,
                tier_order=TIER_ORDER,
                coaches_draft_states={},
                current_coach_a_id=None,
                current_coach_b_id=None,
                current_coach_id=None,
                current_slot_a=None,
                current_slot_b=None,
                current_slot=None,
                last_pick_a=None,
                last_pick_b=None,
                is_admin=is_admin,
                my_picks=[],
                mechanic_tera=settings.get("mechanic_tera", "0"),
                mechanic_zmove=settings.get("mechanic_zmove", "0"),
                league_name=settings.get("league_name", "Pokemon Draft League"),
            )

        picks = db.execute(
            "SELECT * FROM draft_picks WHERE session_id=? ORDER BY pick_number",
            (session_row["id"],)
        ).fetchall()

        round_structure_str = settings.get("draft_round_structure", "")
        try:
            round_structure = json.loads(round_structure_str) if round_structure_str else DEFAULT_ROUND_STRUCTURE
        except Exception:
            round_structure = DEFAULT_ROUND_STRUCTURE

        snake_order = json.loads(session_row["snake_order"] or "[]")

        # Per-pool independent sequences and pick counters (pool_a/b_ids already set above)
        seq_a = _get_pool_sequence(snake_order, pool_a_ids, round_structure)
        seq_b = _get_pool_sequence(snake_order, pool_b_ids, round_structure)

        current_pick_a = session_row["current_pick_a"] or 1
        current_pick_b = session_row["current_pick_b"] or 1

        current_slot_a = seq_a[current_pick_a - 1] if seq_a and 0 < current_pick_a <= len(seq_a) else None
        current_slot_b = seq_b[current_pick_b - 1] if seq_b and 0 < current_pick_b <= len(seq_b) else None

        current_coach_a_id = current_slot_a[3] if current_slot_a else None
        current_coach_b_id = current_slot_b[3] if current_slot_b else None

        # Bank picks: override on-clock coach if there's a pending bank turn
        try:
            bank_pending_a = session_row["bank_pending_a"] or 0
            bank_pending_b = session_row["bank_pending_b"] or 0
        except (IndexError, KeyError):
            bank_pending_a = 0
            bank_pending_b = 0
        if bank_pending_a and bank_pending_a in coaches_map:
            current_coach_a_id = bank_pending_a
        if bank_pending_b and bank_pending_b in coaches_map:
            current_coach_b_id = bank_pending_b

        next_5_a = seq_a[current_pick_a - 1: current_pick_a + 4] if seq_a else []
        next_5_b = seq_b[current_pick_b - 1: current_pick_b + 4] if seq_b else []

        all_draft = db.execute(
            "SELECT * FROM draft_tiers WHERE is_banned != 1 ORDER BY points DESC, name"
        ).fetchall()

        # Available pokemon per pool (pools draft independently — same mon can appear in both)
        picked_names_a = {p["pokemon_name"] for p in picks if p["coach_id"] in pool_a_ids}
        picked_names_b = {p["pokemon_name"] for p in picks if p["coach_id"] in pool_b_ids}

        def _make_avail(picked_names):
            result = []
            for p in all_draft:
                if p["name"] in picked_names:
                    continue
                db_label = p["tier_label"] or ""
                pts = p["points"] or 0
                named = _uber_named(db_label)
                if named:
                    tier_label = named
                elif pts in UBER_POINTS:
                    tier_label = UBER_POINTS[pts]
                else:
                    tier_label = _regular_tier_label(pts) or db_label
                result.append(dict(p, tier_label=tier_label))
            return result

        avail_pokemon_a = _make_avail(picked_names_a)
        avail_pokemon_b = _make_avail(picked_names_b)

        # Build grid from pokemon_roster (full roster) + ticket_used from current session
        pick_info_map = {(p["coach_id"], p["pokemon_name"]): p for p in picks}
        roster_rows = db.execute("""
            SELECT pr.*, COALESCE(dt.tier_label,'') as poke_tier_label
            FROM pokemon_roster pr
            LEFT JOIN draft_tiers dt ON LOWER(pr.pokemon_name) = LOWER(dt.name)
        """).fetchall()
        # Track uber slot assignment per coach so misnamed entries land in the right row
        uber_counts = {}
        roster_from_picks = []
        _roster_keys = roster_rows[0].keys() if roster_rows else []
        for r in roster_rows:
            pick_info = pick_info_map.get((r["coach_id"], r["pokemon_name"]))
            tier = r["tier"]
            # Normalize tier: if stored value is missing/wrong but pokemon is uber-level, fix it
            if tier not in TIER_ORDER and _uber_named(r["poke_tier_label"]):
                cid = r["coach_id"]
                count = uber_counts.get(cid, 0)
                tier = "Uber 2" if count >= 1 else "Uber 1"
                uber_counts[cid] = count + 1
            roster_from_picks.append({
                "coach_id": r["coach_id"], "pokemon_name": r["pokemon_name"],
                "points": r["points"], "tier": tier,
                "poke_tier_label": r["poke_tier_label"],
                "is_tera_captain": int(r["is_tera_captain"]) if "is_tera_captain" in _roster_keys and r["is_tera_captain"] else 0,
                "is_zmove_captain": int(r["is_zmove_captain"]) if "is_zmove_captain" in _roster_keys and r["is_zmove_captain"] else 0,
                "is_free_pick": (r["is_free_pick"] or 0) if "is_free_pick" in _roster_keys else 0,
                "ticket_used": (pick_info["ticket_used"] if pick_info else None) or "",
            })
        grid_a, max_a = _build_draft_grid(coaches_a, roster_from_picks)
        grid_b, max_b = _build_draft_grid(coaches_b, roster_from_picks)

        # Per-coach draft state (mode, remaining budget/tickets, uber status)
        coaches_draft_states = {
            c["id"]: _get_coach_draft_state(db, c["id"], session_row["id"])
            for c in coaches
        }

    is_admin = session.get("role") == "admin"
    my_coach_id = session.get("coach_id")

    # Determine which pool the logged-in coach belongs to
    my_coach_row = coaches_map.get(my_coach_id) if my_coach_id else None
    my_pool = my_coach_row["pool"] if my_coach_row else None

    if my_pool == "A":
        current_coach_id = current_coach_a_id
        current_slot = current_slot_a
        can_pick = is_admin or (my_coach_id == current_coach_a_id)
        avail_pokemon = avail_pokemon_a
    elif my_pool == "B":
        current_coach_id = current_coach_b_id
        current_slot = current_slot_b
        can_pick = is_admin or (my_coach_id == current_coach_b_id)
        avail_pokemon = avail_pokemon_b
    else:
        # Admin without coach assignment
        current_coach_id = current_coach_a_id
        current_slot = current_slot_a
        can_pick = is_admin
        avail_pokemon = avail_pokemon_a

    # Build current user's picks from pokemon_roster for the captain panel
    my_picks = []
    if my_coach_id:
        for r in roster_from_picks:
            if r["coach_id"] == my_coach_id:
                my_picks.append({
                    "pokemon_name": r["pokemon_name"],
                    "points": r["points"],
                    "tier": r["tier"],
                    "coach_id": my_coach_id,
                    "is_tera_captain": r["is_tera_captain"],
                    "is_zmove_captain": r["is_zmove_captain"],
                })

    current_draft_state = coaches_draft_states.get(current_coach_id, {}) if current_coach_id else {}
    current_draft_state_a = coaches_draft_states.get(current_coach_a_id, {}) if current_coach_a_id else {}
    current_draft_state_b = coaches_draft_states.get(current_coach_b_id, {}) if current_coach_b_id else {}

    # Most recent pick per pool (for LAST_PICK display in pool header)
    last_pick_a = next((p for p in reversed(picks) if p["coach_id"] in pool_a_ids), None)
    last_pick_b = next((p for p in reversed(picks) if p["coach_id"] in pool_b_ids), None)

    return render_template(
        "draft_live.html",
        draft_session=dict(session_row),
        picks=picks,
        coaches=coaches,
        coaches_a=sorted([c for c in coaches if c["pool"] == "A"], key=lambda c: snake_order.index(c["id"]) if c["id"] in snake_order else 999),
        coaches_b=sorted([c for c in coaches if c["pool"] == "B"], key=lambda c: snake_order.index(c["id"]) if c["id"] in snake_order else 999),
        grid_a=grid_a, grid_b=grid_b,
        max_a=max_a, max_b=max_b,
        tier_order=TIER_ORDER,
        avail_pokemon=avail_pokemon,
        avail_pokemon_a=avail_pokemon_a,
        avail_pokemon_b=avail_pokemon_b,
        current_slot=current_slot,
        current_slot_a=current_slot_a,
        current_slot_b=current_slot_b,
        current_coach_id=current_coach_id,
        current_coach_a_id=current_coach_a_id,
        current_coach_b_id=current_coach_b_id,
        current_pick_a=current_pick_a,
        current_pick_b=current_pick_b,
        next_5=next_5_a,
        next_5_a=next_5_a,
        next_5_b=next_5_b,
        coaches_map=coaches_map,
        can_pick=can_pick,
        is_admin=is_admin,
        my_pool=my_pool,
        round_structure=round_structure,
        my_coach_id=my_coach_id,
        my_picks=my_picks,
        coaches_draft_states=coaches_draft_states,
        bank_pending_a=bank_pending_a,
        bank_pending_b=bank_pending_b,
        current_draft_state=current_draft_state,
        current_draft_state_a=current_draft_state_a,
        current_draft_state_b=current_draft_state_b,
        last_pick_a=dict(last_pick_a) if last_pick_a else None,
        last_pick_b=dict(last_pick_b) if last_pick_b else None,
        ticket_alloc=TICKET_ALLOC,
        tier_to_ticket=TIER_TO_TICKET,
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

        is_admin = session.get("role") == "admin"
        my_coach_id = session.get("coach_id")

        coaches_all = db.execute("SELECT * FROM coaches").fetchall()
        pool_a_ids = {c["id"] for c in coaches_all if c["pool"] == "A"}
        pool_b_ids = {c["id"] for c in coaches_all if c["pool"] == "B"}

        # Determine which pool this pick is for
        if is_admin:
            pick_pool = request.form.get("pick_pool", "A")
        else:
            coach_row = next((c for c in coaches_all if c["id"] == my_coach_id), None)
            if not coach_row:
                flash("Coach not found.", "warning")
                return redirect(url_for("draft_live"))
            pick_pool = coach_row["pool"]

        pool_ids = pool_a_ids if pick_pool == "A" else pool_b_ids

        snake_order = json.loads(session_row["snake_order"] or "[]")
        seq = _get_pool_sequence(snake_order, pool_ids, round_structure)

        current_pick = (session_row["current_pick_a"] or 1) if pick_pool == "A" else (session_row["current_pick_b"] or 1)

        # Check if there's a bank pick pending for this pool
        bank_pending_col = "bank_pending_a" if pick_pool == "A" else "bank_pending_b"
        try:
            bank_pending_coach_id = session_row[bank_pending_col] or 0
        except (IndexError, KeyError):
            bank_pending_coach_id = 0
        is_bank_pick = bool(bank_pending_coach_id)

        if not is_bank_pick and (not seq or current_pick < 1 or current_pick > len(seq)):
            flash("Draft is complete or pick number is invalid.", "warning")
            return redirect(url_for("draft_live"))

        if seq and 0 < current_pick <= len(seq):
            pick_num, round_idx, _slot_name, _seq_coach_id = seq[current_pick - 1]
        else:
            pick_num, round_idx, _slot_name, _seq_coach_id = 0, 0, "Free Pick", 0

        # Bank pick overrides the on-clock coach; regular pick uses sequence
        coach_id = bank_pending_coach_id if is_bank_pick else _seq_coach_id

        if not is_admin and my_coach_id != coach_id:
            flash("It's not your turn.", "warning")
            return redirect(url_for("draft_live"))

        # Check not already picked within this pool (pools are independent)
        placeholders = ",".join("?" * len(pool_ids))
        existing = db.execute(
            f"SELECT id FROM draft_picks WHERE session_id=? AND pokemon_name=? AND coach_id IN ({placeholders})",
            [session_row["id"], pokemon_name] + list(pool_ids),
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
        poke_tier_label = poke_row["tier_label"] or ""

        mega_names_set = {r["name"] for r in db.execute(
            "SELECT name FROM draft_tiers WHERE is_mega=1"
        ).fetchall()}
        is_mega = pokemon_name in mega_names_set

        # A mega costed at an uber point value (mega_bronze/silver/gold/platinum_pts
        # in settings, e.g. 27/28/29/30) is an uber pick.
        mega_uber_tier = _mega_tier_label(points, settings) if is_mega else ""
        poke_uber_tier = _uber_named(poke_tier_label)

        # An uber point value (27-30) is always an uber pick — no special button
        # needed. The "Uber" toggle on the card is now just a visual cue; clicking
        # plain PICK on a 27-30pt mon still routes it to the uber slot.
        if poke_uber_tier:
            is_uber = True
            effective_uber_tier = poke_uber_tier
        elif mega_uber_tier:
            is_uber = True
            effective_uber_tier = mega_uber_tier
        elif points in UBER_POINTS:
            is_uber = True
            effective_uber_tier = UBER_POINTS[points]
        else:
            is_uber = False
            effective_uber_tier = ""

        # First overall pick must be a regular-tier pokemon (not mega, must have pts ≥ 1)
        if pick_num == 1 and (is_mega or points < 1):
            flash("The first pick must be a regular-tier Pokemon (not Mega).", "warning")
            return redirect(url_for("draft_live"))

        # Enforce max 10 picks per team (8 regular + 2 uber)
        team_pick_count = db.execute(
            "SELECT COUNT(*) FROM pokemon_roster WHERE coach_id=?", (coach_id,)
        ).fetchone()[0]
        if team_pick_count >= 10:
            flash(f"This team already has {team_pick_count} picks (max 10).", "warning")
            return redirect(url_for("draft_live"))

        # ── Plan Griffin validation ──────────────────────────────────────────
        coach_mode_row = db.execute(
            "SELECT draft_mode FROM coaches WHERE id=?", (coach_id,)
        ).fetchone()
        coach_mode = (coach_mode_row["draft_mode"] or "legacy") if coach_mode_row else "legacy"
        ticket_used_val = None

        if is_uber:
            existing_uber = _get_coach_uber_named_tiers(db, coach_id, session_row["id"])
            if not _can_add_uber(existing_uber, effective_uber_tier):
                valid_next = _valid_uber_second_choices(existing_uber)
                if not valid_next:
                    flash("You have already used both uber picks.", "warning")
                else:
                    flash(f"Invalid uber combo. Your next uber must be: {', '.join(sorted(valid_next))}.", "warning")
                return redirect(url_for("draft_live"))
            ticket_used_val = "uber"

        elif coach_mode == "points":
            budget_row = db.execute(
                "SELECT value FROM league_settings WHERE key='points_budget_griffin'"
            ).fetchone()
            budget = int(budget_row["value"]) if budget_row else 70
            spent = db.execute(
                "SELECT COALESCE(SUM(points),0) FROM draft_picks "
                "WHERE session_id=? AND coach_id=? AND slot_name NOT IN ('Uber 1','Uber 2')",
                (session_row["id"], coach_id)
            ).fetchone()[0] or 0
            if spent + points > budget:
                flash(
                    f"Not enough points. {budget - spent} remaining, {pokemon_name} costs {points}pts.",
                    "warning",
                )
                return redirect(url_for("draft_live"))

        elif coach_mode == "tier_tickets":
            poke_tier = _regular_tier_label(points)
            poke_ticket = TIER_TO_TICKET.get(poke_tier)
            if not poke_ticket:
                flash("Cannot determine ticket tier for this Pokémon.", "warning")
                return redirect(url_for("draft_live"))
            chosen_ticket = request.form.get("ticket_used") or poke_ticket
            chosen_rank = TICKET_RANK.get(chosen_ticket, 999)
            poke_rank = TICKET_RANK[poke_ticket]
            if chosen_rank > poke_rank:
                flash("You cannot use a lower-tier ticket on a higher-tier Pokémon.", "warning")
                return redirect(url_for("draft_live"))
            used_rows = db.execute(
                "SELECT ticket_used, COUNT(*) as cnt FROM draft_picks "
                "WHERE session_id=? AND coach_id=? AND ticket_used IS NOT NULL AND ticket_used != 'uber' "
                "GROUP BY ticket_used",
                (session_row["id"], coach_id),
            ).fetchall()
            used_map = {r["ticket_used"]: r["cnt"] for r in used_rows}
            avail = TICKET_ALLOC.get(chosen_ticket, 0) - used_map.get(chosen_ticket, 0)
            if avail <= 0:
                flash(f"No {chosen_ticket} tickets remaining.", "warning")
                return redirect(url_for("draft_live"))
            ticket_used_val = chosen_ticket
        # ────────────────────────────────────────────────────────────────────

        # Auto-assign to the correct roster slot based on actual pokemon tier
        coach_roster = db.execute(
            "SELECT tier, is_free_pick FROM pokemon_roster WHERE coach_id=?", (coach_id,)
        ).fetchall()

        if is_uber:
            existing_uber_count = sum(1 for r in coach_roster if r["tier"] in ("Uber 1", "Uber 2"))
            actual_slot = "Uber 2" if existing_uber_count >= 1 else "Uber 1"
            is_free = False
        else:
            actual_slot, is_free = _auto_slot(pokemon_name, points, mega_names_set, coach_roster)

        db.execute(
            "INSERT INTO draft_picks "
            "(session_id, pick_number, round_number, slot_name, coach_id, pokemon_name, points, ticket_used) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (session_row["id"], pick_num, round_idx + 1, actual_slot, coach_id, pokemon_name, points, ticket_used_val)
        )
        db.execute(
            "INSERT OR IGNORE INTO pokemon_roster (coach_id, pokemon_name, points, tier, is_tera_captain, is_zmove_captain, is_free_pick) VALUES (?,?,?,?,0,0,?)",
            (coach_id, pokemon_name, points, actual_slot, 1 if is_free else 0)
        )
        pick_col = "current_pick_a" if pick_pool == "A" else "current_pick_b"
        if is_bank_pick:
            # Consume the bank pick — clear bank_pending, keep current_pick unchanged
            db.execute(
                f"UPDATE draft_sessions SET {bank_pending_col}=0 WHERE id=?",
                (session_row["id"],)
            )
        else:
            # Advance to next pick in sequence
            db.execute(
                f"UPDATE draft_sessions SET {pick_col}=? WHERE id=?",
                (current_pick + 1, session_row["id"])
            )
            # Check if the coach who just picked has a banked pick to use
            try:
                banked = json.loads(session_row["banked_picks"] or "{}")
            except Exception:
                banked = {}
            if banked.get(str(coach_id), 0) > 0:
                banked[str(coach_id)] -= 1
                db.execute(
                    f"UPDATE draft_sessions SET {bank_pending_col}=?, banked_picks=? WHERE id=?",
                    (coach_id, json.dumps(banked), session_row["id"])
                )

    flash(f"Picked {pokemon_name}!", "success")
    return redirect(url_for("draft_live"))


@app.route("/draft/live/skip", methods=["POST"])
def draft_live_skip():
    if session.get("role") != "admin":
        flash("Admin only.", "warning")
        return redirect(url_for("draft_live"))
    pick_pool = request.form.get("pick_pool", "A")
    with get_db() as db:
        sess = db.execute(
            "SELECT * FROM draft_sessions WHERE status='active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not sess:
            flash("No active draft session.", "warning")
            return redirect(url_for("draft_live"))
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
        rs_str = settings.get("draft_round_structure", "")
        try:
            rs = json.loads(rs_str) if rs_str else DEFAULT_ROUND_STRUCTURE
        except Exception:
            rs = DEFAULT_ROUND_STRUCTURE
        so = json.loads(sess["snake_order"] or "[]")
        coaches_all = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
        p_ids = {c["id"] for c in coaches_all if c["pool"] == pick_pool}
        seq = _get_pool_sequence(so, p_ids, rs)
        pick_col = "current_pick_a" if pick_pool == "A" else "current_pick_b"
        bank_col = "bank_pending_a" if pick_pool == "A" else "bank_pending_b"
        cur = (sess["current_pick_a"] or 1) if pick_pool == "A" else (sess["current_pick_b"] or 1)
        if not seq or cur < 1 or cur > len(seq):
            flash("No current pick slot to skip.", "warning")
            return redirect(url_for("draft_live"))
        slot = seq[cur - 1]
        pick_num, round_idx, slot_name_val, coach_id = slot[0], slot[1], slot[2], slot[3]
        # Record a skip placeholder in draft_picks
        db.execute(
            "INSERT INTO draft_picks (session_id, pick_number, round_number, slot_name, coach_id, pokemon_name, points, ticket_used) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sess["id"], pick_num, round_idx + 1, slot_name_val, coach_id, "(SKIP)", 0, None)
        )
        # Immediately grant a makeup pick by setting bank_pending
        db.execute(
            f"UPDATE draft_sessions SET {pick_col}=?, {bank_col}=? WHERE id=?",
            (cur + 1, coach_id, sess["id"])
        )
        coach_row = next((c for c in coaches_all if c["id"] == coach_id), None)
        cname = coach_row["team_name"] if coach_row else str(coach_id)
        flash(f"Pool {pick_pool} skipped — {cname} will get a makeup pick next turn.", "info")
    return redirect(url_for("draft_live"))


@app.route("/draft/live/status")
def draft_live_status():
    with get_db() as db:
        row = db.execute(
            "SELECT id, current_pick_a, current_pick_b, status FROM draft_sessions "
            "WHERE status IN ('active','paused') ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return {"status": "none", "current_pick_a": 0, "current_pick_b": 0, "session_id": None}
    return {
        "status": row["status"],
        "current_pick_a": row["current_pick_a"] or 1,
        "current_pick_b": row["current_pick_b"] or 1,
        "session_id": row["id"],
    }


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

@app.route("/admin/draft/debug")
@admin_required
def admin_draft_debug():
    import os as _os
    db_path = _os.environ.get("DB_PATH", "NOT SET — using fallback")
    with get_db() as db:
        sessions = db.execute("SELECT * FROM draft_sessions ORDER BY id DESC").fetchall()
        coaches = db.execute("SELECT * FROM coaches").fetchall()
        picks_count = db.execute("SELECT COUNT(*) FROM draft_picks").fetchone()[0]
        active = db.execute(
            "SELECT * FROM draft_sessions WHERE status IN ('active','paused','setup') ORDER BY id DESC LIMIT 1"
        ).fetchone()
    import glob as _glob
    import sqlite3 as _sqlite3
    db_exists = _os.path.exists(db_path) if db_path != "NOT SET — using fallback" else "N/A"
    search_paths = _glob.glob("/home/zcs55397/**/*.db", recursive=True)

    other_db_info = []
    for other_path in search_paths:
        if other_path == db_path:
            continue
        try:
            conn = _sqlite3.connect(other_path)
            conn.row_factory = _sqlite3.Row
            c = conn.execute("SELECT COUNT(*) FROM coaches").fetchone()[0]
            s = conn.execute("SELECT COUNT(*) FROM draft_sessions").fetchone()[0]
            p = conn.execute("SELECT COUNT(*) FROM draft_picks").fetchone()[0]
            sess_list = conn.execute("SELECT name, status, season FROM draft_sessions ORDER BY id DESC LIMIT 3").fetchall()
            conn.close()
            other_db_info.append(f"  {other_path}: coaches={c} sessions={s} picks={p} recent={[(r['name'],r['status'],r['season']) for r in sess_list]}")
        except Exception as e:
            other_db_info.append(f"  {other_path}: ERROR {e}")

    lines = [
        f"DB_PATH env: {db_path}",
        f"DB file exists: {db_exists}",
        f"Current DB: coaches={len(coaches)} sessions={len(sessions)} picks={picks_count}",
        "",
        "Other .db files:",
    ] + other_db_info + [
        "",
        f"active_session query result: {dict(active) if active else None}",
        "",
        f"All sessions ({len(sessions)}):",
    ]
    for s in sessions:
        lines.append(f"  id={s['id']} name={s['name']!r} status={s['status']} season={s['season']}")
    lines.append(f"\nCoaches ({len(coaches)}):")
    for c in coaches:
        lines.append(f"  id={c['id']} pool={c['pool']} name={c['team_name']}")
    return "<pre style='font-size:14px;padding:20px;'>" + "\n".join(lines) + "</pre>"


@app.route("/admin/draft", methods=["GET", "POST"])
@admin_required
def admin_draft():
    with get_db() as db:
        coaches = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
        sessions = db.execute("SELECT * FROM draft_sessions ORDER BY id DESC").fetchall()
        active_session = db.execute(
            "SELECT * FROM draft_sessions WHERE status IN ('active','paused','setup') ORDER BY id DESC LIMIT 1"
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
                    "INSERT INTO draft_sessions (name, season, status, snake_order, current_round, current_pick, current_pick_a, current_pick_b) VALUES (?,?,?,?,?,?,?,?)",
                    (name, season, "setup", snake_json, 1, 1, 1, 1)
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
                db.execute("UPDATE draft_sessions SET status='active', current_pick=1, current_pick_a=1, current_pick_b=1 WHERE id=?", (sid,))
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
                sess_row = db.execute("SELECT * FROM draft_sessions WHERE id=?", (sid,)).fetchone()
                # Collect coach IDs from picks (may already be deleted) + snake_order
                drafted_coach_ids = {
                    r[0] for r in db.execute(
                        "SELECT DISTINCT coach_id FROM draft_picks WHERE session_id=?", (sid,)
                    ).fetchall()
                }
                try:
                    so = json.loads(sess_row["snake_order"] or "[]") if sess_row else []
                    drafted_coach_ids |= set(so)
                except Exception:
                    pass
                db.execute(
                    "UPDATE draft_sessions SET status='setup', current_pick=1, current_round=1, "
                    "current_pick_a=1, current_pick_b=1, bank_pending_a=0, bank_pending_b=0, "
                    "banked_picks='{}' WHERE id=?",
                    (sid,)
                )
                db.execute("DELETE FROM draft_picks WHERE session_id=?", (sid,))
                if drafted_coach_ids:
                    ph = ",".join("?" * len(drafted_coach_ids))
                    db.execute(f"DELETE FROM pokemon_roster WHERE coach_id IN ({ph})", list(drafted_coach_ids))
            flash("Draft reset — picks and rosters cleared.", "warning")

        elif action == "discard_session":
            sid = request.form.get("session_id")
            with get_db() as db:
                db.execute("UPDATE draft_sessions SET status='completed' WHERE id=?", (sid,))
            flash("Session discarded.", "warning")

        elif action == "set_pick":
            sid = request.form.get("session_id")
            pick_pool = request.form.get("pick_pool", "A")
            try:
                pick_num = int(request.form.get("pick_number", 1))
            except ValueError:
                pick_num = 1
            col = "current_pick_a" if pick_pool == "A" else "current_pick_b"
            with get_db() as db:
                db.execute(f"UPDATE draft_sessions SET {col}=? WHERE id=?", (pick_num, sid))
            flash(f"Pool {pick_pool} pick set to {pick_num}.", "success")

        elif action == "update_snake":
            sid = request.form.get("session_id")
            # Accept separate per-pool ordered lists: pool_a_order[] and pool_b_order[]
            a_ids = request.form.getlist("pool_a_order")
            b_ids = request.form.getlist("pool_b_order")
            if a_ids or b_ids:
                combined = [int(x) for x in (a_ids + b_ids) if x]
            else:
                combined = [int(x) for x in request.form.getlist("snake_order") if x]
            snake_json = json.dumps(combined)
            with get_db() as db:
                db.execute("UPDATE draft_sessions SET snake_order=? WHERE id=?", (snake_json, sid))
            flash("Draft order updated.", "success")

        elif action == "skip_pick":
            sid = request.form.get("session_id")
            pick_pool = request.form.get("pick_pool", "A")
            with get_db() as db:
                sess = db.execute("SELECT * FROM draft_sessions WHERE id=?", (sid,)).fetchone()
                coaches_all = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
                rs_str = settings.get("draft_round_structure", "")
                try:
                    rs = json.loads(rs_str) if rs_str else DEFAULT_ROUND_STRUCTURE
                except Exception:
                    rs = DEFAULT_ROUND_STRUCTURE
                so = json.loads(sess["snake_order"] or "[]")
                p_ids = {c["id"] for c in coaches_all if c["pool"] == pick_pool}
                seq = _get_pool_sequence(so, p_ids, rs)
                col = "current_pick_a" if pick_pool == "A" else "current_pick_b"
                cur = (sess["current_pick_a"] or 1) if pick_pool == "A" else (sess["current_pick_b"] or 1)
                if seq and 0 < cur <= len(seq):
                    slot = seq[cur - 1]
                    coach_id = slot[3]
                    tier = slot[2]
                    pick_num = slot[0]
                    db.execute(
                        "INSERT INTO draft_picks (session_id, pick_number, coach_id, pokemon_name, tier, is_free_pick, ticket_used) VALUES (?,?,?,?,?,?,?)",
                        (sid, pick_num, coach_id, "(SKIP)", tier, 0, None)
                    )
                    db.execute(f"UPDATE draft_sessions SET {col}=? WHERE id=?", (cur + 1, sid))
                    flash(f"Pool {pick_pool} pick skipped — blank placeholder recorded.", "info")
                else:
                    flash("No current pick slot found.", "warning")

        elif action == "undo_pick":
            sid = request.form.get("session_id")
            pick_pool = request.form.get("pick_pool", "A")
            col = "current_pick_a" if pick_pool == "A" else "current_pick_b"
            with get_db() as db:
                sess = db.execute("SELECT * FROM draft_sessions WHERE id=?", (sid,)).fetchone()
                cur = (sess["current_pick_a"] or 1) if pick_pool == "A" else (sess["current_pick_b"] or 1)
                if cur > 1:
                    coaches_all = db.execute("SELECT * FROM coaches ORDER BY pool, id").fetchall()
                    p_ids = {c["id"] for c in coaches_all if c["pool"] == pick_pool}
                    # Find the last pick for this pool and delete it
                    last = db.execute(
                        "SELECT * FROM draft_picks WHERE session_id=? AND coach_id IN ({}) ORDER BY pick_number DESC LIMIT 1".format(
                            ",".join("?" * len(p_ids))
                        ),
                        (sid, *list(p_ids))
                    ).fetchone()
                    if last:
                        db.execute("DELETE FROM draft_picks WHERE id=?", (last["id"],))
                    db.execute(f"UPDATE draft_sessions SET {col}=? WHERE id=?", (cur - 1, sid))
                    # Also remove from pokemon_roster if it exists there
                    if last and last["pokemon_name"] != "(SKIP)":
                        db.execute(
                            "DELETE FROM pokemon_roster WHERE coach_id=? AND pokemon_name=?",
                            (last["coach_id"], last["pokemon_name"])
                        )
                    flash(f"Pool {pick_pool} last pick undone.", "success")
                else:
                    flash("No picks to undo.", "warning")

        return redirect(url_for("admin_draft"))

    # Build live draft data when session is active
    coaches_map = {c["id"]: dict(c) for c in coaches}
    active_snake = []
    grid_a = grid_b = {}
    max_a = max_b = {}
    current_slot_a = current_slot_b = None
    current_coach_a_id = current_coach_b_id = None
    current_pick_a = current_pick_b = 1
    last_pick_a = last_pick_b = None
    coaches_draft_states = {}
    avail_pokemon_a = avail_pokemon_b = []
    coaches_a = [c for c in coaches if c["pool"] == "A"]
    coaches_b = [c for c in coaches if c["pool"] == "B"]
    snake_ids = []

    if active_session:
        snake_ids = json.loads(active_session["snake_order"] or "[]")
        active_snake = [coaches_map[cid] for cid in snake_ids if cid in coaches_map]
        snake_pos = {cid: i for i, cid in enumerate(snake_ids)}
        coaches_a = sorted(coaches_a, key=lambda c: snake_pos.get(c["id"], 999))
        coaches_b = sorted(coaches_b, key=lambda c: snake_pos.get(c["id"], 999))

        with get_db() as db:
            picks = db.execute(
                "SELECT * FROM draft_picks WHERE session_id=? ORDER BY pick_number",
                (active_session["id"],)
            ).fetchall()
            pool_a_ids = {c["id"] for c in coaches_a}
            pool_b_ids = {c["id"] for c in coaches_b}

            seq_a = _get_pool_sequence(snake_ids, pool_a_ids, round_structure)
            seq_b = _get_pool_sequence(snake_ids, pool_b_ids, round_structure)

            current_pick_a = active_session["current_pick_a"] or 1
            current_pick_b = active_session["current_pick_b"] or 1

            current_slot_a = seq_a[current_pick_a - 1] if seq_a and 0 < current_pick_a <= len(seq_a) else None
            current_slot_b = seq_b[current_pick_b - 1] if seq_b and 0 < current_pick_b <= len(seq_b) else None
            current_coach_a_id = current_slot_a[3] if current_slot_a else None
            current_coach_b_id = current_slot_b[3] if current_slot_b else None

            picked_names_a = {p["pokemon_name"] for p in picks if p["coach_id"] in pool_a_ids}
            picked_names_b = {p["pokemon_name"] for p in picks if p["coach_id"] in pool_b_ids}
            all_draft = db.execute(
                "SELECT * FROM draft_tiers WHERE is_banned != 1 ORDER BY points DESC, name"
            ).fetchall()
            def _tl(p):
                db_lbl = p["tier_label"] or ""
                pts = p["points"] or 0
                named = _uber_named(db_lbl)
                if named:
                    return named
                if pts in UBER_POINTS:
                    return UBER_POINTS[pts]
                return _regular_tier_label(pts) or db_lbl
            avail_pokemon_a = [dict(p, tier_label=_tl(p)) for p in all_draft if p["name"] not in picked_names_a]
            avail_pokemon_b = [dict(p, tier_label=_tl(p)) for p in all_draft if p["name"] not in picked_names_b]

            # Build roster grid
            try:
                roster_rows = db.execute("""
                    SELECT pr.*, COALESCE(dt.tier_label,'') as poke_tier_label
                    FROM pokemon_roster pr
                    LEFT JOIN draft_tiers dt ON LOWER(pr.pokemon_name) = LOWER(dt.name)
                """).fetchall()
            except Exception:
                roster_rows = []
            _rkeys = roster_rows[0].keys() if roster_rows else []
            _uber_c = {}
            roster_picks = []
            for r in roster_rows:
                tier = r["tier"]
                if tier not in TIER_ORDER and _uber_named(r["poke_tier_label"]):
                    cid = r["coach_id"]
                    cnt = _uber_c.get(cid, 0)
                    tier = "Uber 2" if cnt >= 1 else "Uber 1"
                    _uber_c[cid] = cnt + 1
                pick_info = next((p for p in picks if p["coach_id"] == r["coach_id"] and p["pokemon_name"] == r["pokemon_name"]), None)
                try:
                    roster_picks.append({
                        "coach_id": r["coach_id"], "pokemon_name": r["pokemon_name"],
                        "points": r["points"], "tier": tier,
                        "poke_tier_label": r["poke_tier_label"],
                        "is_tera_captain": int(r["is_tera_captain"]) if "is_tera_captain" in _rkeys and r["is_tera_captain"] else 0,
                        "is_zmove_captain": int(r["is_zmove_captain"]) if "is_zmove_captain" in _rkeys and r["is_zmove_captain"] else 0,
                        "is_free_pick": (r["is_free_pick"] or 0) if "is_free_pick" in _rkeys else 0,
                        "ticket_used": (pick_info["ticket_used"] if pick_info else None) or "",
                    })
                except Exception:
                    pass

            grid_a, max_a = _build_draft_grid(coaches_a, roster_picks)
            grid_b, max_b = _build_draft_grid(coaches_b, roster_picks)
            coaches_draft_states = {
                c["id"]: _get_coach_draft_state(db, c["id"], active_session["id"])
                for c in coaches
            }
            last_pick_a = next((p for p in reversed(picks) if p["coach_id"] in pool_a_ids), None)
            last_pick_b = next((p for p in reversed(picks) if p["coach_id"] in pool_b_ids), None)

    # Per-pool snake order for the editor
    snake_a = [coaches_map[cid] for cid in snake_ids if cid in coaches_map and coaches_map[cid]["pool"] == "A"] if active_session else []
    snake_b = [coaches_map[cid] for cid in snake_ids if cid in coaches_map and coaches_map[cid]["pool"] == "B"] if active_session else []
    # Coaches not yet in snake order (for new sessions)
    in_order_ids = set(snake_ids) if active_session else set()
    coaches_not_ordered_a = [c for c in coaches_a if c["id"] not in in_order_ids]
    coaches_not_ordered_b = [c for c in coaches_b if c["id"] not in in_order_ids]

    from flask import make_response
    resp = make_response(render_template(
        "admin/draft.html",
        coaches=coaches,
        coaches_a=coaches_a,
        coaches_b=coaches_b,
        coaches_map=coaches_map,
        sessions=sessions,
        active_session=dict(active_session) if active_session else None,
        active_snake=active_snake,
        snake_a=snake_a,
        snake_b=snake_b,
        coaches_not_ordered_a=coaches_not_ordered_a,
        coaches_not_ordered_b=coaches_not_ordered_b,
        grid_a=grid_a, grid_b=grid_b,
        max_a=max_a, max_b=max_b,
        tier_order=TIER_ORDER,
        coaches_draft_states=coaches_draft_states,
        current_slot_a=current_slot_a,
        current_slot_b=current_slot_b,
        current_coach_a_id=current_coach_a_id,
        current_coach_b_id=current_coach_b_id,
        current_pick_a=current_pick_a,
        current_pick_b=current_pick_b,
        last_pick_a=dict(last_pick_a) if last_pick_a else None,
        last_pick_b=dict(last_pick_b) if last_pick_b else None,
        avail_pokemon_a=avail_pokemon_a,
        avail_pokemon_b=avail_pokemon_b,
        ticket_alloc=TICKET_ALLOC,
        mechanic_tera=settings.get("mechanic_tera", "0"),
        mechanic_zmove=settings.get("mechanic_zmove", "0"),
        round_structure=round_structure,
        round_structure_json=json.dumps(round_structure, indent=2),
        league_name=settings.get("league_name", "Pokemon Draft League"),
    ))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


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
            "SELECT id, coach_name, team_name, color, logo_url FROM coaches ORDER BY coach_name"
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
        pickem_rows = db.execute("""
            SELECT s.coach1_id, s.coach2_id, s.week,
                   SUM(CASE WHEN pv.picked_coach_id = s.coach1_id THEN 1 ELSE 0 END) AS c1_votes,
                   COUNT(*) AS total_votes
            FROM schedule s
            JOIN pickem_votes pv ON pv.match_id = s.id
            GROUP BY s.id
        """).fetchall()

    pickem_map = {}
    for r in pickem_rows:
        c1, c2, total = r["coach1_id"], r["coach2_id"], r["total_votes"] or 0
        c1_pct = round(r["c1_votes"] / total * 100) if total > 0 else 50
        key = f"{min(c1, c2)}_{max(c1, c2)}"
        pickem_map[key] = {
            "c1_id": c1, "c2_id": c2,
            "c1_pct": c1_pct, "c2_pct": 100 - c1_pct,
            "total": total, "week": r["week"],
        }

    pokedex_map = {r["pokeapi_name"]: r for r in pokedex_rows}

    coaches_data = {}
    for c in coaches:
        coaches_data[c["id"]] = {
            "id": c["id"],
            "name": c["coach_name"],
            "team_name": c["team_name"] or c["coach_name"],
            "color": c["color"] or "#6b7280",
            "logo_url": c["logo_url"] or "",
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
            "sprite_anim": pokemon_sprite_url(r["pokemon_name"]),
        })

    return render_template(
        "battle_prep.html",
        coaches_json=json.dumps(list(coaches_data.values())),
        pickem_json=json.dumps(pickem_map),
        league_name=settings.get("league_name", "Pokemon Draft League"),
    )


@app.route("/api/pokepaste", methods=["POST"])
def api_pokepaste():
    """Proxy a team paste to pokepast.es and return the resulting URL."""
    import urllib.request as _ur
    import urllib.parse as _up
    data = request.get_json(silent=True) or {}
    paste_text = (data.get("paste") or "").strip()
    title      = (data.get("title") or "Battle Team").strip()
    author     = (data.get("author") or "").strip()
    if not paste_text:
        return jsonify({"error": "No paste provided"}), 400
    payload = _up.urlencode({
        "paste":  paste_text,
        "title":  title,
        "author": author,
        "notes":  "",
    }).encode("utf-8")
    try:
        req = _ur.Request(
            "https://pokepast.es/api/new",
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "YuriDraftLeague/1.0",
            },
        )
        with _ur.urlopen(req, timeout=12) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        url = result.get("url") or result.get("link") or ""
        if not url:
            return jsonify({"error": "pokepast.es returned no URL", "raw": result}), 502
        return jsonify({"url": url})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


_CALC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "calc")


@app.route("/damage-calc")
@app.route("/damage-calc/")
def damage_calc():
    """Render the damage calculator inside the site's nav/chrome."""
    with get_db() as db:
        settings = {r["key"]: r["value"] for r in db.execute("SELECT * FROM league_settings").fetchall()}
    return render_template("damage_calc.html",
                           league_name=settings.get("league_name", "Pokemon Draft League"))


@app.route("/damage-calc/<path:filename>")
def damage_calc_assets(filename):
    """Serve all calc assets: styles/, js/, data/sets/, tweaks-panel.jsx."""
    return send_from_directory(_CALC_DIR, filename)


@app.route("/api/calc/teams")
def api_calc_teams():
    """Return all league teams with their current-season drafted Pokémon roster for the damage calc team picker."""
    with get_db() as db:
        coaches = db.execute(
            "SELECT id, team_name, coach_name, pool, logo_url FROM coaches ORDER BY pool, team_name"
        ).fetchall()

        # Fetch all rosters in one query (much faster than N+1 per coach)
        all_roster = db.execute(
            "SELECT coach_id, pokemon_name FROM pokemon_roster ORDER BY pokemon_name"
        ).fetchall()
        roster_map = {}
        for r in all_roster:
            roster_map.setdefault(r["coach_id"], []).append(r["pokemon_name"])

        teams = []
        for c in coaches:
            teams.append({
                "id": c["id"],
                "team": c["team_name"],
                "coach": c["coach_name"],
                "pool": c["pool"] or "",
                "logo": c["logo_url"] or "",
                "pokemon": roster_map.get(c["id"], []),
            })
    return jsonify(teams)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
