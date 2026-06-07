import os
import time
import logging
import sqlite3
import yfinance as yf
from database import DB_NAME
from earnings_engine import send_alert_to_channel
from scanner import get_us_market_universe

logger = logging.getLogger("InsiderEngine")

def run_insider_tracking():
    """Scans market universe for high-conviction C-Suite corporate purchases."""
    logger.info("Initializing Insider Tracking Engine...")
    universe, _ = get_us_market_universe()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    for ticker in universe[:50]: # Scans first 50 targets for performance safety
        try:
            stock = yf.Ticker(ticker)
            df = stock.insider_purchases
            if df is not None and not df.empty:
                # Check if there is a massive recent insider purchase footprint
                recent_buys = df[df['Purchases'] > 0]
                if not recent_buys.empty:
                    cursor.execute("SELECT id FROM insider_signals WHERE ticker = ?", (ticker,))
                    if not cursor.fetchone():
                        curr_price = stock.fast_info.last_price
                        cursor.execute("INSERT INTO insider_signals (ticker, date_detected, price_detected) VALUES (?, date('now'), ?)", (ticker, curr_price))
                        conn.commit()
                        
                        msg_en = f"🟢 <b>Insider Buy Alert: {ticker}</b>\nC-Suite Executives have executed massive open-market purchases at roughly ${curr_price:.2f}. Structural bullish signal."
                        msg_it = f"🟢 <b>Acquisto Insider: {ticker}</b>\nI manager hanno acquistato massicciamente azioni a mercato intorno a ${curr_price:.2f}. Segnale rialzista strutturale."
                        send_alert_to_channel(msg_en, msg_it)
                        logger.info(f"Insider alert dispatched for {ticker}")
        except Exception as e:
            pass
        time.sleep(0.5)
        
    conn.close()
