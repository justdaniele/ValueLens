import os
import time
import logging
import datetime
import requests
import sqlite3
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from analyzer import analyze_company
from database import DB_NAME

load_dotenv()

# File and Console Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("valuelens_scanner.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ValueLensScanner")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID_IT = os.environ.get("TELEGRAM_CHANNEL_ID_IT", "")
CHANNEL_ID_EN = os.environ.get("TELEGRAM_CHANNEL_ID_EN", "")

# ── S&P 500 TICKERS (From Wikipedia) ──────────────────────────────────────────

def get_sp500_tickers():
    """Downloads the S&P 500 ticker list from Wikipedia with a spoofed User-Agent."""
    logger.info("Downloading S&P 500 list from Wikipedia...")
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        # Custom headers to bypass Wikipedia's strict bot-blocking parameters
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        # Fetch raw HTML page content first
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Parse the plain text source through pandas
        table = pd.read_html(response.text)[0]
        tickers = table['Symbol'].tolist()
        tickers = [t.replace('.', '-') for t in tickers]
        logger.info(f"Found {len(tickers)} S&P 500 tickers.")
        return tickers
    except Exception as e:
        logger.error(f"Error downloading S&P 500 list: {e}")
        return []

def get_us_market_universe():
    """Wrapper function for compatibility with earnings_engine.py."""
    sp500 = get_sp500_tickers()
    return sp500, []

# ── VALUE UNIVERSE FILTER (From S&P 500) ──────────────────────────────────────

def filter_value_universe(tickers, max_candidates=150, sleep_seconds=3,
                          pe_threshold=20):
    """Filters S&P 500 tickers to extract a preliminary value universe."""
    candidates = []
    for i, ticker in enumerate(tickers):
        if i % 50 == 0 and i > 0:
            logger.info(f"Filter progress: {i}/{len(tickers)} tickers...")
        try:
            stock = yf.Ticker(ticker)
            f_info = stock.fast_info
            
            # Dual-lookup fallback handling both modern snake_case and older camelCase
            trailing_pe = getattr(f_info, 'trailing_pe', None) or getattr(f_info, 'trailingPE', None)
            
            if trailing_pe is not None and trailing_pe > pe_threshold:
                continue
            candidates.append(ticker)
        except Exception as e:
            logger.debug(f"Skip {ticker} during filter: {e}")
        time.sleep(sleep_seconds)
    logger.info(f"Filtered Value Universe size: {len(candidates)} tickers.")
    return candidates[:max_candidates]

# ── FAST SCREEN (Lightweight fast_info) ───────────────────────────────────────

def fast_value_screen(tickers_list, max_candidates=20, sleep_seconds=3,
                      pe_threshold=20):
    """Pre‑filters using yfinance fast_info to sort by deep discount."""
    candidates = []
    for i, ticker in enumerate(tickers_list):
        if i % 50 == 0 and i > 0:
            logger.info(f"Fast‑screen progress: {i}/{len(tickers_list)} tickers...")
        try:
            stock = yf.Ticker(ticker)
            f_info = stock.fast_info
            
            # Dual-lookup fallback handling both modern snake_case and older camelCase
            high = getattr(f_info, 'year_high', None) or getattr(f_info, 'yearHigh', None)
            current = getattr(f_info, 'last_price', None) or getattr(f_info, 'lastPrice', None)
            trailing_pe = getattr(f_info, 'trailing_pe', None) or getattr(f_info, 'trailingPE', None)
            
            if high and current:
                if trailing_pe is not None and trailing_pe > pe_threshold:
                    continue
                discount = (high - current) / high
                candidates.append({
                    "ticker": ticker,
                    "discount": discount,
                    "trailing_pe": trailing_pe
                })
        except Exception as e:
            logger.debug(f"Skip {ticker} during fast screen: {e}")
        time.sleep(sleep_seconds)
        
    candidates.sort(key=lambda x: x['discount'], reverse=True)
    top_tickers = [c['ticker'] for c in candidates[:max_candidates]]
    logger.info(f"Fast‑screen top candidates: {top_tickers}")
    return top_tickers

# ── DEEP SCREEN (Full stock.info) ─────────────────────────────────────────────

def deep_value_screen(tickers_list, max_candidates=15, sleep_seconds=15):
    """Second‑pass structural filter using full stock.info sorted by analyst upside."""
    candidates = []
    for ticker in tickers_list:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            current = info.get("currentPrice") or info.get("regularMarketPrice")
            target_mean = info.get("targetMeanPrice")
            pe = info.get("trailingPE") or info.get("forwardPE")
            pb = info.get("priceToBook")
            market_cap = info.get("marketCap", 0)
            if current and target_mean and market_cap > 10e9:
                upside = (target_mean - current) / current
                candidates.append({
                    "ticker": ticker,
                    "upside": upside,
                    "pe": pe,
                    "pb": pb,
                    "market_cap": market_cap
                })
        except Exception as e:
            logger.debug(f"Skip {ticker} during deep screen: {e}")
        time.sleep(sleep_seconds)
    candidates.sort(key=lambda x: x['upside'], reverse=True)
    top_tickers = [c['ticker'] for c in candidates[:max_candidates]]
    logger.info(f"Deep‑screen top candidates: {top_tickers}")
    return top_tickers

# ── TELEGRAM LOGIC ────────────────────────────────────────────────────────────

