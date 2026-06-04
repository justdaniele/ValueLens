import sqlite3

DB_NAME = "valuelens.db"

def init_db():
    """Initializes the SQLite database and handles structural schema evolution safely."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Users table creation
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            scan_count INTEGER DEFAULT 0,
            registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Safe schema migration: Add language column to users table if it doesn't exist
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'en'")
        conn.commit()
    except sqlite3.OperationalError:
        # Column already exists, swallow the database operational error safely
        pass

    # Metadata configuration table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Insider tracking signals data architecture
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insider_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT UNIQUE,
            date_detected TEXT,
            price_detected REAL,
            status TEXT DEFAULT 'ACTIVE'
        )
    """)
    
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('last_insider_scan', 'NEVER')")
    conn.commit()
    conn.close()

def register_user(user_id: int, username: str):
    """Registers a new user context or refreshes the username signature."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username) 
        VALUES (?, ?) 
        ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
    """, (user_id, username))
    conn.commit()
    conn.close()

def get_user_language(user_id: int) -> str:
    """Retrieves the localized ISO language profile for a target user ID."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if (row and row[0]) else "en"

def set_user_language(user_id: int, lang: str):
    """Updates the user session runtime language preference profile."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()
    conn.close()

def increment_scan_count(user_id: int):
    """Increments the analytical runtime counter metrics per unique profile."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET scan_count = scan_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()