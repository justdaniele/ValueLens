import os
import time
import logging
import requests
import html
import datetime
import yfinance as yf
from analyzer import generate_earnings_sentiment_layer
from database import save_earnings_prediction
from scanner import get_us_market_universe, _sanitise_html

logger = logging.getLogger("EarningsEngine")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID_IT = os.environ.get("TELEGRAM_CHANNEL_ID_IT", "")
CHANNEL_ID_EN = os.environ.get("TELEGRAM_CHANNEL_ID_EN", "")
EES_FIRE_THRESHOLD = int(os.environ.get("EES_FIRE_THRESHOLD", "30"))

def send_alert_to_channel(text_en: str, text_it: str = None):
    """Broadcasts localized alerts applying structural safety HTML escape utilities."""
    if not BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    def dispatch(channel, text):
        safe_text = _sanitise_html(text)
        try:
            requests.post(url, json={"chat_id": channel, "text": safe_text, "parse_mode": "HTML"}, timeout=15)
        except Exception as e:
            logger.error(f"Failed sending alert: {e}")

    if CHANNEL_ID_EN and text_en:
        dispatch(CHANNEL_ID_EN, text_en)
    if CHANNEL_ID_IT and (text_it or text_en):
        dispatch(CHANNEL_ID_IT, text_it if text_it else text_en)

def _compute_quant_score(stock) -> float:
    """Calculates a dynamic quantitative score based on 52-week positioning range (No hardcoded metrics)."""
    try:
        fast = stock.fast_info
        low = fast.year_low
        high = fast.year_high
        price = fast.last_price
        
        if low and high and price and (high > low):
            # Calculate range position: 0.0 at 52w low, 1.0 at 52w high
            range_pos = (price - low) / (high - low)
            # Higher score given to assets closer to their 52-week lows (Value Principle)
            return (1.0 - range_pos) * 20.0
    except Exception:
        pass
    return 10.0 # Standard structural neutral baseline fallback

async def run_earnings_pipeline():
    """Identifies active corporate earnings events within a 72h forward window across the entire universe."""
    logger.info("Initiating Earnings Catalyst Sniper Engine...")
    universe = get_us_market_universe()
    if not universe:
        logger.error("Market universe empty. Aborting execution string.")
        return

    today = datetime.date.today()
    target_window_end = today + datetime.timedelta(days=3)
    upcoming_catalysts = []
    
    logger.info(f"Scanning full roster of {len(universe)} securities for short-term earnings events...")
    for ticker in universe:
        try:
            stock = yf.Ticker(ticker)
            calendar = stock.calendar
            
            if calendar and 'Earnings Date' in calendar:
                dates = calendar['Earnings Date']
                if dates and isinstance(dates, list) and len(dates) > 0:
                    earnings_date = dates[0]
                    
                    # Normalize yfinance dynamic datetime formats to standard date layouts
                    if hasattr(earnings_date, "date"): 
                        earnings_date = earnings_date.date()
                    
                    if isinstance(earnings_date, datetime.date):
                        if today <= earnings_date <= target_window_end:
                            upcoming_catalysts.append(ticker)
                            logger.info(f"Catalyst detected: {ticker} earnings confirmed on {earnings_date}")
        except Exception:
            pass
        # Rate-limit safety margin mapped to 0.3 seconds
        time.sleep(0.3)

    if not upcoming_catalysts:
        logger.info("No corporate earnings events found inside the current 72h tracking window.")
        return
        
    logger.info(f"Processing deep intelligence analytics for {len(upcoming_catalysts)} target stocks...")
    for ticker in upcoming_catalysts:
        try:
            stock = yf.Ticker(ticker)
            curr_price = stock.fast_info.last_price
            company_name = stock.info.get("shortName", ticker)
            
            # Dynamic synthesis layers
            quant_score = _compute_quant_score(stock)
            ai_score = generate_earnings_sentiment_layer(ticker, company_name)
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
            logger.error(f"Error processing deep execution pipeline for {ticker}: {e}")