import os
import sys
import sqlite3
import logging
from datetime import datetime
import yfinance as yf
from database import (
    DB_NAME, 
    has_recent_active_signal, 
    add_insider_signal, 
    get_signals_to_track, 
    update_signal_metrics
)

LOCK_FILE = "scan.lock"

# Configure advanced structured logging architecture
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ValueLensScanner")

def run_nightly_screener():
    logger.info("Starting nightly corporate insider scanning sequence...")
    
    # Create the synchronization lock file to prevent race conditions with the bot context
    with open(LOCK_FILE, "w") as f:
        f.write("locked")
        
    try:
        # --- PHASE 1 & 2: INDEX SCREENING & INSIDER FILTERING ---
        # Mocking data payload from financial APIs (Replace with your actual scraping/API core)
        discovered_tickers = [("INTC", 30.15), ("PFE", 28.40)] 
        
        for ticker, price in discovered_tickers:
            try:
                # Apply the 90-day protection shield filter to avoid duplicate user alerts
                if not has_recent_active_signal(ticker):
                    add_insider_signal(ticker, price)
                    logger.info(f"New high-conviction insider signal stored: {ticker} at ${price}")
                else:
                    logger.info(f"Signal for {ticker} skipped: protection shield active (within 90 days).")
            except Exception as ticker_err:
                logger.error(f"Failed processing insider screening loop for asset {ticker}: {ticker_err}")

        # --- PHASE 3: PORTFOLIO ROI CALCULATIONS (Virtual Tracker) ---
        logger.info("Recalculating real-time performance metrics for active tracker portfolio...")
        try:
            signals_to_update = get_signals_to_track()
            for row in signals_to_update:
                # Safe index-based unpacking to accommodate custom structural DB changes
                signal_id = row[0]
                ticker = row[1]
                price_detected = row[3]
                
                try:
                    stock = yf.Ticker(ticker)
                    current_price = stock.info.get("currentPrice")
                    
                    if current_price is not None and price_detected > 0:
                        # Calculate current absolute ROI percentage from initial C-Suite execution window
                        current_roi = round(((current_price - price_detected) / price_detected) * 100, 2)
                        
                        # Execute the database tracking persistence layer update
                        update_signal_metrics(signal_id, current_roi)
                        logger.info(f"Updated tracking statistics for {ticker}: ROI currently at {current_roi}%")
                except Exception as tracking_err:
                    logger.error(f"Failed pulling market price data for portfolio tracking entity {ticker}: {tracking_err}")
        except Exception as batch_err:
            logger.error(f"Failed executing structural tracker portfolio calculation batch: {batch_err}")

        # --- PHASE 4: UPDATE RUNTIME METADATA ---
        # Signals the main bot interface that metadata states are initialized and updated
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE metadata SET value = ? WHERE key = 'last_insider_scan'", (now_str,))
        conn.commit()
        conn.close()
        
        logger.info("Nightly corporate insider scan completed successfully.")

    except Exception as e:
        logger.error(f"CRITICAL CRASH detected within nightly screener sequence: {str(e)}")
    finally:
        # Crucial safety cleanup step to guarantee the core system is never left frozen permanently
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)

if __name__ == "__main__":
    run_nightly_screener()