import os
import json
import time
import logging
import sqlite3
import datetime
import requests
import yfinance as yf
from database import DB_NAME
from earnings_engine import send_alert_to_channel
from scanner import get_us_market_universe

logger = logging.getLogger("InsiderEngine")

MIN_PURCHASE_VALUE  = float(os.environ.get("INSIDER_MIN_VALUE", "100000"))
COMPANY_TICKERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_tickers.json")

# SEC EDGAR API headers — identification required by SEC fair-use policy
EDGAR_HEADERS = {
    "User-Agent": "ValueLens Intelligence Bot contact@valuelens.app",
    "Accept-Encoding": "gzip, deflate",
}


def _load_ticker_cik_map() -> dict:
    """Loads the SEC EDGAR company_tickers.json and returns a {TICKER: CIK_str} map.

    CIK is zero-padded to 10 digits as required by the EDGAR submissions API.
    """
    try:
        with open(COMPANY_TICKERS_PATH, "r") as f:
            data = json.load(f)
        mapping = {}
        for entry in data.values():
            ticker = entry.get("ticker", "").upper().strip()
            cik    = str(entry.get("cik_str", "")).zfill(10)
            if ticker and cik:
                mapping[ticker] = cik
        logger.info(f"Loaded {len(mapping)} ticker->CIK mappings from company_tickers.json.")
        return mapping
    except Exception as e:
        logger.error(f"Failed to load company_tickers.json: {e}")
        return {}


