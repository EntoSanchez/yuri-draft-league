"""
Scrapes pokemondb.net for each utility move and updates draft_tiers.moves
in the local league.db with any missing moves for pokemon in the draft pool.

Usage:
    python scripts/update_moves.py            # dry run — shows what would change
    python scripts/update_moves.py --apply    # writes changes to DB
"""

import sqlite3
import time
import sys
import re
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DB_PATH = Path(__file__).parent.parent / "league.db"

# Canonical move name  →  pokemondb slug
UTILITY_MOVES = {
    # Hazards
    "Stealth Rock": "stealth-rock",
    "Spikes": "spikes",
    "Toxic Spikes": "toxic-spikes",
    "Sticky Web": "sticky-web",
    "Ceaseless Edge": "ceaseless-edge",
    "Stone Axe": "stone-axe",
    # Removal
    "Rapid Spin": "rapid-spin",
    "Defog": "defog",
    "Court Change": "court-change",
    "Mortal Spin": "mortal-spin",
    "Steel Roller": "steel-roller",
    "Ice Spinner": "ice-spinner",
    # Recovery
    "Recover": "recover",
    "Roost": "roost",
    "Slack Off": "slack-off",
    "Soft-Boiled": "soft-boiled",
    "Shore Up": "shore-up",
    "Heal Order": "heal-order",
    "Moonlight": "moonlight",
    "Synthesis": "synthesis",
    "Morning Sun": "morning-sun",
    "Wish": "wish",
    "Healing Wish": "healing-wish",
    "Jungle Healing": "jungle-healing",
    "Milk Drink": "milk-drink",
    "Life Dew": "life-dew",
    "Leech Seed": "leech-seed",
    "Aqua Ring": "aqua-ring",
    "Pain Split": "pain-split",
    "Rest": "rest",
    "Strength Sap": "strength-sap",
    "Floral Healing": "floral-healing",
    # Support
    "Trick Room": "trick-room",
    "Tailwind": "tailwind",
    "Helping Hand": "helping-hand",
    "Follow Me": "follow-me",
    "Rage Powder": "rage-powder",
    "Wide Guard": "wide-guard",
    "Quick Guard": "quick-guard",
    "Fake Out": "fake-out",
    "Safeguard": "safeguard",
    "Light Screen": "light-screen",
    "Reflect": "reflect",
    "Aurora Veil": "aurora-veil",
    "Aromatherapy": "aromatherapy",
    "Heal Bell": "heal-bell",
    "Misty Terrain": "misty-terrain",
    "Electric Terrain": "electric-terrain",
    "Grassy Terrain": "grassy-terrain",
    "Psychic Terrain": "psychic-terrain",
    "Magic Coat": "magic-coat",
    "Encore": "encore",
    "Taunt": "taunt",
    "Imprison": "imprison",
    "Gravity": "gravity",
    "Ally Switch": "ally-switch",
    "After You": "after-you",
    "Baton Pass": "baton-pass",
    "Pollen Puff": "pollen-puff",
    "Coaching": "coaching",
    # Status
    "Thunder Wave": "thunder-wave",
    "Will-O-Wisp": "will-o-wisp",
    "Toxic": "toxic",
    "Nuzzle": "nuzzle",
    "Stun Spore": "stun-spore",
    "Sleep Powder": "sleep-powder",
    "Spore": "spore",
    "Hypnosis": "hypnosis",
    "Yawn": "yawn",
    "Glare": "glare",
    "Confuse Ray": "confuse-ray",
    "Acid Spray": "acid-spray",
    "Snarl": "snarl",
    "Screech": "screech",
    "Charm": "charm",
    "Breaking Swipe": "breaking-swipe",
    "Eerie Impulse": "eerie-impulse",
    "Chilling Water": "chilling-water",
    "Alluring Voice": "alluring-voice",
    "Fake Tears": "fake-tears",
    "Icy Wind": "icy-wind",
    "Electroweb": "electroweb",
    "Bulldoze": "bulldoze",
    "Super Fang": "super-fang",
    # Momentum
    "U-turn": "u-turn",
    "Volt Switch": "volt-switch",
    "Flip Turn": "flip-turn",
    "Teleport": "teleport",
    "Parting Shot": "parting-shot",
    "Shed Tail": "shed-tail",
    "Chilly Reception": "chilly-reception",
    "Memento": "memento",
    # Priority
    "Extreme Speed": "extreme-speed",
    "Quick Attack": "quick-attack",
    "Mach Punch": "mach-punch",
    "Ice Shard": "ice-shard",
    "Bullet Punch": "bullet-punch",
    "Aqua Jet": "aqua-jet",
    "Shadow Sneak": "shadow-sneak",
    "Sucker Punch": "sucker-punch",
    "First Impression": "first-impression",
    "Water Shuriken": "water-shuriken",
    "Grassy Glide": "grassy-glide",
    "Accelerock": "accelerock",
    "Jet Punch": "jet-punch",
    "Vacuum Wave": "vacuum-wave",
    "Upper Hand": "upper-hand",
    # Phasing
    "Whirlwind": "whirlwind",
    "Roar": "roar",
    "Dragon Tail": "dragon-tail",
    "Circle Throw": "circle-throw",
    "Haze": "haze",
    "Perish Song": "perish-song",
    "Clear Smog": "clear-smog",
    # Trap
    "Mean Look": "mean-look",
    "Block": "block",
    "Spider Web": "spider-web",
    "Infestation": "infestation",
    "Wrap": "wrap",
    "Fire Spin": "fire-spin",
    "Whirlpool": "whirlpool",
    "Bind": "bind",
    "Sand Tomb": "sand-tomb",
    "Thunder Cage": "thunder-cage",
    "Octolock": "octolock",
    # Tactical
    "Knock Off": "knock-off",
    "Trick": "trick",
    "Switcheroo": "switcheroo",
    "Skill Swap": "skill-swap",
    "Fling": "fling",
    "Thief": "thief",
    "Covet": "covet",
    "Foul Play": "foul-play",
    "Brick Break": "brick-break",
    "Psychic Noise": "psychic-noise",
    "Recycle": "recycle",
    # Setup
    "Swords Dance": "swords-dance",
    "Nasty Plot": "nasty-plot",
    "Calm Mind": "calm-mind",
    "Dragon Dance": "dragon-dance",
    "Shell Smash": "shell-smash",
    "Quiver Dance": "quiver-dance",
    "Belly Drum": "belly-drum",
    "Agility": "agility",
    "Rock Polish": "rock-polish",
    "Autotomize": "autotomize",
    "Bulk Up": "bulk-up",
    "Coil": "coil",
    "Iron Defense": "iron-defense",
    "Curse": "curse",
    "Cotton Guard": "cotton-guard",
    "Amnesia": "amnesia",
    "Work Up": "work-up",
    "Hone Claws": "hone-claws",
    "Shift Gear": "shift-gear",
    "Gear Up": "gear-up",
    "Power-Up Punch": "power-up-punch",
    "Victory Dance": "victory-dance",
    "Clangorous Soul": "clangorous-soul",
    "Tail Glow": "tail-glow",
    "Trailblaze": "trailblaze",
    "Howl": "howl",
    "Cosmic Power": "cosmic-power",
    "Body Press": "body-press",
    "Acid Armor": "acid-armor",
    "Geomancy": "geomancy",
    "Stockpile": "stockpile",
    "Relic Song": "relic-song",
    # Weather
    "Rain Dance": "rain-dance",
    "Sunny Day": "sunny-day",
    "Sandstorm": "sandstorm",
    "Hail": "hail",
    # Terrain attacks
    "Expanding Force": "expanding-force",
    "Rising Voltage": "rising-voltage",
    "Misty Explosion": "misty-explosion",
    # Doubles
    "Protect": "protect",
    "Feint": "feint",
    "Beat Up": "beat-up",
    "Instruct": "instruct",
    "Heal Pulse": "heal-pulse",
    "Self-Destruct": "self-destruct",
    "Explosion": "explosion",
    "Final Gambit": "final-gambit",
    "Dragon Cheer": "dragon-cheer",
}