def broadcast_to_channel(text, channel_id):
    """Dispatches text payloads to a specified Telegram channel handling length constraints."""
    if not BOT_TOKEN or not channel_id:
        logger.error(f"Missing Telegram Bot Token or Channel ID context for target: {channel_id}")
        return False
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    success_all = True
    
    for chunk in chunks:
        payload = {
            "chat_id": channel_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            r = requests.post(url, json=payload, timeout=15)
            r.raise_for_status()
            time.sleep(1)
        except Exception as e:
            logger.error(f"Telegram dispatch failed: {e} | Response: {r.text if 'r' in dir() else 'N/A'}")
            success_all = False
            
    return success_all

def morning_broadcast():
    """Routes the compiled morning reports to IT and EN channels based on DB flags."""
    logger.info("Morning broadcast triggered.")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Target channels configuration mapped by destination language and headers
    channels_setup = [
        {"id": CHANNEL_ID_IT, "lang": "it", "header": "🌅 <b>ValueLens Morning Intelligence Report</b>\n\n<i>Rilevati target altamente sottovalutati:</i>\n\n", "summary_tmpl": "🌅 Report Mattutino: inviati {} report in Italiano."},
        {"id": CHANNEL_ID_EN, "lang": "en", "header": "🌅 <b>ValueLens Morning Intelligence Report</b>\n\n<i>Highly undervalued targets detected:</i>\n\n", "summary_tmpl": "🌅 Morning Report: {} English reports sent."}
    ]
    
    for channel in channels_setup:
        if not channel["id"]:
            continue
            
        cursor.execute("""
            SELECT ticker, report_text FROM nightly_reports
            WHERE date(date_generated) = ? AND status = 'PENDING' AND lang = ?
        """, (today, channel["lang"]))
        rows = cursor.fetchall()
        
        if not rows:
            logger.info(f"No pending reports found for language locale: {channel['lang']}")
            continue
            
        # Send initial Channel Header
        broadcast_to_channel(channel["header"], channel["id"])
        
        for ticker, report_text in rows:
            formatted = f"<b>[ {ticker} ]</b>\n\n{report_text}\n\n〰️〰️〰️\n"
            success = broadcast_to_channel(formatted, channel["id"])
            if success:
                cursor.execute("""
                    UPDATE nightly_reports SET status = 'SENT' 
                    WHERE ticker = ? AND date(date_generated) = ? AND lang = ?
                """, (ticker, today, channel["lang"]))
                logger.info(f"Report successfully dispatched for {ticker} ({channel['lang']}).")
            else:
                logger.warning(f"Failed broadcasting report for {ticker} ({channel['lang']}).")
            time.sleep(2)
            
        summary = channel["summary_tmpl"].format(len(rows))
        broadcast_to_channel(summary, channel["id"])
        logger.info(summary)
        
    conn.commit()
    conn.close()

# ── DATABASE LOGIC ────────────────────────────────────────────────────────────

def save_report_to_db(ticker, report_text, lang):
    """Saves generated equity analytical briefs to local disk ledger storage."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO nightly_reports (ticker, report_text, lang, status)
            VALUES (?, ?, ?, 'PENDING')
        """, (ticker, report_text, lang))
        
        conn.commit()
        conn.close()
    except Exception as e:
         logger.error(f"Error persisting report asset {ticker} ({lang}) to database: {e}")

# ── MAIN OPERATION PIPELINE ───────────────────────────────────────────────────

def execute_nightly_routine():
    """Main orchestrator execution loop handling the bilingual nightly screening funnel."""
    logger.info("="*60)
    logger.info("Starting ValueLens Bilingual Nightly Routine (Scanner + Analyzer)")
    logger.info("="*60)
    
    # DELETE THE HASHTAG AFTER THE TESTS
  #  if datetime.datetime.now().weekday() >= 5:
  #      logger.info("Weekend detected. Equity markets closed. Aborting execution routine.")
  #      return

    sp500 = get_sp500_tickers()
    if not sp500:
        logger.error("Failed retrieving S&P 500 baseline indices.")
        return
    
    logger.info("Phase 0: Filtering value universe from S&P 500 (sleep 3s)...")
    value_universe = filter_value_universe(sp500, max_candidates=150, sleep_seconds=3)
    if not value_universe:
        logger.info("No value targets matched baseline criteria.")
        return
    
    logger.info("Phase 1: Launching Fast Price Screening (sleep 3s)...")
    fast_candidates = fast_value_screen(value_universe, max_candidates=20, sleep_seconds=3)
    if not fast_candidates:
        logger.info("No assets survived the fast screening pass.")
        return
    
    logger.info(f"Phase 2: Initiating Deep Fundamentals Screen on {len(fast_candidates)} candidates (sleep 15s)...")
    total_candidates = deep_value_screen(fast_candidates, max_candidates=15, sleep_seconds=15)
    if not total_candidates:
        logger.info("No candidates passed the deep quantitative screen.")
        return
    
    logger.info(f"Funnel successfully processed. Target securities selected for analysis: {total_candidates}")
    logger.info("Phase 3: Triggering Dual-Language Generative AI Analysis & DB Commit...")
    
    for ticker in total_candidates:
        # 1. Generate and save the report IN ENGLISH
        try:
            logger.info(f"Generating EN report for target: {ticker}...")
            report_en = analyze_company(ticker, mode="PRO", lang="en")
            save_report_to_db(ticker, report_en, "en")
            time.sleep(10)
        except Exception as e:
            logger.error(f"Deep analytical call EN failed for target {ticker}: {e}")

        # 2. Generate and save the report IN ITALIAN
        try:
            logger.info(f"Generating IT report for target: {ticker}...")
            report_it = analyze_company(ticker, mode="PRO", lang="it")
            save_report_to_db(ticker, report_it, "it")
            time.sleep(10)
        except Exception as e:
            logger.error(f"Deep analytical call IT failed for target {ticker}: {e}")

    logger.info("="*60)
    logger.info("Nightly Analytical Pipeline fully completed for both localized channels.")
    logger.info("="*60)

if __name__ == "__main__":
    execute_nightly_routine()