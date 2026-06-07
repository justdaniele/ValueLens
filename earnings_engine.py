import os
import time
import logging
import requests
import html
import datetime
import yfinance as yf
from analyzer import generate_earnings_sentiment_layer
from database import save_earnings_prediction
from scanner import get_us_market_universe

logger = logging.getLogger("EarningsEngine")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID_IT = os.environ.get("TELEGRAM_CHANNEL_ID_IT", "")
CHANNEL_ID_EN = os.environ.get("TELEGRAM_CHANNEL_ID_EN", "")

# Minimum absolute EES score before a Sniper Alert is dispatched
EES_FIRE_THRESHOLD = int(os.environ.get("EES_FIRE_THRESHOLD", "30"))

def send_alert_to_channel(text_en: str, text_it: str = None):
    """Broadcasts localized alerts applying safety HTML escape matrices."""
    if not BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    def dispatch(channel, text):
        safe_text = html.escape(text, quote=False)
        safe_text = safe_text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
        safe_text = safe_text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
        try:
            requests.post(url, json={"chat_id": channel, "text": safe_text, "parse_mode": "HTML"}, timeout=15)
        except Exception as e:
            logger.error(f"Failed sending alert: {e}")

    if CHANNEL_ID_EN and text_en:
        dispatch(CHANNEL_ID_EN, text_en)
    if CHANNEL_ID_IT and (text_it or text_en):
        dispatch(CHANNEL_ID_IT, text_it if text_it else text_en)

async def run_earnings_pipeline():
    """Triggers the predictive earnings analysis on short-term catalysts."""
    logger.info("Initiating Earnings Catalyst Sniper Engine...")
    universe, _ = get_us_market_universe()
    if not universe:
        return

    today = datetime.date.today()
    target_window_end = today + datetime.timedelta(days=3)
    
    upcoming = []
    
    logger.info("Scanning universe for upcoming earnings within 72h window...")
    for ticker in universe[:150]: # Scansiona i primi 150 titoli (Regola questo limite secondo necessità)
        try:
            stock = yf.Ticker(ticker)
            calendar = stock.calendar
            
            if calendar and 'Earnings Date' in calendar:
                dates = calendar['Earnings Date']
                if dates and isinstance(dates, list) and len(dates) > 0:
                    earnings_date = dates[0]
                    
                    # FIX: yfinance ora restituisce datetime.date direttamente.
                    # Se fosse un Timestamp o datetime, estraiamo solo il `.date()`
                    if hasattr(earnings_date, "date"): 
                        earnings_date = earnings_date.date()
                    
                    if isinstance(earnings_date, datetime.date):
                        if today <= earnings_date <= target_window_end:
                            upcoming.append(ticker)
                            logger.info(f"Catalyst found: {ticker} earnings on {earnings_date}")
        except Exception as e:
            pass
        time.sleep(0.1)

    if not upcoming:
        logger.info("No upcoming earnings detected in the short-term window.")
        return
        
    for ticker in upcoming:
        try:
            stock = yf.Ticker(ticker)
            curr_price = stock.fast_info.last_price
            
            quant_score = 10.5 # Default quant base score
            ai_score = generate_earnings_sentiment_layer(ticker, stock.info.get("shortName", ticker))
            final_ees = round(quant_score + ai_score)
            
            direction = "BULLISH" if final_ees >= 0 else "BEARISH"
            direction_it = "RIALZISTA" if final_ees >= 0 else "RIBASSISTA"
            
            save_earnings_prediction(ticker, curr_price, direction)
            
            if abs(final_ees) >= EES_FIRE_THRESHOLD:
                msg_en = (f"🎯 <b>Sniper Alert: {ticker}</b>\n\n"
                          f"Score: <b>{final_ees}</b>\n"
                          f"Quant: {round(quant_score)} | AI Sentiment: {ai_score}\n"
                          f"Prediction: <b>{direction}</b>\n"
                          f"Price at signal: <code>${curr_price:.2f}</code>")
                          
                msg_it = (f"🎯 <b>Sniper Alert: {ticker}</b>\n\n"
                          f"Punteggio: <b>{final_ees}</b>\n"
                          f"Quant: {round(quant_score)} | Sentiment AI: {ai_score}\n"
                          f"Previsione: <b>{direction_it}</b>\n"
                          f"Prezzo al segnale: <code>${curr_price:.2f}</code>")
                
                send_alert_to_channel(msg_en, msg_it)
                time.sleep(2)
        except Exception as e:
            logger.error(f"Error processing earnings analysis for {ticker}: {e}")