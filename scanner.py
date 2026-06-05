import os
import time
import logging
import datetime
import requests
import sqlite3
import yfinance as yf
from analyzer import analyze_company
from database import DB_NAME

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

# ── STATIC VALUE UNIVERSE (~150 tickers) ──────────────────────────────────────
# Excludes high‑multiple tech, unprofitable biotech, zero‑growth utilities.
# Focus on Financials, Energy, Industrials, Materials, Consumer Defensive,
# and value‑oriented Health Care.
VALUE_UNIVERSE = [
    # Financials
    "JPM","BAC","WFC","C","GS","MS","BLK","SCHW","AXP","USB","PNC","TFC",
    "COF","BK","STT","KEY","RF","HBAN","FITB","MTB","NTRS","CFG","ZION",
    # Energy
    "XOM","CVX","COP","EOG","PXD","OXY","HAL","SLB","BKR","MPC","PSX","VLO",
    "HES","DVN","MRO","APA","CTRA","FANG","EQT","SWN","RRC","CHK","AR","PR",
    # Industrials
    "CAT","DE","GE","HON","MMM","BA","LMT","NOC","GD","RTX","TXT","COL","SPR",
    "TDG","HEI","AXON","WAB","ETN","EMR","ROK","IR","PH","DOV","SWK","SNA",
    "IEX","GWW","FAST","MSM","TTC","LECO","KMT","WSO","FERG","WCC","BECN",
    "AA","FCX","NEM","GOLD","BTG","KGC","AGI","PAAS","WPM","FNV","RGLD",
    "SSRM","CDE","HL",
    # Materials
    "APD","LIN","PX","ECL","SHW","PPG","RPM","AXTA","WDFC","SXT","KWR",
    "FMC","CF","MOS","NTR","IPI","SMG",
    # Consumer Defensive
    "PG","KO","PEP","COST","WMT","TGT","DG","DLTR","KR","SYY","CL","KMB",
    "CHD","CLX","EL","COTY","IP","WRK","AVY","BALL","CCK","SEE","GPK","SON",
    "AMCR","BERY","OI","SLGN","TRS","REYN","MYE","PTVE","PACK",
    # Health Care (value)
    "JNJ","PFE","MRK","ABBV","BMY","LLY","UNH","CVS","CI","HUM","ANTM","CNC",
    "MOH","DVA","FMS","BAX","BDX","BSX","SYK","MDT","EW","ISRG","ZBH","SNN",
    "TFX","COO","RMD","ABT","TMO","DHR","A","WAT","PKI","MHK","IRM","RRD",
    "ARC","KODK","XRX","CBT","ESI","FUL"
]

# ── FAST SCREEN (lightweight fast_info) ───────────────────────────────────────

def fast_value_screen(tickers_list, max_candidates=20, sleep_seconds=5,
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

    # Use static value universe instead of full index
    logger.info(f"Using static value universe of {len(VALUE_UNIVERSE)} tickers.")
    
    logger.info("Fase 1: Fast Screen (sleep 5s)...")
    fast_candidates = fast_value_screen(VALUE_UNIVERSE, max_candidates=20, sleep_seconds=5)
    
    if not fast_candidates:
        logger.info("Nessun candidato dopo fast screen.")
        return
    
    logger.info(f"Fase 2: Deep Screen su {len(fast_candidates)} candidati (sleep 15s)...")
    total_candidates = deep_value_screen(fast_candidates, max_candidates=15, sleep_seconds=15)
    
    if not total_candidates:
        logger.info("Nessun candidato dopo deep screen.")
        return
    
    estimated_minutes = round((len(VALUE_UNIVERSE) * 5 + len(fast_candidates) * 15) / 60, 1)
    logger.info(f"Funnel completato. Titoli selezionati per Deep Analysis: {total_candidates} (tempo stimato ~{estimated_minutes} min)")
    
    # Fase 3: Analisi DeepSeek, Salvataggio DB e Invio Telegram
    logger.info("Fase 3: Generazione Report AI e Broadcast...")
    header = "🌅 <b>ValueLens Morning Intelligence Report</b>\n\n<i>Target altamente sottovalutati rilevati:</i>\n\n"
    broadcast_to_channel(header)
    
    for ticker in total_candidates:
        logger.info(f"Avvio analisi per {ticker}...")
        try:
            # Assumiamo che analyze_company in analyzer.py gestisca l'HTML
            report = analyze_company(ticker, mode="PRO", lang="en") 
            
            # Formattazione per il canale
            formatted_report = f"<b>[ {ticker} ]</b>\n\n{report}\n\n〰️〰️〰️\n"
            
            # 1. Salva nel DB (Tolleranza ai guasti)
            save_report_to_db(ticker, formatted_report)
            
            # 2. Invia singolarmente per evitare il limite dei 4096 caratteri
            success = broadcast_to_channel(formatted_report)
            
            if success:
                 logger.info(f"Report per {ticker} pubblicato con successo.")
            else:
                 logger.warning(f"Salvataggio effettuato, ma fallito invio Telegram per {ticker}.")
            
            time.sleep(15) # Pausa tra chiamate AI/Yahoo
            
        except Exception as e:
            logger.error(f"Fallita l'analisi profonda per {ticker}: {e}")

    logger.info("="*60)
    logger.info("Routine Notturna completata.")
    logger.info("="*60)

if __name__ == "__main__":
    execute_nightly_routine()
