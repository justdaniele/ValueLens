import os
import logging
import requests
import asyncio
from datetime import datetime, timedelta
import yfinance as yf
from analyzer import generate_earnings_sentiment_layer
from database import save_earnings_prediction
from scanner import get_us_market_universe

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] EarningsEngine: %(message)s")
logger = logging.getLogger("EarningsEngine")

# Settings
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")

def _fetch_earnings_from_yfinance(tickers, days_ahead):
    """Scan a list of tickers for upcoming earnings using yfinance."""
    upcoming = []
    cutoff = datetime.now() + timedelta(days=days_ahead)
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            earn_ts = info.get("earningsTimestamp")
            if earn_ts:
                earn_date = datetime.fromtimestamp(earn_ts)
                if earn_date <= cutoff:
                    upcoming.append({"ticker": ticker, "date": earn_date.isoformat()})
                    continue
            calendar = stock.calendar
            if calendar and "Earnings Date" in calendar:
                earn_value = calendar["Earnings Date"]
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
    return upcoming

def get_earnings_calendar(days_ahead=7):
    """Fetches upcoming earnings using Financial Modeling Prep API or falls back to dynamic yfinance scan."""
    logger.info("Fetching earnings calendar...")
    fmp_api_key = os.environ.get("FMP_API_KEY", "")
    upcoming = []

    if fmp_api_key:
        try:
            start_date = datetime.now().strftime("%Y-%m-%d")
            end_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            url = (f"https://financialmodelingprep.com/api/v3/earnings_calendar"
                   f"?from={start_date}&to={end_date}&apikey={fmp_api_key}")
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    ticker = item.get("symbol", "")
                    date = item.get("date", "")
                    if ticker and date:
                        upcoming.append({"ticker": ticker, "date": date})
                logger.info(f"Fetched {len(upcoming)} upcoming earnings from FMP.")
        except Exception as e:
            logger.warning(f"FMP API call failed: {e}. Falling back to yfinance approach.")
            upcoming = []

    if not upcoming:
        # Use dynamic universe from scanner
        sp500, nasdaq_unique = get_us_market_universe()
        all_tickers = sp500 + nasdaq_unique
        logger.info(f"Scanning {len(all_tickers)} tickers for upcoming earnings via yfinance...")
        upcoming = _fetch_earnings_from_yfinance(all_tickers, days_ahead)
        if not upcoming:
            logger.info("No upcoming earnings found via yfinance either.")
            # Return empty list instead of hardcoded fallback
            return []

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
