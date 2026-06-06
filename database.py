import sqlite3
import logging
from datetime import datetime, timedelta
import yfinance as yf

# Configure internal module logger
logger = logging.getLogger("ValueLensDatabase")

DB_NAME = "valuelens.db"

def init_db():
    """Initializes the SQLite database and structures the autonomous operational schema."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Metadata configuration table (Global System Trackers)
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
    
    # Nightly raw market reports persistence storage (Updated with 'lang' column)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nightly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_generated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            report_text TEXT,
            lang TEXT DEFAULT 'en',
            status TEXT DEFAULT 'PENDING'
        )
    """)
    
    # Automatic migration: if the table already exists without the 'lang' column, we add it
    try:
        cursor.execute("ALTER TABLE nightly_reports ADD COLUMN lang TEXT DEFAULT 'en'")
        logger.info("Database migration: Added 'lang' column to 'nightly_reports'.")
    except sqlite3.OperationalError:
        # Column already exists, no issue
        pass
    
    # Earnings sniper predictions persistence table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS earnings_predictions (
            ticker TEXT PRIMARY KEY,
            trigger_price REAL,
            prediction TEXT,
            timestamp TEXT,
            is_evaluated INTEGER DEFAULT 0
        )
    """)
    
    # Initialize core operational metadata entries safely
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('last_insider_scan', 'NEVER')")
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('accuracy_wins', '0')")
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('accuracy_total', '0')")
    
    conn.commit()
    conn.close()
    logger.info("Database schemas fully initialized, migrated, and synchronized.")


# --- Persistent Earnings & Accuracy Tracking Functions ---

def get_accuracy_metrics() -> tuple:
    """Reads current quantitative win/loss statistics from the metadata layer."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT value FROM metadata WHERE key = 'accuracy_wins'")
    wins = int(cursor.fetchone()[0])
    
    cursor.execute("SELECT value FROM metadata WHERE key = 'accuracy_total'")
    total = int(cursor.fetchone()[0])
    
    conn.close()
    
    accuracy_percentage = (wins / total * 100) if total > 0 else 0.0
    return wins, total, f"{round(accuracy_percentage, 1)}%"


def save_earnings_prediction(ticker: str, current_price: float, direction: str):
    """Stores a pending corporate catalyst prediction safely to disk storage."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO earnings_predictions (ticker, trigger_price, prediction, timestamp, is_evaluated)
        VALUES (?, ?, ?, ?, 0)
    """, (ticker, current_price, direction, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def evaluate_historical_accuracy_loop():
    """Validates older predictions against current spot closes to update global tracking statistics."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT ticker, trigger_price, prediction, timestamp FROM earnings_predictions WHERE is_evaluated = 0")
    pending_rows = cursor.fetchall()
    
    for row in pending_rows:
        ticker, old_price, pred, timestamp_str = row
        timestamp = datetime.fromisoformat(timestamp_str)
        
        # Evaluate performance conditions only after a 48-hour analytical execution buffer
        if datetime.now() - timestamp > timedelta(days=2):
            try:
                stock = yf.Ticker(ticker)
                current_close = stock.info.get("currentPrice") or stock.info.get("regularMarketPrice")
                
                if pred != "NEUTRAL" and current_close is not None:
                    is_successful_call = (pred == "BULLISH" and current_close > old_price) or (pred == "BEARISH" and current_close < old_price)
                    
                    cursor.execute("UPDATE metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'accuracy_total'")
                    if is_successful_call:
                        cursor.execute("UPDATE metadata SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'accuracy_wins'")
                
                cursor.execute("UPDATE earnings_predictions SET is_evaluated = 1 WHERE ticker = ?", (ticker,))
                logger.info(f"Historical verification successfully recorded for asset: {ticker}.")
            except Exception as e:
                logger.error(f"Failed pulling real-time market settlement data for evaluation context {ticker}: {e}")
                
    conn.commit()
    conn.close()