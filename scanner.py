import os
import time
import logging
import datetime
import requests
import sqlite3
import html
import pandas as pd
import yfinance as yf

# HEADLESS MATPLOTLIB CONFIGURATION FOR SERVER DEPLOYMENT
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from dotenv import load_dotenv
from analyzer import analyze_company
from database import DB_NAME, init_db

load_dotenv()

# Inherit the root logger configuration from the master daemon (bot.py)
logger = logging.getLogger("ValueLensScanner")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID_IT = os.environ.get("TELEGRAM_CHANNEL_ID_IT", "")
CHANNEL_ID_EN = os.environ.get("TELEGRAM_CHANNEL_ID_EN", "")

def get_sp500_tickers():
    """Retrieves S&P 500 tickers from local cache, updating from Wikipedia once every 7 days."""
    cache_file = "sp500_tickers.txt"
    cache_expiry_days = 7
    
    if os.path.exists(cache_file):
        file_time = datetime.datetime.fromtimestamp(os.path.getmtime(cache_file))
        if datetime.datetime.now() - file_time < datetime.timedelta(days=cache_expiry_days):
            logger.info("Loading S&P 500 universe from local storage cache.")
            with open(cache_file, "r") as f:
                return [line.strip() for line in f.readlines() if line.strip()]

    logger.info("Cache missing or expired. Syncing fresh S&P 500 roster from Wikipedia...")
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        table = pd.read_html(response.text)[0]
        tickers = [t.replace('.', '-') for t in table['Symbol'].tolist()]
        
        with open(cache_file, "w") as f:
            for ticker in tickers:
                f.write(f"{ticker}\n")
                
        logger.info(f"Successfully synchronized and cached {len(tickers)} tickers locally.")
        return tickers
    except Exception as e:
        logger.error(f"Error downloading S&P 500 list: {e}")
        if os.path.exists(cache_file):
            logger.warning("Returning expired cache file as emergency operational fallback.")
            with open(cache_file, "r") as f:
                return [line.strip() for line in f.readlines()]
        return []

def get_us_market_universe():
    """Wrapper function to export the ticker list to the earnings and insider engines."""
    return get_sp500_tickers(), []

def filter_value_universe(tickers, max_candidates=150, sleep_seconds=0.05):
    """Screens the S&P 500 using native fast_info, sorting by deep 52-week discount."""
    candidates = []
    for i, ticker in enumerate(tickers):
        if i % 100 == 0 and i > 0:
            logger.info(f"Filter progress: {i}/{len(tickers)} tickers...")
        try:
            f_info = yf.Ticker(ticker).fast_info
            high = getattr(f_info, 'year_high', None) or getattr(f_info, 'yearHigh', None)
            current = getattr(f_info, 'last_price', None) or getattr(f_info, 'lastPrice', None)
            
            if high and current:
                discount = (high - current) / high
                candidates.append({"ticker": ticker, "discount": discount})
        except Exception:
            pass
        time.sleep(sleep_seconds)
        
    candidates.sort(key=lambda x: x['discount'], reverse=True)
    top_tickers = [c['ticker'] for c in candidates[:max_candidates]]
    logger.info(f"Filtered Value Universe size: {len(top_tickers)} tickers sorted by discount.")
    return top_tickers

def fast_value_screen(tickers_list, max_candidates=20):
    """Extracts the top structural candidates from the filtered value pool."""
    top_tickers = tickers_list[:max_candidates]
    logger.info(f"Fast-screen top candidates: {top_tickers}")
    return top_tickers

def deep_value_screen(tickers_list, max_candidates=15, sleep_seconds=15, pe_threshold=25):
    """Second-pass comprehensive filter validating real P/E and Analyst Upside."""
    candidates = []
    for ticker in tickers_list:
        try:
            logger.info(f"Fetching deep fundamentals for corporate target: {ticker}...")
            info = yf.Ticker(ticker).info
            
            current = info.get("currentPrice") or info.get("regularMarketPrice")
            target_mean = info.get("targetMeanPrice")
            pe = info.get("trailingPE") or info.get("forwardPE")
            
            if pe is not None and pe > pe_threshold:
                logger.info(f"Rejected {ticker}: P/E ratio ({pe}) above threshold.")
                continue
                
            if current and target_mean:
                upside = (target_mean - current) / current
                candidates.append({"ticker": ticker, "upside": upside})
        except Exception as e:
            logger.warning(f"Skip structural lookup for {ticker}: {e}")
        time.sleep(sleep_seconds)
        
    candidates.sort(key=lambda x: x['upside'], reverse=True)
    top_tickers = [c['ticker'] for c in candidates[:max_candidates]]
    logger.info(f"Deep-screen final winners: {top_tickers}")
    return top_tickers