def extract_learner_names(soup: BeautifulSoup) -> set[str]:
    """Extract all pokemon names from infocards on a move page.

    pokemondb infocard structure:
      <div class="infocard">
        <span class="infocard-md-data">
          <a class="ent-name">Geodude</a>
          <small class="text-muted">Alolan Geodude</small>   ← form name (optional)
          <small class="text-muted">#0074 / Rock ...</small>
        </span>
      </div>

    If a second <small> starts with a form name (no "#"), use that; otherwise use ent-name.
    """
    learners = set()
    for card in soup.select(".infocard"):
        ent_a = card.select_one("a.ent-name")
        if not ent_a:
            continue
        base_name = ent_a.get_text(strip=True)

        # Look for a form-name small (does not contain "#")
        form_name = None
        for sm in card.select("small.text-muted"):
            txt = sm.get_text(strip=True)
            if txt and "#" not in txt and "/" not in txt:
                form_name = txt
                break

        name = form_name if form_name else base_name
        learners.add(name.lower())
    return learners


def fetch_move_learners(move_name: str, slug: str, session: requests.Session) -> set[str]:
    url = f"https://pokemondb.net/move/{slug}"
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  WARN: {slug}: {e}")
        return set()
    soup = BeautifulSoup(r.text, "html.parser")
    return extract_learner_names(soup)


