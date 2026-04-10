# Yuri Draft League — Claude Project Guidelines

## Project Overview
Flask/SQLite web app for managing a Pokemon draft league. Hosted on PythonAnywhere.

- **Local path:** `D:/Yuri Draft League/`
- **GitHub:** `EntoSanchez/yuri-draft-league` (main branch)
- **Live URL:** `https://zcs55397.pythonanywhere.com`
- **PythonAnywhere username:** `zcs55397`
- **Server path:** `/home/zcs55397/yuri-draft-league/`
- **Database:** `/home/zcs55397/yuri-draft-league/yuri-draft-league/league.db` (nested dir — do NOT move it)

## Deploying Changes

Always follow this workflow:
1. Edit locally in `D:/Yuri Draft League/`
2. Commit and push: `git add <files> && git commit && git push origin HEAD`
3. On PythonAnywhere bash console:
   ```bash
   cd /home/zcs55397/yuri-draft-league
   git fetch origin && git reset --hard origin/main
   touch /var/www/zcs55397_pythonanywhere_com_wsgi.py
   ```
4. Hard refresh browser (Ctrl+Shift+R)

## WSGI Configuration
File: `/var/www/zcs55397_pythonanywhere_com_wsgi.py`
```python
import sys, os
path = '/home/zcs55397/yuri-draft-league'
if path not in sys.path:
    sys.path.insert(0, path)
os.environ['DB_PATH'] = '/home/zcs55397/yuri-draft-league/yuri-draft-league/league.db'
from app import app as application
```

## Key Architecture

### Database (`league.db`)
Main tables: `coaches`, `schedule`, `pokemon_roster`, `draft_tiers`, `pokedex`, `pokemon_db`,
`league_settings`, `pickem_votes`, `users`, `seasons`, `match_stats`, `transactions`

- `schedule`: `week, pool, coach1_id, coach2_id, score1, score2`
- `draft_tiers`: `name, points, tier_label, ability1/2/3, moves, type1/2, hp/atk/defense/spa/spd/spe/bst`
- `pokedex`: `pokeapi_name, display_name, type1/2, hp/atk/def_stat/spa/spd/spe, pokeapi_id`
- `league_settings`: key/value pairs (see Settings section)
- `pickem_votes`: `voter_name, week, match_id, picked_coach_id` (UNIQUE on voter+week+match)

### Sprite System
```python
SPRITE_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/showdown"
SHOWDOWN_ANI = "https://play.pokemonshowdown.com/sprites/ani"        # slug-based animated
SHOWDOWN_STATIC = "https://play.pokemonshowdown.com/sprites/gen5"   # slug-based static
```
- `_pokemon_id_map`: loaded at startup from `pokemon_db` (name→numeric ID). Reload web app after running `fetch_pokemon_db.py`.
- `_name_to_slug()` returns: `[regional_slug, mega_slug, primal_slug, alias, naive]` — first valid slug used for Showdown CDN fallback
- Fallback chain: PokeAPI GitHub (numeric ID) → Showdown animated CDN → Showdown static CDN

### Settings (league_settings table)
Key settings:
- `mechanic_mega`: `'0'` or `'1'` — whether Mega tier is active
- `draft_free_pick_type`: `'none'` | `'one_per_tier'` | `'four_any'`
- `uber_combination`: comma-separated string e.g. `'2_bronze,1_platinum'`
- `league_name`: display name

### Static Files
- `static/logos/` — team logo uploads (also at `/home/zcs55397/yuri-draft-league/yuri-draft-league/static/logos/` on server)
- `static/calc/` — damage calculator dist files (copied from `damage-calc/dist/` since damage-calc has its own `.git`)
- `static/favicon.jpg` — Yuri Cup logo

## Python Environment
Uses `uv` with `.venv`. On PythonAnywhere uses the server's venv at `.venv/bin/activate`.

## Utility Scripts
- `fetch_abilities.py` — fetches abilities from PokeAPI for all draft_tiers pokemon
- `fetch_pokemon_db.py` — populates `pokemon_db` table with PokeAPI ID mappings (run then reload web app)
- `fetch_pokedex.py` — populates `pokedex` table
- `migrate_settings.py` — one-time settings migrations

## Known Gotchas
- **Never hardcode Windows paths** — use `os.path.dirname(os.path.abspath(__file__))` for DB_PATH
- **DB is in nested dir on server** — `/yuri-draft-league/yuri-draft-league/league.db` (historical artifact)
- **Logos live in nested dir too** — copy new logos: `cp -r .../yuri-draft-league/static/logos /home/zcs55397/yuri-draft-league/static/`
- **damage-calc/** has its own `.git` — never track as subdirectory; copy dist files to `static/calc/` instead
- **Tailwind via CDN** — no build step needed, all classes available
- **`enumerate` filter** registered manually: `app.jinja_env.globals["enumerate"] = enumerate`
