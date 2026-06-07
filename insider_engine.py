import os
import time
import logging
import sqlite3
import yfinance as yf
from database import DB_NAME
from earnings_engine import send_alert_to_channel
from scanner import get_us_market_universe

logger = logging.getLogger("InsiderEngine")

# Imposta una soglia minima di acquisto per evitare rumore di fondo (es. 100k)
MIN_PURCHASE_VALUE = float(os.environ.get("INSIDER_MIN_VALUE", "100000"))
SCAN_LIMIT = int(os.environ.get("INSIDER_SCAN_LIMIT", "50"))

def run_insider_tracking():
    """Scans market universe for high-conviction C-Suite corporate purchases."""
    logger.info("Initializing Insider Tracking Engine...")
    universe, _ = get_us_market_universe()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    scanned = 0
    alerts_fired = 0
    
    for ticker in universe[:SCAN_LIMIT]:
        try:
            stock = yf.Ticker(ticker)
            df = stock.insider_transactions
            
            if df is not None and not df.empty:
                # FIX: Utilizziamo le colonne 'Transaction' (T maiuscola) e 'Value' (V maiuscola)
                if 'Transaction' in df.columns and 'Value' in df.columns:
                    # Filtriamo solo gli acquisti a mercato (Buy / Purchase)
                    buys = df[df['Transaction'].astype(str).str.contains('Buy|Purchase', case=False, na=False)]
                    
                    # Filtriamo solo acquisti rilevanti maggiori della soglia (es. > 100.000$)
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
            logger.debug(f"Skip insider scan for {ticker}: {e}")
            
        scanned += 1
        time.sleep(0.5)
        
    conn.close()
    logger.info(f"Insider scan complete. Scanned: {scanned}. Alerts fired: {alerts_fired}.")