def normalize(name: str) -> str:
    return name.lower().strip()


def main():
    apply = "--apply" in sys.argv
    db_path = DB_PATH
    for i, arg in enumerate(sys.argv):
        if arg == "--db" and i + 1 < len(sys.argv):
            db_path = sys.argv[i + 1]
    print(f"Using DB: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Build draft pool: lower_name → original_name
    draft_pool: dict[str, str] = {}
    for row in cur.execute("SELECT name FROM draft_tiers WHERE is_banned != 1"):
        draft_pool[normalize(row["name"])] = row["name"]

    # Current moves per pokemon: original_name → set of move names (lowercased)
    current_moves: dict[str, set[str]] = {}
    for row in cur.execute("SELECT name, moves FROM draft_tiers WHERE is_banned != 1"):
        mvs = {m.strip().lower() for m in (row["moves"] or "").split("|") if m.strip()}
        current_moves[row["name"]] = mvs

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (draft-league-move-updater/1.0)"

    # pokemon original_name → list of moves to add
    to_add: dict[str, list[str]] = {}

    total = len(UTILITY_MOVES)
    for i, (move_name, slug) in enumerate(UTILITY_MOVES.items(), 1):
        print(f"[{i}/{total}] {move_name}...", flush=True, end="")
        learners = fetch_move_learners(move_name, slug, session)
        if not learners:
            print(" (no learners found)")
            time.sleep(0.4)
            continue

        missing_mons = []
        for lower_db, orig_db in draft_pool.items():
            if lower_db not in learners:
                continue
            # Pokemon is a learner — check if move already in DB
            if move_name.lower() not in current_moves.get(orig_db, set()):
                missing_mons.append(orig_db)
                to_add.setdefault(orig_db, []).append(move_name)

        print(f" {len(learners)} learners, {len(missing_mons)} new" if missing_mons else f" {len(learners)} learners")
        time.sleep(0.4)

    print("\n" + "=" * 60)
    print("SUMMARY — moves to add to DB")
    print("=" * 60)
    for mon, moves in sorted(to_add.items()):
        print(f"  {mon}: + {', '.join(moves)}")
    total_adds = sum(len(v) for v in to_add.values())
    print(f"\nTotal: {total_adds} additions across {len(to_add)} pokemon")

    if not apply:
        print("\nDry run — pass --apply to write to DB.")
        conn.close()
        return

    print("\nApplying...")
    for mon, new_moves in to_add.items():
        orig_moves_raw = cur.execute(
            "SELECT moves FROM draft_tiers WHERE name = ?", (mon,)
        ).fetchone()["moves"] or ""
        existing = [m for m in orig_moves_raw.split("|") if m.strip()]
        existing_lower = {m.lower() for m in existing}
        to_append = [m for m in new_moves if m.lower() not in existing_lower]
        merged = existing + to_append
        conn.execute(
            "UPDATE draft_tiers SET moves = ? WHERE name = ?",
            ("|".join(merged), mon),
        )
    conn.commit()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
