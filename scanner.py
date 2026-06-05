import os
import time
import logging
import datetime
import requests
import pandas as pd
import yfinance as yf
from analyzer import analyze_company, get_value_radar

logger = logging.getLogger("ValueLensScanner")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

def get_us_market_universe():
    """Fetches and deduplicates S&P 500 and NASDAQ 100 tickers using Wikipedia."""
    try:
        sp500_table = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        sp500_tickers = sp500_table['Symbol'].tolist()
        
        nasdaq_table = pd.read_html("https://en.wikipedia.org/wiki/NASDAQ-100")[4]
        nasdaq_tickers = nasdaq_table['Ticker'].tolist()
    except Exception as e:
        logger.error(f"Failed to fetch dynamic ticker lists: {e}")
        return [], []
    
    sp500_clean = [t.replace('.', '-') for t in sp500_tickers]
    nasdaq_clean = [t.replace('.', '-') for t in nasdaq_tickers]
    
    nasdaq_unique = [t for t in nasdaq_clean if t not in sp500_clean]
    return sp500_clean, nasdaq_unique

def fast_value_screen(tickers_list, max_candidates=15):
    """Screens tickers quickly using lightweight fast_info property."""
    candidates = []
    
    for ticker in tickers_list:
        try:
            stock = yf.Ticker(ticker)
            f_info = stock.fast_info
            
            high = f_info.get('yearHigh', None)
            current = f_info.get('last_price', None)
            market_cap = f_info.get('marketCap', 0)
            
            if high and current and market_cap > 2000000000:
                discount = (high - current) / high
                candidates.append({
                    "ticker": ticker,
                    "discount": discount,
                    "market_cap": market_cap
                })
        except Exception as e:
            logger.warning(f"Skipping fast scan for {ticker}: {e}")
            
        time.sleep(3)
        
    candidates.sort(key=lambda x: x['discount'], reverse=True)
    return [c['ticker'] for c in candidates[:max_candidates]]

def broadcast_to_channel(text):
    """Sends compiled text payload to the designated Telegram channel."""
    if not BOT_TOKEN or not CHANNEL_ID:
        logger.error("Telegram environment variables missing.")
        return
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        logger.error(f"Failed broadcasting report update: {e}")

def execute_nightly_routine():
    """Orchestrates the entire multi-stage quantitative funnel and AI analysis."""
    logger.info("Executing standard market analysis routine.")
    
    sp500, nasdaq_unique = get_us_market_universe()
    if not sp500:
        return
    
    # Phase 1: S&P 500 Fast Scan
    sp500_top_candidates = fast_value_screen(sp500, max_candidates=15)
    
    # Phase 2: NASDAQ Unique Fast Scan
    nasdaq_top_candidates = fast_value_screen(nasdaq_unique, max_candidates=5)
    
    total_candidates = sp500_top_candidates + nasdaq_top_candidates
    logger.info(f"Funnel complete. Selected targets for deep analysis: {total_candidates}")
    
    compiled_reports = ["🌅 *ValueLens Morning Market Intelligence Report*\n\n"]
    
    for ticker in total_candidates:
        try:
            report = analyze_company(ticker, mode="FLASH", lang="it")
            compiled_reports.append(f"### Analysis for {ticker}\n{report}\n\n---\n\n")
            time.sleep(15)
        except Exception as e:
            logger.error(f"Failed fetching comprehensive analysis for target {ticker}: {e}")
            
    final_payload = "".join(compiled_reports)
    broadcast_to_channel(final_payload)