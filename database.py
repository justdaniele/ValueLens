import sqlite3
from datetime import datetime

DB_NAME = "valuelens.db"

def init_db():
    """Initializes the database, creating tables for users, insider signals, and metadata."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            user_level INTEGER DEFAULT 1,
            Scans_count INTEGER DEFAULT 0
        )
    """)
    
    # Global Insider Signals Table (Bot Tracker Portfolio)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insider_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date_detected TEXT NOT NULL,
            price_detected REAL NOT NULL,
            status TEXT DEFAULT 'ACTIVE',
            roi_3m REAL DEFAULT NULL,
            roi_6m REAL DEFAULT NULL,
            roi_1y REAL DEFAULT NULL
        )
    """)
    
    # Metadata Table for boot and state management
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('last_insider_scan', 'NEVER')")
    
    conn.commit()
    conn.close()


# --- USER MANAGEMENT ---

def register_user(user_id: int, username: str):
    """Registers a new user into the database if they do not exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, username, user_level, Scans_count)
        VALUES (?, ?, 1, 0)
    """, (user_id, username))
    conn.commit()
    conn.close()

def get_user_level(user_id: int) -> int:
    """Returns the subscription/clearance level of the user."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_level FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 1

def increment_scan_count(user_id: int):
    """Increments the total number of manual scans executed by the user."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET Scans_count = Scans_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# --- PORTFOLIO & INSIDER TRACKING ---

def has_recent_active_signal(ticker: str) -> bool:
    """Checks if an active alert already exists for the ticker (90-day protection shield)."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM insider_signals 
        WHERE ticker = ? AND status = 'ACTIVE'
    """, (ticker.upper(),))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def add_insider_signal(ticker: str, price: float):
    """Saves a newly discovered insider opportunity into the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        INSERT INTO insider_signals (ticker, date_detected, price_detected, status)
        VALUES (?, ?, ?, 'ACTIVE')
    """, (ticker.upper(), today_str, price))
    conn.commit()
    conn.close()

def get_signals_to_track():
    """Retrieves all historical signals that still require performance monitoring."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, ticker, date_detected, price_detected, status, roi_3m, roi_6m 
        FROM insider_signals 
        WHERE roi_1y IS NULL
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_signal_metrics(signal_id: int, status: str, roi_3m: float, roi_6m: float, roi_1y: float):
    """Updates tracking status and actual percentage returns for a specific signal."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE insider_signals 
        SET status = ?, roi_3m = ?, roi_6m = ?, roi_1y = ?
        WHERE id = ?
    """, (status, roi_3m, roi_6m, roi_1y, signal_id))
    conn.commit()
    conn.close()