def generate_target_chart(ticker, current_price, target_price):
    """Generates a dark-themed institutional chart overlaid with analyst targets."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if hist.empty:
            return None
            
        plt.figure(figsize=(8, 4))
        plt.style.use('dark_background')
        plt.plot(hist.index, hist['Close'], color='cyan', linewidth=1.5, label='Price Action')
        
        if target_price:
            plt.axhline(y=target_price, color='lime', linestyle='--', linewidth=2, label=f'Analyst Target: ${target_price}')
            
        plt.scatter(hist.index[-1], current_price, color='gold', s=100, zorder=5, label='Current Price')
        
        plt.title(f"{ticker} - ValueLens Technical Target Horizon", color='white', fontweight='bold')
        plt.grid(color='gray', linestyle=':', linewidth=0.5, alpha=0.5)
        plt.legend(loc="upper left")
        plt.tight_layout()
        
        chart_path = f"chart_{ticker}.png"
        plt.savefig(chart_path, dpi=150)
        plt.close()
        return chart_path
    except Exception as e:
        logger.error(f"Failed to generate chart for {ticker}: {e}")
        return None

def broadcast_to_channel(text, channel_id, image_path=None):
    """Dispatches payloads safely using HTML escapes, attaching charts if available."""
    if not BOT_TOKEN or not channel_id:
        return False
    
    # HTML Parsing Protection Barrier
    safe_text = html.escape(text, quote=False)
    safe_text = safe_text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    safe_text = safe_text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    
    success_all = True
    
    # Attempt to dispatch as a Photo with Caption
    if image_path and os.path.exists(image_path):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        # Telegram caps photo captions at 1024 characters
        if len(safe_text) <= 1024:
            try:
                with open(image_path, 'rb') as photo:
                    r = requests.post(url, data={"chat_id": channel_id, "caption": safe_text, "parse_mode": "HTML"}, files={"photo": photo})
                    r.raise_for_status()
            except Exception as e:
                logger.error(f"Image dispatch failed: {e}")
                success_all = False
            
            # Clean up temporary chart asset
            os.remove(image_path)
            return success_all
        else:
            # Payload exceeds caption limit: send blank photo, then fallthrough to text message
            try:
                with open(image_path, 'rb') as photo:
                    requests.post(url, data={"chat_id": channel_id}, files={"photo": photo})
                os.remove(image_path)
            except Exception:
                pass

    # Standard Text Broadcast Fallback (No photo or caption limit exceeded)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunks = [safe_text[i:i+4000] for i in range(0, len(safe_text), 4000)]
    
    for chunk in chunks:
        try:
            requests.post(url, json={"chat_id": channel_id, "text": chunk, "parse_mode": "HTML"}, timeout=15).raise_for_status()
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Telegram HTML parsing failed ({e}). Attempting plain-text fallback...")
            plain_fallback = chunk.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
            try:
                requests.post(url, json={"chat_id": channel_id, "text": plain_fallback}, timeout=15)
            except Exception:
                success_all = False
                
    return success_all

def morning_broadcast():
    """Routes the compiled morning reports to IT and EN channels based on pending status."""
    logger.info("Morning broadcast triggered.")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    channels = [
        {"id": CHANNEL_ID_IT, "lang": "it", "header": "🌅 <b>ValueLens Morning Intelligence</b>\n<i>Target rilevati:</i>\n", "summary": "🌅 Inviati {} report in Italiano."},
        {"id": CHANNEL_ID_EN, "lang": "en", "header": "🌅 <b>ValueLens Morning Intelligence</b>\n<i>Targets detected:</i>\n", "summary": "🌅 {} English reports sent."}
    ]
    
    for channel in channels:
        if not channel["id"]: continue
        cursor.execute("SELECT ticker, report_text FROM nightly_reports WHERE date(date_generated) = ? AND status = 'PENDING' AND lang = ?", (today, channel["lang"]))
        rows = cursor.fetchall()
        if not rows: continue
        
        broadcast_to_channel(channel["header"], channel["id"])
        
        for ticker, report_text in rows:
            formatted = f"<b>[ {ticker} ]</b>\n\n{report_text}\n\n〰️〰️〰️"
            
            # Fetch current live parameters for charting overlay
            c_price, t_price = 0, 0
            try:
                stock_data = yf.Ticker(ticker)
                c_price = stock_data.fast_info.last_price
                t_price = stock_data.info.get("targetMeanPrice", None)
            except Exception:
                pass
                
            chart_path = generate_target_chart(ticker, c_price, t_price) if c_price else None
            success = broadcast_to_channel(formatted, channel["id"], image_path=chart_path)
            
            if success:
                cursor.execute("UPDATE nightly_reports SET status = 'SENT' WHERE ticker = ? AND date(date_generated) = ? AND lang = ?", (ticker, today, channel["lang"]))
            time.sleep(2)
            
        broadcast_to_channel(channel["summary"].format(len(rows)), channel["id"])
        
    conn.commit()
    conn.close()

def save_report_to_db(ticker, report_text, lang):
    """Saves generated equity analytical briefs to the local persistence ledger."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO nightly_reports (ticker, report_text, lang, status) VALUES (?, ?, ?, 'PENDING')", (ticker, report_text, lang))
    conn.commit()
    conn.close()

def execute_nightly_routine():
    """Main orchestrator handling the bilingual nightly fundamental screening funnel."""
    init_db()
    
    logger.info("="*60)
    logger.info("Starting ValueLens Bilingual Nightly Screening Routine")
    logger.info("="*60)
    
    sp500 = get_sp500_tickers()
    if not sp500: return
    
    logger.info("Phase 0: Filtering value universe from S&P 500...")
    value_universe = filter_value_universe(sp500)
    fast_candidates = fast_value_screen(value_universe)
    total_candidates = deep_value_screen(fast_candidates)
    
    logger.info("Phase 3: Triggering Generative AI Analysis & Storage Commit...")
    for ticker in total_candidates:
        try:
            info = yf.Ticker(ticker).info
        except Exception:
            info = None
            
        try:
            logger.info(f"Generating EN report for {ticker}...")
            report_en = analyze_company(ticker, mode="PRO", lang="en", company_info=info)
            save_report_to_db(ticker, report_en, "en")
            time.sleep(10)
        except Exception as e:
            logger.error(f"Analysis EN failed for {ticker}: {e}")

        try:
            logger.info(f"Generating IT report for {ticker}...")
            report_it = analyze_company(ticker, mode="PRO", lang="it", company_info=info)
            save_report_to_db(ticker, report_it, "it")
            time.sleep(10)
        except Exception as e:
            logger.error(f"Analysis IT failed for {ticker}: {e}")

    logger.info("="*60)
    logger.info("Nightly Analytical Pipeline completed successfully.")
    logger.info("="*60)