import os
import time
import logging
import sqlite3
import datetime
import pandas as pd
import yfinance as yf
from database import DB_NAME
from earnings_engine import send_alert_to_channel
from scanner import get_us_market_universe

logger = logging.getLogger("InsiderEngine")
MIN_PURCHASE_VALUE = float(os.environ.get("INSIDER_MIN_VALUE", "100000"))
SCAN_LIMIT = int(os.environ.get("INSIDER_SCAN_LIMIT", "50"))

def run_insider_tracking():
    """Scans the entire market universe for high-conviction corporate purchase footprints."""
    logger.info("Initializing Insider Tracking Engine...")
    universe = get_us_market_universe()
    if not universe:
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    scanned = 0
    alerts_fired = 0
    
    today = datetime.date.today()
    two_weeks_ago = today - datetime.timedelta(days=14)

    for ticker in universe[:SCAN_LIMIT]:
        try:
            stock = yf.Ticker(ticker)
            df = stock.insider_transactions
            
            if df is not None and not df.empty:
                if 'Transaction' in df.columns and 'Value' in df.columns and 'Start Date' in df.columns:
                    buys = df[df['Transaction'].astype(str).str.contains('Buy|Purchase', case=False, na=False)]
                    
                    recent_buys = []
                    for _, row in buys.iterrows():
                        try:
                            tx_date = pd.to_datetime(row['Start Date']).date()
                            if two_weeks_ago <= tx_date <= today:
                                if float(row['Value']) >= MIN_PURCHASE_VALUE:
                                    recent_buys.append(row)
                        except Exception:
                            pass
                    
                    if recent_buys:
                        cursor.execute("SELECT id FROM insider_signals WHERE ticker = ?", (ticker,))
                        if not cursor.fetchone():
                            curr_price = stock.fast_info.last_price
                            total_value = sum(float(r['Value']) for r in recent_buys)
                            num_transactions = len(recent_buys)
                            
                            cursor.execute(
                                "INSERT INTO insider_signals (ticker, date_detected, price_detected) VALUES (?, date('now'), ?)", 
                                (ticker, curr_price)
                            )
                            conn.commit()
                            
                            value_str = f"${total_value:,.0f}" if total_value > 0 else "N/A"
                            
                            # MATCHING ENGINE CODES (GOLDEN COMBO CHECK)
                            cursor.execute("""
                                SELECT id FROM nightly_reports 
                                WHERE ticker = ? AND date(date_generated) >= date('now', '-1 day')
                                LIMIT 1
                            """, (ticker,))
                            is_combo = cursor.fetchone() is not None
                            
                            if is_combo:
                                msg_en = (
                                    f"🏆 <b>ValueLens Golden Combo Alert: {ticker}</b>\n\n"
                                    f"<b>AI Fundamental Match:</b> This firm was flagged as highly undervalued "
                                    f"by our system, and C-Suite execs are now buying personal stock shares!\n\n"
                                    f"• Transactions: <code>{num_transactions}</code>\n"
                                    f"• Value: <b>{value_str}</b>\n"
                                    f"• Price: <code>${curr_price:.2f}</code>"
                                )
                                msg_it = (
                                    f"🏆 <b>ValueLens Golden Combo Alert: {ticker}</b>\n\n"
                                    f"<b>Match Matrice Fondamentale AI:</b> Questa azienda è stata contrassegnata come "
                                    f"altamente sottovalutata dal bot, ed i manager stanno comprando azioni sul mercato aperto!\n\n"
                                    f"• Numero Transazioni: <code>{num_transactions}</code>\n"
                                    f"• Valore Totale: <b>{value_str}</b>\n"
                                    f"• Prezzo Attuale: <code>${curr_price:.2f}</code>"
                                )
                            else:
                                msg_en = (
                                    f"🟢 <b>Insider Buy Alert: {ticker}</b>\n\n"
                                    f"C-Suite executives executed <b>{num_transactions}</b> open-market "
                                    f"purchase(s) totalling approx. <b>{value_str}</b> "
                                    f"at ~<code>${curr_price:.2f}</code>. Structural bullish signal."
                                )
                                msg_it = (
                                    f"🟢 <b>Acquisto Insider: {ticker}</b>\n\n"
                                    f"I manager hanno effettuato <b>{num_transactions}</b> acquisto/i "
                                    f"a mercato aperto per un totale di circa <b>{value_str}</b> "
                                    f"a ~<code>${curr_price:.2f}</code>. Segnale rialzista strutturale."
                                )
                            
                            send_alert_to_channel(msg_en, msg_it)
                            logger.info(f"Insider alert fired for {ticker} (Combo: {is_combo})")
                            alerts_fired += 1
        except Exception as e:
            logger.warning(f"Insider validation skipped for {ticker}: {e}")
            
        scanned += 1
        time.sleep(0.3)  # Clean pacing interval anti-throttling link
        
    conn.close()