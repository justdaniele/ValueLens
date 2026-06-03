import sqlite3

def init_db():
    conn = sqlite3.connect("valuelens.db")
    cursor = conn.cursor()
    # Aggiungiamo 'user_level' che di default è 0 (Free)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            user_level INTEGER DEFAULT 0,
            Scans_count INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_user_level(user_id):
    conn = sqlite3.connect("valuelens.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_level FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0
