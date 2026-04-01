"""
Initialize the Yuri Cup draft league database.
Run once to create the schema and set up the admin user.
"""
import sqlite3
import hashlib
import sys

DB_PATH = "D:/Yuri Draft League/league.db"


def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS league_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS coaches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coach_name TEXT NOT NULL,
            team_name TEXT NOT NULL,
            pool TEXT DEFAULT 'A',
            color TEXT DEFAULT '#3b82f6',
            logo_url TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS pokemon_roster (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coach_id INTEGER NOT NULL,
            pokemon_name TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            tier TEXT DEFAULT '',
            is_tera_captain INTEGER DEFAULT 0,
            FOREIGN KEY (coach_id) REFERENCES coaches(id)
        );

        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week INTEGER NOT NULL,
            pool TEXT DEFAULT 'A',
            coach1_id INTEGER NOT NULL,
            coach2_id INTEGER NOT NULL,
            score1 REAL,
            score2 REAL,
            FOREIGN KEY (coach1_id) REFERENCES coaches(id),
            FOREIGN KEY (coach2_id) REFERENCES coaches(id)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            coach1_id INTEGER NOT NULL,
            pokemon_out TEXT DEFAULT '',
            pokemon_in TEXT DEFAULT '',
            coach2_id INTEGER,
            notes TEXT DEFAULT '',
            FOREIGN KEY (coach1_id) REFERENCES coaches(id),
            FOREIGN KEY (coach2_id) REFERENCES coaches(id)
        );

        CREATE TABLE IF NOT EXISTS match_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL,
            coach_id INTEGER NOT NULL,
            pokemon_name TEXT NOT NULL,
            kills REAL DEFAULT 0,
            deaths REAL DEFAULT 0,
            FOREIGN KEY (schedule_id) REFERENCES schedule(id),
            FOREIGN KEY (coach_id) REFERENCES coaches(id)
        );

        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_order INTEGER DEFAULT 0,
            title TEXT NOT NULL,
            content TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'coach',
            coach_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS draft_tiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            points INTEGER NOT NULL,
            tier_label TEXT DEFAULT '',
            is_banned INTEGER DEFAULT 0,
            is_tera_banned INTEGER DEFAULT 0
        );
    """)

    # Default settings
    defaults = [
        ("league_name", "Pokemon Draft League"),
        ("season", "1"),
        ("points_budget", "45"),
        ("fa_limit", "3"),
        ("mechanic", "Terastallization"),
        ("mechanic_tax", "0"),
        ("num_players", "18"),
        ("num_pools", "2"),
        ("current_week", "1"),
        ("format", "Gen 9 National Dex Ubers"),
    ]
    for key, value in defaults:
        c.execute(
            "INSERT OR IGNORE INTO league_settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def create_admin(username, password):
    """Create or update the admin user."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO users (username, password_hash, role) VALUES (?,?,?)",
        (username, hash_pw(password), "admin")
    )
    conn.commit()
    conn.close()
    print(f"Admin user '{username}' created/updated.")


def create_coach_user(username, password, coach_id):
    """Create a coach user account."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO users (username, password_hash, role, coach_id) VALUES (?,?,?,?)",
        (username, hash_pw(password), "coach", coach_id)
    )
    conn.commit()
    conn.close()
    print(f"Coach user '{username}' created/updated.")


if __name__ == "__main__":
    init_db()

    # Default admin: admin / yuricup2024
    # Run: python init_db.py to initialize, or:
    # python init_db.py admin YourPasswordHere  to set admin password
    if len(sys.argv) >= 3:
        create_admin(sys.argv[1], sys.argv[2])
    else:
        create_admin("admin", "yuricup2024")
        print("Default admin created: username=admin, password=yuricup2024")
        print("CHANGE THIS PASSWORD! Run: python init_db.py admin <new_password>")
