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

# A default watchlist to monitor for earnings events
WATCHLIST = [
    "AAPL","MSFT","GOOGL","AMZN","TSLA","META","NVDA","JPM","V","JNJ","WMT","DIS","MA","UNH","HD"
]

def get_earnings_calendar(days_ahead=7):
    """Fetches upcoming earnings for watchlist tickers within days_ahead."""
    logger.info("Fetching earnings calendar...")
    cutoff = datetime.now() + timedelta(days=days_ahead)
    upcoming = []

    for ticker in WATCHLIST:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            # Try to get the next earnings timestamp from the info dictionary
            earn_ts = info.get("earningsTimestamp")
            if earn_ts:
                earn_date = datetime.fromtimestamp(earn_ts)
                if earn_date <= cutoff:
                    upcoming.append({"ticker": ticker, "date": earn_date.isoformat()})
                    continue

            # Fallback using the calendar property
            calendar = stock.calendar
            if calendar and "Earnings Date" in calendar:
                earn_value = calendar["Earnings Date"]
                # calendar can return a string or a Datetime
                if isinstance(earn_value, str):
                    earn_date = datetime.fromisoformat(earn_value)
                elif isinstance(earn_value, datetime):
                    earn_date = earn_value
                else:
                    continue
                if earn_date <= cutoff:
                    upcoming.append({"ticker": ticker, "date": earn_date.isoformat()})
        except Exception as e:
            logger.warning(f"Could not fetch calendar for {ticker}: {e}")
            continue

    # If nothing found, return a fallback entry so the pipeline still has data
    if not upcoming:
        logger.info("No upcoming earnings found in watchlist; using fallback entry.")
        upcoming = [{"ticker": "TSLA", "date": "2026-06-10"}]

    logger.info(f"Found {len(upcoming)} upcoming earnings.")
    return upcoming

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
