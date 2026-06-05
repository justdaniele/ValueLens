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

# Configurazione Log su File e Console
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
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

# ── S&P 500 TICKERS (da Wikipedia) ────────────────────────────────────────────

def get_sp500_tickers():
    """Scarica la lista dei ticker S&P 500 da Wikipedia."""
    logger.info("Scaricamento lista S&P 500 da Wikipedia...")
    try:
        table = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        tickers = table['Symbol'].tolist()
        tickers = [t.replace('.', '-') for t in tickers]
        logger.info(f"Trovati {len(tickers)} ticker S&P 500.")
        return tickers
    except Exception as e:
        logger.error(f"Errore scaricamento S&P 500: {e}")
        return []

def get_us_market_universe():
    """Wrapper per compatibilità con earnings_engine.py."""
    sp500 = get_sp500_tickers()
    return sp500, []

# ── VALUE UNIVERSE FILTER (da S&P 500) ────────────────────────────────────────

def filter_value_universe(tickers, max_candidates=150, sleep_seconds=3,
                          pe_threshold=20, min_market_cap=10e9):
    """
    Filtra i ticker S&P 500 per ottenere un universo value di ~150 ticker.
    Usa fast_info per P/E e market cap.
    """
    candidates = []
    for i, ticker in enumerate(tickers):
        if i % 50 == 0 and i > 0:
            logger.info(f"Filter progress: {i}/{len(tickers)} tickers...")
        try:
            stock = yf.Ticker(ticker)
            f_info = stock.fast_info
            market_cap = getattr(f_info, 'marketCap', 0)
            trailing_pe = getattr(f_info, 'trailingPE', None)
            if market_cap > min_market_cap:
                if trailing_pe is not None and trailing_pe > pe_threshold:
                    continue
                candidates.append(ticker)
        except Exception as e:
            logger.debug(f"Skip {ticker} during filter: {e}")
        time.sleep(sleep_seconds)
    logger.info(f"Value universe filtrato: {len(candidates)} ticker.")
    return candidates[:max_candidates]

# ── FAST SCREEN (lightweight fast_info) ───────────────────────────────────────

def fast_value_screen(tickers_list, max_candidates=20, sleep_seconds=3,
                      pe_threshold=20, min_market_cap=10e9):
    """
    Pre‑filter using yfinance fast_info.
    Skips tickers with trailing P/E above pe_threshold or market cap below min_market_cap.
    Returns the top max_candidates by discount from 52‑week high.
    """
    candidates = []
    for i, ticker in enumerate(tickers_list):
        if i % 50 == 0 and i > 0:
            logger.info(f"Fast‑screen progress: {i}/{len(tickers_list)} tickers...")
        try:
            stock = yf.Ticker(ticker)
            f_info = stock.fast_info
            high = getattr(f_info, 'yearHigh', None)
            current = getattr(f_info, 'lastPrice', None) or getattr(f_info, 'last_price', None)
            market_cap = getattr(f_info, 'marketCap', 0)
            trailing_pe = getattr(f_info, 'trailingPE', None)
            if high and current and market_cap > min_market_cap:
                # Skip high‑P/E names (value screen)
                if trailing_pe is not None and trailing_pe > pe_threshold:
                    continue
                discount = (high - current) / high
                candidates.append({
                    "ticker": ticker,
                    "discount": discount,
                    "market_cap": market_cap,
                    "trailing_pe": trailing_pe
                })
        except Exception as e:
            logger.debug(f"Skip {ticker} during fast screen: {e}")
        time.sleep(sleep_seconds)
    candidates.sort(key=lambda x: x['discount'], reverse=True)
    top_tickers = [c['ticker'] for c in candidates[:max_candidates]]
    logger.info(f"Fast‑screen top candidates: {top_tickers}")
    return top_tickers

# ── DEEP SCREEN (full stock.info) ─────────────────────────────────────────────

def deep_value_screen(tickers_list, max_candidates=15, sleep_seconds=15):
    """
    Second‑pass filter using full stock.info.
    Uses analyst target mean price to compute upside.
    Returns the top max_candidates by upside.
    """
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

# ── LOGICA TELEGRAM (Gestione 4096 Caratteri) ─────────────────────────────────

def broadcast_to_channel(text):
    """Invia il testo al canale gestendo i limiti di lunghezza di Telegram."""
    if not BOT_TOKEN or not CHANNEL_ID:
        logger.error("Variabili ambiente Telegram mancanti.")
        return False
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # Spezza in blocchi da 4000 caratteri
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    success_all = True
    
    for chunk in chunks:
        payload = {
            "chat_id": CHANNEL_ID,
            "text": chunk,
            "parse_mode": "HTML", # Usiamo HTML, è più robusto del Markdown per testi generati dall'AI
            "disable_web_page_preview": True
        }
        try:
            r = requests.post(url, json=payload, timeout=15)
            r.raise_for_status()
            time.sleep(1)
        except Exception as e:
            logger.error(f"Errore invio messaggio Telegram: {e} | R: {r.text if 'r' in dir() else 'N/A'}")
            success_all = False
            
    return success_all

