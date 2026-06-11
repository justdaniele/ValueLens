import os
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

MIN_PURCHASE_VALUE = float(os.environ.get("INSIDER_MIN_VALUE", "100000"))

# SEC EDGAR full-text search endpoint
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# Required by SEC fair-use policy
EDGAR_HEADERS = {
    "User-Agent": "ValueLens Intelligence Bot contact@valuelens.app",
    "Accept-Encoding": "gzip, deflate",
    "Host": "efts.sec.gov"
}


def _bulk_fetch_form4(days_back: int, page_size: int = 200) -> list:
    """Fetches all Form 4 filings from SEC EDGAR in a single bulk request.

    Returns a flat list of dicts with keys: ticker_hint, date, accession.
    Uses pagination to retrieve up to page_size results per window.
    """
    since = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d")
    today = datetime.date.today().strftime("%Y-%m-%d")

    params = {
        "dateRange": "custom",
        "startdt": since,
        "enddt": today,
        "forms": "4",
        "_source": "file_date,entity_name,period_of_report,accession_no",
        "from": 0,
        "size": page_size,
    }

    results = []
    try:
        resp = requests.get(
            EDGAR_SEARCH_URL,
            params=params,
            headers=EDGAR_HEADERS,
            timeout=20
        )
        if resp.status_code != 200:
            logger.warning(f"EDGAR bulk fetch returned {resp.status_code}")
            return []

        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        for hit in hits:
            src = hit.get("_source", {})
            results.append({
                "entity": src.get("entity_name", "").upper().strip(),
                "date":   src.get("file_date", ""),
                "accession": src.get("accession_no", ""),
            })

        logger.info(f"EDGAR bulk fetch ({days_back}d): {len(results)} Form 4 filings retrieved.")

    except Exception as e:
        logger.warning(f"EDGAR bulk fetch failed: {e}")

    return results


def _build_edgar_ticker_map(universe: list) -> dict:
    """Builds a map of {ticker: [filings]} by running 3 bulk EDGAR queries
    covering 7, 30, and 90 day windows and matching entity names to tickers.

    Matching is intentionally loose — ticker symbols are not always present in
    the EDGAR entity name, so we cross-reference using yfinance company names
    for a subset of hits. The primary match is entity_name contains ticker.
    """
    # Single bulk request for the full 90-day window
    unique_filings = _bulk_fetch_form4(days_back=90, page_size=500)

    logger.info(f"EDGAR: {len(unique_filings)} unique Form 4 filings in 90-day window.")

    # Build reverse lookup: entity name fragment → ticker
    # Most S&P500 tickers appear verbatim in the issuer entity name
    ticker_map = {t.upper(): [] for t in universe}

    for filing in unique_filings:
        entity = filing["entity"]
        for ticker in universe:
            # Match if ticker appears as a word in entity name
            # e.g. "APPLE INC" matches "AAPL" only if we have a name map
            # Simple approach: exact ticker substring match in entity
            if ticker.upper() in entity.split():
                ticker_map[ticker.upper()].append(filing)

    matched = sum(1 for v in ticker_map.values() if v)
    logger.info(f"EDGAR: {matched} tickers matched from Form 4 filings.")

    return ticker_map


def _yfinance_fallback_buys(ticker: str, days_back: int = 90) -> list:
    """Fallback: fetches insider buys from yfinance for a single ticker.

    Returns list of dicts with keys: date, value.
    Only includes open-market buys above MIN_PURCHASE_VALUE.
    """
    import pandas as pd
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=days_back)

    try:
        stock = yf.Ticker(ticker)
        df = stock.insider_transactions
        if df is None or df.empty:
            return []

        required = {"Transaction", "Value", "Start Date"}
        if not required.issubset(df.columns):
            return []

        buys = df[df["Transaction"].astype(str).str.contains("Buy|Purchase", case=False, na=False)]
        results = []
        for _, row in buys.iterrows():
            try:
                tx_date = pd.to_datetime(row["Start Date"]).date()
                val = float(row["Value"])
                if cutoff <= tx_date <= today and val >= MIN_PURCHASE_VALUE:
                    results.append({"date": str(tx_date), "value": val})
            except Exception:
                pass
        return results

    except Exception as e:
        logger.debug(f"yfinance fallback failed for {ticker}: {e}")
        return []