def _fetch_recent_form4_buys(cik: str, ticker: str, days_back: int = 90) -> list:
    """Fetches recent Form 4 open-market purchase transactions for a given CIK.

    Calls the EDGAR submissions API to get recent filings, then filters for
    Form 4 filings within the lookback window.
    Returns list of dicts with keys: date, form_type.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    cutoff = datetime.date.today() - datetime.timedelta(days=days_back)

    try:
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.debug(f"EDGAR submissions returned {resp.status_code} for {ticker} (CIK {cik})")
            return []

        data = resp.json()
        filings = data.get("filings", {}).get("recent", {})

        forms       = filings.get("form", [])
        filed_dates = filings.get("filingDate", [])

        results = []
        for form, filed in zip(forms, filed_dates):
            if form != "4":
                continue
            try:
                filed_date = datetime.date.fromisoformat(filed)
                if filed_date >= cutoff:
                    results.append({"date": filed, "form_type": form})
            except Exception:
                pass

        return results

    except Exception as e:
        logger.debug(f"EDGAR submissions fetch failed for {ticker}: {e}")
        return []


def _yfinance_buy_value(ticker: str, days_back: int = 90) -> float:
    """Returns total value of open-market insider buys from yfinance for value validation.

    Called only for tickers that already have EDGAR Form 4 hits, to enrich
    the alert with a dollar value figure.
    """
    import pandas as pd
    today  = datetime.date.today()
    cutoff = today - datetime.timedelta(days=days_back)
    total  = 0.0

    try:
        df = yf.Ticker(ticker).insider_transactions
        if df is None or df.empty:
            return 0.0

        required = {"Transaction", "Value", "Start Date"}
        if not required.issubset(df.columns):
            return 0.0

        buys = df[df["Transaction"].astype(str).str.contains("Buy|Purchase", case=False, na=False)]
        for _, row in buys.iterrows():
            try:
                tx_date = pd.to_datetime(row["Start Date"]).date()
                val     = float(row["Value"])
                if cutoff <= tx_date <= today and val > 0:
                    total += val
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"yfinance value fetch failed for {ticker}: {e}")

    return total


def run_insider_tracking():
    """Scans the market universe for high-conviction C-suite open-market purchase footprints.

    Workflow:
    1. Load ticker→CIK map from local company_tickers.json (zero network calls).
    2. For each ticker in the universe that has a CIK, call EDGAR submissions API
       to check for Form 4 filings in the last 90 days.
    3. For tickers with Form 4 hits, enrich with yfinance value data.
    4. Fire Telegram alerts for new signals above MIN_PURCHASE_VALUE.

    EDGAR submissions API: ~0.3s per ticker, no ban risk with proper User-Agent.
    """
    logger.info("Initializing Insider Tracking Engine (SEC EDGAR submissions API)...")
    universe = get_us_market_universe()
    if not universe:
        logger.warning("Universe empty — aborting insider scan.")
        return

    # Load CIK map once
    cik_map = _load_ticker_cik_map()
    if not cik_map:
        logger.error("CIK map empty — cannot proceed with EDGAR scan.")
        return

    conn    = sqlite3.connect(DB_NAME)
    cursor  = conn.cursor()

    scanned      = 0
    alerts_fired = 0

    for ticker in universe:
        cik = cik_map.get(ticker.upper())

        if not cik:
            # Ticker not in EDGAR map — skip silently
            scanned += 1
            continue

        try:
            # Deduplication — skip if already tracked this cycle
            cursor.execute("SELECT id FROM insider_signals WHERE ticker = ?", (ticker,))
            if cursor.fetchone():
                scanned += 1
                time.sleep(0.3)
                continue

            # Check EDGAR for Form 4 filings in last 90 days
            form4_hits = _fetch_recent_form4_buys(cik, ticker, days_back=90)

            if not form4_hits:
                scanned += 1
                time.sleep(0.3)
                continue

            # Enrich with value data from yfinance
            total_value     = _yfinance_buy_value(ticker, days_back=90)
            num_transactions = len(form4_hits)

            # Skip if value data available but below threshold
            if total_value > 0 and total_value < MIN_PURCHASE_VALUE:
                scanned += 1
                time.sleep(0.3)
                continue

            # Fetch current price
            curr_price = yf.Ticker(ticker).fast_info.last_price
            if not curr_price:
                scanned += 1
                time.sleep(0.3)
                continue

            # Persist signal
            cursor.execute(
                "INSERT INTO insider_signals (ticker, date_detected, price_detected) VALUES (?, date('now'), ?)",
                (ticker, curr_price)
            )
            conn.commit()

            value_str = f"${total_value:,.0f}" if total_value > 0 else "N/A"

            # Golden Combo check
            cursor.execute("""
                SELECT id FROM nightly_reports
                WHERE ticker = ? AND date(date_generated) >= date('now', '-1 day')
                LIMIT 1
            """, (ticker,))
            is_combo = cursor.fetchone() is not None

            if is_combo:
                msg_en = (
                    f"🏆 <b>ValueLens Golden Combo Alert: {ticker}</b>\n\n"
                    f"<b>AI Fundamental Match:</b> This firm was flagged as highly undervalued "
                    f"by our system, and C-Suite execs are now filing open-market purchases "
                    f"with the SEC!\n\n"
                    f"• Form 4 Filings: <code>{num_transactions}</code>\n"
                    f"• Est. Value: <b>{value_str}</b>\n"
                    f"• Price: <code>${curr_price:.2f}</code>"
                )
                msg_it = (
                    f"🏆 <b>ValueLens Golden Combo Alert: {ticker}</b>\n\n"
                    f"<b>Match Matrice Fondamentale AI:</b> Questa azienda è stata contrassegnata come "
                    f"altamente sottovalutata dal bot, ed i manager stanno depositando acquisti "
                    f"a mercato aperto alla SEC!\n\n"
                    f"• Filing Form 4: <code>{num_transactions}</code>\n"
                    f"• Valore Stimato: <b>{value_str}</b>\n"
                    f"• Prezzo Attuale: <code>${curr_price:.2f}</code>"
                )
            else:
                msg_en = (
                    f"🟢 <b>Insider Buy Alert: {ticker}</b>\n\n"
                    f"C-Suite executives filed <b>{num_transactions}</b> Form 4 "
                    f"open-market purchase(s) with the SEC, totalling approx. <b>{value_str}</b> "
                    f"at ~<code>${curr_price:.2f}</code>. Structural bullish signal."
                )
                msg_it = (
                    f"🟢 <b>Acquisto Insider: {ticker}</b>\n\n"
                    f"I manager hanno depositato <b>{num_transactions}</b> Form 4 "
                    f"a mercato aperto alla SEC per un totale di circa <b>{value_str}</b> "
                    f"a ~<code>${curr_price:.2f}</code>. Segnale rialzista strutturale."
                )

            send_alert_to_channel(msg_en, msg_it)
            logger.info(f"Insider alert fired for {ticker} (Form 4 hits: {num_transactions}, combo: {is_combo})")
            alerts_fired += 1
            time.sleep(0.3)

        except Exception as e:
            logger.warning(f"Insider validation skipped for {ticker}: {e}")

        scanned += 1
        if scanned % 50 == 0:
            logger.info(f"Insider scan progress: {scanned}/{len(universe)}, alerts fired: {alerts_fired}")
        time.sleep(0.3)  # Pacing — EDGAR submissions API fair-use

    conn.close()
    logger.info(f"Insider tracking complete. Scanned: {scanned}, Alerts fired: {alerts_fired}")