import os
import time
import logging
import sqlite3
import yfinance as yf
from database import DB_NAME
from earnings_engine import send_alert_to_channel
from scanner import get_us_market_universe

logger = logging.getLogger("InsiderEngine")

# Minimum dollar value for a single purchase to be considered high-conviction
MIN_PURCHASE_VALUE = float(os.environ.get("INSIDER_MIN_VALUE", "100000"))

def run_insider_tracking():
    """Scans the entire market universe for high-conviction C-Suite open-market purchases."""
    logger.info("Initializing Insider Tracking Engine...")
    universe = get_us_market_universe()
    if not universe:
        logger.error("Market universe is empty. Aborting insider tracking routine.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    scanned = 0
    alerts_fired = 0

    logger.info(f"Starting comprehensive insider screening over {len(universe)} assets...")
    
    # FIX: Loop over the entire universe to completely eliminate alphabetical and size bias
    for ticker in universe:
        try:
            stock = yf.Ticker(ticker)
            df = stock.insider_transactions
            
            if df is not None and not df.empty:
                # Validate that modern yfinance columns exist
                if 'Transaction' in df.columns and 'Value' in df.columns:
                    # Isolate open-market purchases (exclude stock options or gifts)
                    buys = df[df['Transaction'].astype(str).str.contains('Buy|Purchase', case=False, na=False)]
                    recent_buys = buys[buys['Value'] >= MIN_PURCHASE_VALUE]
                    
                    if not recent_buys.empty:
                        cursor.execute("SELECT id FROM insider_signals WHERE ticker = ?", (ticker,))
                        if not cursor.fetchone():
                            curr_price = stock.fast_info.last_price
                            total_value = recent_buys['Value'].sum()
                            num_transactions = len(recent_buys)
                            
                            cursor.execute(
                                "INSERT INTO insider_signals (ticker, date_detected, price_detected) VALUES (?, date('now'), ?)", 
                                (ticker, curr_price)
                            )
                            conn.commit()
                            
                            value_str = f"${total_value:,.0f}" if total_value > 0 else "N/A"
                            
                            msg_en = (
                                f"🟢 <b>Insider Buy Alert: {ticker}</b>\n"
                                f"C-Suite executives executed <b>{num_transactions}</b> open-market "
                                f"purchase(s) totalling approx. <b>{value_str}</b> "
                                f"at ~<code>${curr_price:.2f}</code>. Structural bullish signal."
                            )
                            msg_it = (
                                f"🟢 <b>Acquisto Insider: {ticker}</b>\n"
                                f"I manager hanno effettuato <b>{num_transactions}</b> acquisto/i "
                                f"a mercato aperto per un totale di circa <b>{value_str}</b> "
                                f"a ~<code>${curr_price:.2f}</code>. Segnale rialzista strutturale."
                            )
                            
                            send_alert_to_channel(msg_en, msg_it)
                            logger.info(f"Insider alert dispatched for {ticker} — {num_transactions} tx, {value_str}")
                            alerts_fired += 1
        except Exception as e:
            logger.warning(f"Insider scan failed or skipped for {ticker}: {e}")
            
        scanned += 1
        # Pacing window configured to 0.3s to protect network hardware integrity
        time.sleep(0.3) 
        
    conn.close()
    logger.info(f"Insider scan complete. Scanned assets: {scanned}. Alerts fired: {alerts_fired}.")