import os
import time
import logging
import datetime
import requests
import sqlite3
import pandas as pd
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

# ── LOGICA DI MERCATO (YFINANCE + WIKIPEDIA) ──────────────────────────────────

def get_us_market_universe():
    """Scarica e deduplica i ticker S&P 500 e NASDAQ 100 usando Wikipedia."""
    logger.info("Scaricamento liste ticker da Wikipedia...")
    try:
        sp500_table = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
        sp500_tickers = sp500_table['Symbol'].tolist()
        
        # Il NASDAQ-100 table index potrebbe cambiare, di solito è la tabella 4 o 5
        nasdaq_tables = pd.read_html("https://en.wikipedia.org/wiki/NASDAQ-100")
        nasdaq_table = None
        for table in nasdaq_tables:
            if 'Ticker' in table.columns:
                nasdaq_table = table
                break
        
        if nasdaq_table is not None:
             nasdaq_tickers = nasdaq_table['Ticker'].tolist()
        else:
             logger.error("Impossibile trovare la colonna 'Ticker' nella pagina del NASDAQ-100.")
             nasdaq_tickers = []
             
    except Exception as e:
        logger.error(f"Errore durante lo scaricamento delle liste ticker: {e}")
        return [], []
    
    # Pulizia ticker per Yahoo Finance (es. BRK.B diventa BRK-B)
    sp500_clean = [t.replace('.', '-') for t in sp500_tickers]
    nasdaq_clean = [t.replace('.', '-') for t in nasdaq_tickers]
    
    # Deduplicazione
    nasdaq_unique = [t for t in nasdaq_clean if t not in sp500_clean]
    logger.info(f"Trovati {len(sp500_clean)} ticker S&P 500 e {len(nasdaq_unique)} ticker unici NASDAQ 100.")
    return sp500_clean, nasdaq_unique

def fast_value_screen(tickers_list, max_candidates=15, sleep_seconds=3):
    """Filtra velocemente i ticker basandosi sullo sconto rispetto ai massimi annuali."""
    candidates = []
    
    for i, ticker in enumerate(tickers_list):
        if i % 50 == 0 and i > 0:
            logger.info(f"Analizzati {i}/{len(tickers_list)} ticker...")
            
        try:
            stock = yf.Ticker(ticker)
            f_info = stock.fast_info
            
            high = getattr(f_info, 'yearHigh', None)
            current = getattr(f_info, 'lastPrice', None) or getattr(f_info, 'last_price', None)
            market_cap = getattr(f_info, 'marketCap', 0)
            
            # Condizione minima: Cap > $2B e dati presenti
            if high and current and market_cap > 2000000000:
                discount = (high - current) / high
                candidates.append({
                    "ticker": ticker,
                    "discount": discount,
                    "market_cap": market_cap
                })
        except Exception as e:
             logger.debug(f"Skip {ticker}: dati incompleti o errore ({e})")
            
        time.sleep(sleep_seconds)
        
    candidates.sort(key=lambda x: x['discount'], reverse=True)
    top_tickers = [c['ticker'] for c in candidates[:max_candidates]]
    logger.info(f"Top candidati selezionati: {top_tickers}")
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

    # Fase 1: Ottenimento Universo e Fast Scan
    sp500, nasdaq_unique = get_us_market_universe()
    if not sp500:
         logger.error("Impossibile procedere senza le liste ticker.")
         return
    
    logger.info("Fase 1: Scansione Rapida S&P 500 (sleep 3s)...")
    sp500_top = fast_value_screen(sp500, max_candidates=15, sleep_seconds=3)
    
    logger.info("Fase 2: Scansione Rapida NASDAQ (Unici) (sleep 3s)...")
    nasdaq_top = fast_value_screen(nasdaq_unique, max_candidates=5, sleep_seconds=3)
    
    total_candidates = sp500_top + nasdaq_top
    estimated_minutes = round((len(sp500) * 3 + len(nasdaq_unique) * 3) / 60, 1)
    logger.info(f"Funnel completato. Titoli selezionati per Deep Analysis: {total_candidates} (tempo stimato ~{estimated_minutes} min)")
    
    if not total_candidates:
         logger.info("Nessun candidato trovato stasera.")
         return

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
