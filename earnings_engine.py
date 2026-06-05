import os
import logging
import requests
import asyncio
from datetime import datetime, timedelta
import yfinance as yf
from analyzer import generate_earnings_sentiment_layer
from database import save_earnings_prediction

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] EarningsEngine: %(message)s")
logger = logging.getLogger("EarningsEngine")

# Settings
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")

def get_earnings_calendar(days_ahead=7):
    """Fetches upcoming earnings using the ticker-agnostic approach."""
    # Nota: yfinance non ha un metodo 'Calendar' perfetto per date future remote.
    # L'approccio migliore è monitorare i titoli che segui o usare un provider.
    # Per ora, usiamo una lista di controllo basata su volumi (o un subset).
    logger.info("Fetching earnings calendar...")
    # Sostituire con logica di scraping o lista di watch-list definita
    return [{"ticker": "TSLA", "date": "2026-06-10"}] 

def send_alert_to_channel(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL_ID, "text": message, "parse_mode": "HTML"}
    requests.post(url, json=payload)

async def run_earnings_pipeline():
    logger.info("Starting Earnings Sniper Engine...")
    candidates = get_earnings_calendar()
    
    for item in candidates:
        ticker = item['ticker']
        stock = yf.Ticker(ticker)
        
        # 1. Quant Score (Fundamentals)
        info = stock.info
        curr_price = info.get("currentPrice", 1.0)
        target_mean = info.get("targetMeanPrice", curr_price)
        quant_score = min(max(((target_mean - curr_price) / curr_price) * 100, -40), 40)
        
        # 2. AI Sentiment Layer (Il nuovo motore che abbiamo creato in analyzer.py)
        ai_score = generate_earnings_sentiment_layer(ticker, info.get("longName", ticker))
        
        # 3. Final EES (Earnings Expectation Score)
        final_ees = round(quant_score + ai_score)
        
        # 4. Save to DB
        save_earnings_prediction(ticker, curr_price, "BULLISH" if final_ees > 0 else "BEARISH")
        
        # 5. Alerting
        if abs(final_ees) >= 30:
            msg = (f"🎯 <b>Sniper Alert: {ticker}</b>\n\n"
                   f"Score: <b>{final_ees}</b>\n"
                   f"Quant: {round(quant_score)} | AI Sentiment: {ai_score}\n"
                   f"<i>Deploying tracking for post-earnings accuracy check.</i>")
            send_alert_to_channel(msg)
            
    logger.info("Earnings cycle complete.")

if __name__ == "__main__":
    asyncio.run(run_earnings_pipeline())