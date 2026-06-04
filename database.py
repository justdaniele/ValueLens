import sqlite3

DB_NAME = "valuelens.db"

def init_db():
    """Initializes the SQLite database and creates the required tables if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            scan_count INTEGER DEFAULT 0,
            registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Metadata table to track scanner states (like the insider scan timestamp)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Insider signals tracking table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insider_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT UNIQUE,
            date_detected TEXT,
            price_detected REAL,
            status TEXT DEFAULT 'ACTIVE'
        )
    """)
    
    # Seed the metadata table for the insider scan if it's completely new
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('last_insider_scan', 'NEVER')")
    
    conn.commit()
    conn.close()

def register_user(user_id: int, username: str):
    """Registers a new user or updates their username if they already exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username) 
        VALUES (?, ?) 
        ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
    """, (user_id, username))
    conn.commit()
    conn.close()

def increment_scan_count(user_id: int):
    """Increments the total number of balance scans executed by a user."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET scan_count = scan_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()