def morning_broadcast():
    """Invia al canale il report mattutino basato sui report salvati durante la notte."""
    logger.info("Morning broadcast triggered.")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT ticker, report_text FROM nightly_reports
        WHERE date(date_generated) = ? AND status = 'PENDING'
    """, (today,))
    rows = cursor.fetchall()
    if not rows:
        logger.info("No pending reports for today.")
        conn.close()
        return
    # Invia header
    header = "🌅 <b>ValueLens Morning Intelligence Report</b>\n\n<i>Target altamente sottovalutati rilevati:</i>\n\n"
    broadcast_to_channel(header)
    for ticker, report_text in rows:
        formatted = f"<b>[ {ticker} ]</b>\n\n{report_text}\n\n〰️〰️〰️\n"
        success = broadcast_to_channel(formatted)
        if success:
            # Aggiorna status a 'SENT'
            cursor.execute("UPDATE nightly_reports SET status = 'SENT' WHERE ticker = ? AND date(date_generated) = ?", (ticker, today))
            logger.info(f"Morning report sent for {ticker}.")
        else:
            logger.warning(f"Failed to send morning report for {ticker}.")
        time.sleep(2)
    # Invia riepilogo
    summary = f"🌅 Morning report: {len(rows)} reports sent."
    broadcast_to_channel(summary)
    logger.info(summary)
    conn.commit()
    conn.close()

# ── LOGICA DATABASE (Salvataggio Report) ──────────────────────────────────────

def save_report_to_db(ticker, report_text):
    """Salva il report generato nel database prima dell'invio."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Creiamo la tabella se non esiste (utile in questa fase di transizione)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nightly_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_generated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ticker TEXT,
                report_text TEXT,
                status TEXT
            )
        """)
        
        cursor.execute("""
            INSERT INTO nightly_reports (ticker, report_text, status)
            VALUES (?, ?, 'PENDING')
        """, (ticker, report_text))
        
        conn.commit()
        conn.close()
    except Exception as e:
         logger.error(f"Errore salvataggio report {ticker} nel DB: {e}")

# ── ROUTINE PRINCIPALE ────────────────────────────────────────────────────────

def execute_nightly_routine():
    """L'orchestratore principale del funnel notturno."""
    logger.info("="*60)
    logger.info("Avvio ValueLens Nightly Routine (Scanner + Analyzer + Broadcast)")
    logger.info("="*60)
    
    # Controllo Week-end (opzionale se gestito via Cron)
    if datetime.datetime.now().weekday() >= 5:
        logger.info("Fine settimana rilevato. Nessun mercato aperto. Salto la scansione.")
        return

    # Step 1: Get S&P 500 tickers
    sp500 = get_sp500_tickers()
    if not sp500:
        logger.error("Impossibile ottenere lista S&P 500.")
        return
    
    # Step 2: Filter to value universe (~150 tickers)
    logger.info("Fase 0: Filtraggio universo value da S&P 500 (sleep 3s)...")
    value_universe = filter_value_universe(sp500, max_candidates=150, sleep_seconds=3)
    if not value_universe:
        logger.info("Nessun ticker value trovato.")
        return
    
    logger.info(f"Universo value: {len(value_universe)} ticker.")
    
    # Step 3: Fast screen on value universe
    logger.info("Fase 1: Fast Screen (sleep 3s)...")
    fast_candidates = fast_value_screen(value_universe, max_candidates=20, sleep_seconds=3)
    
    if not fast_candidates:
        logger.info("Nessun candidato dopo fast screen.")
        return
    
    # Step 4: Deep screen
    logger.info(f"Fase 2: Deep Screen su {len(fast_candidates)} candidati (sleep 15s)...")
    total_candidates = deep_value_screen(fast_candidates, max_candidates=15, sleep_seconds=15)
    
    if not total_candidates:
        logger.info("Nessun candidato dopo deep screen.")
        return
    
    estimated_minutes = round((len(value_universe) * 3 + len(fast_candidates) * 15) / 60, 1)
    logger.info(f"Funnel completato. Titoli selezionati per Deep Analysis: {total_candidates} (tempo stimato ~{estimated_minutes} min)")
    
    # Step 5: DeepSeek analysis and save to DB
    logger.info("Fase 3: Generazione Report AI e Salvataggio...")
    
    for ticker in total_candidates:
        logger.info(f"Avvio analisi per {ticker}...")
        try:
            report = analyze_company(ticker, mode="PRO", lang="en") 
            formatted_report = f"<b>[ {ticker} ]</b>\n\n{report}\n\n〰️〰️〰️\n"
            save_report_to_db(ticker, formatted_report)
            logger.info(f"Report per {ticker} salvato nel DB.")
            time.sleep(15)
        except Exception as e:
            logger.error(f"Fallita l'analisi profonda per {ticker}: {e}")

    logger.info("="*60)
    logger.info("Routine Notturna completata.")
    logger.info("="*60)

if __name__ == "__main__":
    execute_nightly_routine()
