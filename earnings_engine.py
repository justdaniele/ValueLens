import os
import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta
import yfinance as yf
from analyzer import generate_earnings_sentiment_layer
from database import save_earnings_prediction
from scanner import get_us_market_universe

# Configure internal logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] EarningsEngine: %(message)s")
logger = logging.getLogger("EarningsEngine")

# Target Channels Setup (Bilingual Routing)
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID_IT = os.environ.get("TELEGRAM_CHANNEL_ID_IT", "")
CHANNEL_ID_EN = os.environ.get("TELEGRAM_CHANNEL_ID_EN", "")

def send_alert_to_channel(text_en: str, text_it: str = None):
    """Broadcasts localized alerts to their respective active Telegram channels."""
    if not BOT_TOKEN:
        logger.error("Missing TELEGRAM_BOT_TOKEN environment variable.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # 1. Dispatch English Payload
    if CHANNEL_ID_EN and text_en:
        try:
            r = requests.post(url, json={"chat_id": CHANNEL_ID_EN, "text": text_en, "parse_mode": "HTML"}, timeout=15)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Failed sending alert to EN channel: {e}")

    # 2. Dispatch Italian Payload (Fallback to English if custom Italian text is omitted)
    if CHANNEL_ID_IT:
        target_text = text_it if text_it else text_en
        if target_text:
            try:
                r = requests.post(url, json={"chat_id": CHANNEL_ID_IT, "text": target_text, "parse_mode": "HTML"}, timeout=15)
                r.raise_for_status()
            except Exception as e:
                logger.error(f"Failed sending alert to IT channel: {e}")

def _fetch_earnings_from_yfinance(tickers, days_ahead=3):
    """Scans a checklist of tickers to extract upcoming corporate earnings releases."""
    upcoming = []
    now = datetime.now()
    cutoff = now + timedelta(days=days_ahead)
    
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            calendar = stock.calendar
            if calendar and "Earnings Date" in calendar:
                earn_values = calendar["Earnings Date"]
                if earn_values:
                    earn_date = earn_values[0] if isinstance(earn_values, list) else earn_values
                    if isinstance(earn_date, datetime):
                        if now <= earn_date <= cutoff:
                            upcoming.append({"ticker": ticker, "date": earn_date.isoformat()})
        except Exception as e:
            logger.debug(f"Skipping earnings calendar scan for {ticker}: {e}")
    return upcoming

def get_earnings_calendar(days_ahead=3):
    """Wrapper function to parse upcoming earnings targets across the market universe."""
    sp500, _ = get_us_market_universe()
    # Processing first 50 entries to remain safe within API quotas
    return _fetch_earnings_from_yfinance(sp500[:50], days_ahead)

async def run_earnings_pipeline():
    """Executes the quantitative and generative AI evaluation for imminent earnings catalysts."""
    logger.info("Starting Bilingual Earnings Sniper Engine...")
    candidates = get_earnings_calendar()
    
    for item in candidates:
        ticker = item['ticker']
        stock = yf.Ticker(ticker)
        
        try:
            # 1. Quantitative Core Layer (Analyst target vs current price)
            info = stock.info
            curr_price = info.get("currentPrice") or info.get("regularMarketPrice") or 1.0
            target_mean = info.get("targetMeanPrice", curr_price)
            quant_score = min(max(((target_mean - curr_price) / curr_price) * 100, -40), 40)
            
            # 2. Generative AI Sentiment Layer (DeepSeek context analyzer)
            ai_score = generate_earnings_sentiment_layer(ticker, info.get("longName", ticker))
            
            # 3. Structural Synthesis (Earnings Expectation Score)
            final_ees = round(quant_score + ai_score)
            
            # 4. Commit predictive direction to storage ledger
            save_earnings_prediction(ticker, curr_price, "BULLISH" if final_ees > 0 else "BEARISH")
            
            # 5. High-conviction Bilingual Alert Broadcast
            if abs(final_ees) >= 30:
                direction_en = "BULLISH" if final_ees > 0 else "BEARISH"
                direction_it = "RIALZISTA" if final_ees > 0 else "RIBASSISTA"
                
                msg_en = (f"🎯 <b>Sniper Alert: {ticker}</b>\n\n"
                          f"Score: <b>{final_ees}</b>\n"
                          f"Quant: {round(quant_score)} | AI Sentiment: {ai_score}\n"
                          f"Prediction: <b>{direction_en}</b>")
                          
                msg_it = (f"🎯 <b>Sniper Alert: {ticker}</b>\n\n"
                          f"Punteggio: <b>{final_ees}</b>\n"
                          f"Quant: {round(quant_score)} | Sentiment AI: {ai_score}\n"
                          f"Previsione: <b>{direction_it}</b>")
                
                send_alert_to_channel(msg_en, msg_it)
                logger.info(f"Dual-channel Sniper Alert broadcasted for target: {ticker}.")
                
        except Exception as e:
            logger.error(f"Error processing earnings analysis for asset {ticker}: {e}")
            
        await asyncio.sleep(5) # Rate limiting buffer