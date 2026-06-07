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
            value TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insider_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT UNIQUE,
            date_detected TEXT,
            price_detected REAL,
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
            status TEXT DEFAULT 'PENDING'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS earnings_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            ticker TEXT,
            price_at_signal REAL,
            prediction TEXT,
            is_evaluated INTEGER DEFAULT 0
        )
    """)
    
    # Initialize accuracy counters if they do not exist
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('accuracy_wins', '0')")
    cursor.execute("INSERT OR IGNORE INTO metadata (key, value) VALUES ('accuracy_total', '0')")
    
    conn.commit()
    conn.close()

def save_earnings_prediction(ticker, price, prediction):
    """Saves the directional prediction for a specific ticker ahead of its earnings release."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO earnings_predictions (ticker, price_at_signal, prediction)
        VALUES (?, ?, ?)
    """, (ticker, price, prediction))
    conn.commit()
    conn.close()

def evaluate_historical_accuracy_loop():
    """Checks predictions older than 24h, compares the new price, and records Win/Loss."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Fetch predictions older than 24 hours that haven't been evaluated yet
        target_time = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("SELECT id, ticker, price_at_signal, prediction FROM earnings_predictions WHERE is_evaluated = 0 AND timestamp <= ?", (target_time,))
        rows = cursor.fetchall()
        
        wins_added = 0
        total_added = 0
        
        for row in rows:
            record_id, ticker, price_old, prediction = row
            try:
                stock = yf.Ticker(ticker)
                price_new = stock.fast_info.last_price
                
                is_win = False
                if prediction == "BULLISH" and price_new > price_old:
                    is_win = True
                elif prediction == "BEARISH" and price_new < price_old:
                    is_win = True
                    
                if is_win:
                    wins_added += 1
                total_added += 1
                
                # Flag the record as evaluated
                cursor.execute("UPDATE earnings_predictions SET is_evaluated = 1 WHERE id = ?", (record_id,))
                logger.info(f"Evaluated {ticker}: Old ${price_old:.2f} -> New ${price_new:.2f}. Pred: {prediction}. Win: {is_win}")
            except Exception as e:
                logger.warning(f"Could not evaluate {ticker}: {e}")
                
        # Update global accuracy trackers if new evaluations occurred
        if total_added > 0:
            cursor.execute("UPDATE metadata SET value = value + ? WHERE key = 'accuracy_wins'", (wins_added,))
            cursor.execute("UPDATE metadata SET value = value + ? WHERE key = 'accuracy_total'", (total_added,))
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error in evaluate_historical_accuracy_loop: {e}")

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
    cursor.execute("SELECT COUNT(*) FROM earnings_predictions WHERE timestamp >= ?", (seven_days_ago,))
    weekly_alerts = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT ticker FROM earnings_predictions WHERE is_evaluated = 1 ORDER BY timestamp DESC LIMIT 1")
    top_row = cursor.fetchone()
    top_ticker = top_row[0] if top_row else "N/A"
    conn.close()
    
    return {
        "global_wins": wins,
        "global_total": total,
        "global_pct": pct,
        "weekly_alerts": weekly_alerts,
        "top_ticker": top_ticker
    }