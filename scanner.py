import os
import sys
import sqlite3
from datetime import datetime
from database import (
    DB_NAME, 
    has_recent_active_signal, 
    add_insider_signal, 
    get_signals_to_track, 
    update_signal_metrics
)

LOCK_FILE = "scan.lock"

def run_nightly_screener():
    print(f"[{datetime.now()}] Starting nightly insider scan...")
    
    # Create the synchronization lock file
    with open(LOCK_FILE, "w") as f:
        f.write("locked")
        
    try:
        # --- PHASE 1 & 2: INDEX SCREENING & INSIDER FILTERING ---
        # Mocking data payload from financial APIs for testing architecture
        discovered_tickers = [("INTC", 30.15), ("PFE", 28.40)] 
        
        for ticker, price in discovered_tickers:
            # Apply the 90-day protection shield filter
            if not has_recent_active_signal(ticker):
                add_insider_signal(ticker, price)
                print(f"New high-conviction signal stored: {ticker} at ${price}")
            else:
                print(f"Signal for {ticker} skipped: already active within 90 days.")

        # --- PHASE 3: PORTFOLIO ROI CALCULATIONS ---
        signals_to_update = get_signals_to_track()
        for row in signals_to_update:
            signal_id, ticker, date_detected, price_detected, status, roi_3m, roi_6m = row
            # Metrics updating logic will execute here during production runs
            pass

        # --- PHASE 4: UPDATE RUNTIME METADATA ---
        # Tells the main bot that data is initialized and no longer in default state
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE metadata SET value = ? WHERE key = 'last_insider_scan'", (now_str,))
        conn.commit()
        conn.close()
        
        print(f"[{datetime.now()}] Nightly scan completed successfully.")

    except Exception as e:
        print(f"ERROR during nightly scan execution: {str(e)}", file=sys.stderr)
    finally:
        # Safety clean up to ensure the bot is never permanently frozen
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)

if __name__ == "__main__":
    run_nightly_screener()