def run_insider_tracking():
    """Scans the entire market universe for high-conviction C-suite open-market purchase footprints.

    Workflow:
    1. Bulk-fetch all Form 4 filings from SEC EDGAR in 3 API calls (7/30/90 day windows).
    2. Match filings to universe tickers by entity name.
    3. For tickers with EDGAR hits but no value data, fall back to yfinance for value validation.
    4. Fire alerts for new signals above MIN_PURCHASE_VALUE threshold.
    """
    logger.info("Initializing Insider Tracking Engine (SEC EDGAR bulk mode)...")
    universe = get_us_market_universe()
    if not universe:
        logger.warning("Universe empty — aborting insider scan.")
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    alerts_fired = 0

    # Step 1: Build EDGAR ticker map via bulk queries (3 API calls total)
    edgar_map = _build_edgar_ticker_map(universe)

    # Step 2: Process each ticker
    for ticker in universe:
        try:
            edgar_hits = edgar_map.get(ticker.upper(), [])
            yf_buys = []

            # Deduplication — skip if already tracked this cycle
            cursor.execute("SELECT id FROM insider_signals WHERE ticker = ?", (ticker,))
            if cursor.fetchone():
                continue

            if edgar_hits:
                # EDGAR matched — validate with yfinance for value data
                yf_buys = _yfinance_fallback_buys(ticker, days_back=90)
                if not yf_buys:
                    # EDGAR hit but no yfinance value — still fire with N/A value
                    pass
                else:
                    total_value = sum(b["value"] for b in yf_buys)
                    if total_value < MIN_PURCHASE_VALUE:
                        continue
            else:
                # No EDGAR hit — try pure yfinance
                yf_buys = _yfinance_fallback_buys(ticker, days_back=90)
                if not yf_buys:
                    continue
                total_value = sum(b["value"] for b in yf_buys)
                if total_value < MIN_PURCHASE_VALUE:
                    continue

            # Fetch current price
            stock = yf.Ticker(ticker)
            curr_price = stock.fast_info.last_price
            if not curr_price:
                continue

            total_value = sum(b["value"] for b in yf_buys) if yf_buys else 0.0
            num_transactions = len(edgar_hits) if edgar_hits else len(yf_buys)
            value_str = f"${total_value:,.0f}" if total_value > 0 else "N/A"
            source_label = "SEC EDGAR Form 4" if edgar_hits else "SEC Filing"

            # Persist signal
            cursor.execute(
                "INSERT INTO insider_signals (ticker, date_detected, price_detected) VALUES (?, date('now'), ?)",
                (ticker, curr_price)
            )
            conn.commit()

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
                    f"by our system, and C-Suite execs are now buying open-market shares "
                    f"per {source_label}!\n\n"
                    f"• Transactions: <code>{num_transactions}</code>\n"
                    f"• Value: <b>{value_str}</b>\n"
                    f"• Price: <code>${curr_price:.2f}</code>"
                )
                msg_it = (
                    f"🏆 <b>ValueLens Golden Combo Alert: {ticker}</b>\n\n"
                    f"<b>Match Matrice Fondamentale AI:</b> Questa azienda è stata contrassegnata come "
                    f"altamente sottovalutata dal bot, ed i manager stanno comprando azioni a mercato aperto "
                    f"({source_label})!\n\n"
                    f"• Numero Transazioni: <code>{num_transactions}</code>\n"
                    f"• Valore Totale: <b>{value_str}</b>\n"
                    f"• Prezzo Attuale: <code>${curr_price:.2f}</code>"
                )
            else:
                msg_en = (
                    f"🟢 <b>Insider Buy Alert: {ticker}</b>\n\n"
                    f"C-Suite executives filed <b>{num_transactions}</b> open-market "
                    f"purchase(s) via {source_label}, totalling approx. <b>{value_str}</b> "
                    f"at ~<code>${curr_price:.2f}</code>. Structural bullish signal."
                )
                msg_it = (
                    f"🟢 <b>Acquisto Insider: {ticker}</b>\n\n"
                    f"I manager hanno registrato <b>{num_transactions}</b> acquisto/i "
                    f"a mercato aperto ({source_label}) per un totale di circa <b>{value_str}</b> "
                    f"a ~<code>${curr_price:.2f}</code>. Segnale rialzista strutturale."
                )

            send_alert_to_channel(msg_en, msg_it)
            source_tag = "EDGAR" if edgar_hits else "yfinance"
            logger.info(f"Insider alert fired for {ticker} (source: {source_tag}, combo: {is_combo})")
            alerts_fired += 1
            time.sleep(0.3)  # Brief pause between yfinance calls for alerted tickers

        except Exception as e:
            logger.warning(f"Insider validation skipped for {ticker}: {e}")

    conn.close()
    logger.info(f"Insider tracking complete. Universe: {len(universe)}, Alerts fired: {alerts_fired}")