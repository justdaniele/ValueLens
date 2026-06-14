import sqlite3
import logging
from datetime import datetime, timedelta
import yfinance as yf

logger = logging.getLogger("ValueLensDatabase")
DB_NAME = "valuelens.db"

def init_db():
    """Initializes the SQLite database and structures the autonomous operational schema."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        )
    """)

    # insider_signals stores one record per ticker per detection cycle.
    # total_value: sum of all open-market purchases found in that cycle.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insider_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT UNIQUE,
            date_detected TEXT,
            price_detected REAL DEFAULT 0.0,
            total_value REAL DEFAULT 0.0,
            num_transactions INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ACTIVE'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nightly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_generated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            report_text TEXT,
            lang TEXT DEFAULT 'en',
            status TEXT DEFAULT 'PENDING',
            current_price REAL DEFAULT NULL,
            target_price REAL DEFAULT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS earnings_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            price_at_signal REAL,
            prediction TEXT,
            ees_score INTEGER DEFAULT 0,
            is_evaluated INTEGER DEFAULT 0
        )
    """)
    
    # Initialize basic performance registry data tracking
    cursor.execute("SELECT key FROM metadata WHERE key = 'accuracy_wins'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO metadata (key, value) VALUES ('accuracy_wins', 0)")
    cursor.execute("SELECT key FROM metadata WHERE key = 'accuracy_total'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO metadata (key, value) VALUES ('accuracy_total', 0)")
        
    # Unified deduplication table — prevents same ticker being alerted more than once
    # within the cooldown window, regardless of alert type (fundamental or insider).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sent_alerts_ticker ON sent_alerts (ticker, sent_at)")

    # Schema migration — safely add new columns to existing tables
    # Uses try/except because SQLite has no IF NOT EXISTS for ALTER TABLE
    migrations = [
        "ALTER TABLE insider_signals ADD COLUMN total_value REAL DEFAULT 0.0",
        "ALTER TABLE insider_signals ADD COLUMN num_transactions INTEGER DEFAULT 0",
        "ALTER TABLE earnings_predictions ADD COLUMN ees_score INTEGER DEFAULT 0",
    ]
    for migration in migrations:
        try:
            cursor.execute(migration)
        except Exception:
            pass  # Column already exists — skip silently

    conn.commit()
    conn.close()
    logger.info("Database schema initialized and fully matched with tracking engines.")


def save_report_to_db(ticker, report_text, lang="en", current_price=None, target_price=None):
    """Saves a generated AI report to the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO nightly_reports (ticker, report_text, lang, current_price, target_price)
        VALUES (?, ?, ?, ?, ?)
    """, (ticker, report_text, lang, current_price, target_price))
    conn.commit()
    conn.close()


def save_earnings_prediction(ticker, price_at_signal, prediction, ees_score=0):
    """Saves a dynamic earnings sniper prediction to the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO earnings_predictions (ticker, price_at_signal, prediction, ees_score)
        VALUES (?, ?, ?, ?)
    """, (ticker, price_at_signal, prediction, ees_score))
    conn.commit()
    conn.close()


def get_accuracy_metrics():
    """Fetches global historical accuracy performance metrics."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM metadata WHERE key = 'accuracy_wins'")
    wins_row = cursor.fetchone()
    cursor.execute("SELECT value FROM metadata WHERE key = 'accuracy_total'")
    total_row = cursor.fetchone()
    
    global_wins = int(wins_row[0]) if wins_row else 0
    global_total = int(total_row[0]) if total_row else 0
    global_pct = f"{(global_wins / global_total) * 100:.1f}%" if global_total > 0 else "0.0%"
    conn.close()
    return global_wins, global_total, global_pct


def get_weekly_summary_stats():
    """Aggregates active performance data for the weekly recap broadcast."""
    wins, total, pct = get_accuracy_metrics()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "SELECT COUNT(*) FROM earnings_predictions WHERE timestamp >= ?",
        (seven_days_ago,)
    )
    weekly_alerts = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT ticker, COUNT(*) as win_count
        FROM earnings_predictions
        WHERE is_evaluated = 1
          AND prediction IN ('BULLISH', 'BEARISH')
          AND timestamp >= ?
        GROUP BY ticker
        ORDER BY win_count DESC
        LIMIT 1
    """, (seven_days_ago,))
    top_row = cursor.fetchone()
    top_ticker = top_row[0] if top_row else "N/A"

    conn.close()
    return {
        "weekly_alerts": weekly_alerts,
        "top_ticker": top_ticker,
        "global_wins": wins,
        "global_total": total,
        "global_pct": pct
    }


def evaluate_historical_accuracy_loop():
    """Evaluates pending earnings predictions against current market price data to calculate true win/loss metrics."""
    logger.info("Starting historical accuracy validation sweep...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT id, ticker, price_at_signal, prediction FROM earnings_predictions "
        "WHERE is_evaluated = 0 AND timestamp <= datetime('now', '-24 hours')"
    )
    pending = cursor.fetchall()
    
    if not pending:
        logger.info("No pending predictions require evaluation.")
        conn.close()
        return

    wins_added = 0
    total_added = 0

    for row in pending:
        row_id, ticker, price_at_signal, prediction = row
        try:
            stock = yf.Ticker(ticker)
            current_price = stock.fast_info.last_price
            
            if not current_price:
                continue
                
            is_win = False
            if prediction == "BULLISH" and current_price > price_at_signal:
                is_win = True
            elif prediction == "BEARISH" and current_price < price_at_signal:
                is_win = True
                
            if is_win:
                wins_added += 1
            total_added += 1
            
            cursor.execute("UPDATE earnings_predictions SET is_evaluated = 1 WHERE id = ?", (row_id,))
        except Exception as e:
            logger.error(f"Failed to evaluate prediction accuracy for {ticker}: {e}")

    if total_added > 0:
        cursor.execute("UPDATE metadata SET value = value + ? WHERE key = 'accuracy_wins'", (wins_added,))
        cursor.execute("UPDATE metadata SET value = value + ? WHERE key = 'accuracy_total'", (total_added,))
        conn.commit()
        logger.info(f"Accuracy sweep complete. Added {wins_added} wins out of {total_added} evaluated metrics.")
        
    conn.close()

def was_recently_alerted(ticker: str, cooldown_days: int = 5) -> bool:
    """Returns True if the ticker was already alerted within the cooldown window.

    Checks the unified sent_alerts table regardless of alert type (fundamental/insider).
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM sent_alerts WHERE ticker = ? AND sent_at >= datetime('now', ?)",
        (ticker, f"-{cooldown_days} days")
    )
    result = cursor.fetchone() is not None
    conn.close()
    return result


def record_alert_sent(ticker: str, alert_type: str = "fundamental"):
    """Records that an alert was sent for a ticker in the unified deduplication table."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sent_alerts (ticker, alert_type) VALUES (?, ?)",
        (ticker, alert_type)
    )
    conn.commit()
    conn.close()