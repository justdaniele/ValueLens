import os
import io
import csv
import json
import time
import logging
import sqlite3
import datetime
import requests
import xml.etree.ElementTree as ET
import yfinance as yf
from database import DB_NAME
from earnings_engine import send_alert_to_channel
from scanner import get_us_market_universe

logger = logging.getLogger("InsiderEngine")

MIN_PURCHASE_VALUE   = float(os.environ.get("INSIDER_MIN_VALUE", "100000"))
COMPANY_TICKERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_tickers.json")

EDGAR_HEADERS = {
    "User-Agent": "ValueLens Intelligence Bot contact@valuelens.app",
    "Accept-Encoding": "gzip, deflate",
}


def _load_ticker_cik_map() -> dict:
    """Loads SEC EDGAR company_tickers.json and returns a {TICKER: CIK_padded} map."""
    try:
        with open(COMPANY_TICKERS_PATH, "r") as f:
            data = json.load(f)
        mapping = {}
        for entry in data.values():
            ticker = entry.get("ticker", "").upper().strip()
            cik    = str(entry.get("cik_str", "")).zfill(10)
            if ticker and cik:
                mapping[ticker] = cik
        logger.info(f"Loaded {len(mapping)} ticker->CIK mappings.")
        return mapping
    except Exception as e:
        logger.error(f"Failed to load company_tickers.json: {e}")
        return {}


def _fetch_form4_index(year: int, quarter: int) -> list:
    """Downloads the EDGAR quarterly full-index for Form 4 filings.

    Returns list of (cik_padded, accession_no, date_filed) tuples.
    The quarterly index is a ~5MB flat text file listing all filings —
    far more efficient than per-ticker API calls.
    """
    url = f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"
    try:
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"EDGAR index {year}/QTR{quarter} returned {resp.status_code}")
            return []

        results = []
        lines   = resp.text.splitlines()

        # Skip header lines — find the separator line "-----" and start after it
        data_start = 0
        for i, line in enumerate(lines):
            if line.startswith("-----"):
                data_start = i + 1
                break

        for line in lines[data_start:]:
            if not line.strip():
                continue
            # Columns: Form Type | Company Name | CIK | Date Filed | File Name
            # Split on 2+ spaces to handle variable-length company names
            import re
            parts = re.split(r'  +', line.strip())
            if len(parts) < 5:
                continue
            form_type = parts[0].strip()
            if form_type != "4":
                continue
            try:
                cik        = parts[2].strip().zfill(10)
                date_filed = parts[3].strip()
                filename   = parts[4].strip()
                accession  = filename.split("/")[-1].replace(".txt", "").replace("-", "")
                results.append((cik, accession, date_filed))
            except Exception:
                pass

        logger.info(f"EDGAR index {year}/QTR{quarter}: {len(results)} Form 4 filings found.")
        return results

    except Exception as e:
        logger.warning(f"EDGAR index fetch failed for {year}/QTR{quarter}: {e}")
        return []


def _get_quarters_in_range(days_back: int = 90) -> list:
    """Returns list of (year, quarter) tuples covering the lookback window."""
    today   = datetime.date.today()
    cutoff  = today - datetime.timedelta(days=days_back)
    quarters = set()

    d = cutoff
    while d <= today:
        q = (d.month - 1) // 3 + 1
        quarters.add((d.year, q))
        # Advance by ~32 days to hit next month safely
        d = d.replace(day=28) + datetime.timedelta(days=4)
        d = d.replace(day=1)

    return sorted(quarters)


def _parse_form4_xml(cik: str, accession: str) -> list:
    """Downloads and parses a Form 4 XML filing.

    Returns list of open-market purchase dicts (transaction code P only):
        insider_name, title, date, shares, price_per_share, total_value
    """
    acc_dashed = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
    index_url  = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{acc_dashed}-index.htm"

    try:
        idx_resp = requests.get(index_url, headers=EDGAR_HEADERS, timeout=10)
        if idx_resp.status_code != 200:
            return []

        import re
        xml_match = re.search(r'href="(/Archives/edgar/data/[^"]+\.xml)"', idx_resp.text)
        if not xml_match:
            return []
        xml_url = "https://www.sec.gov" + xml_match.group(1)

    except Exception:
        return []

    try:
        xml_resp = requests.get(xml_url, headers=EDGAR_HEADERS, timeout=10)
        if xml_resp.status_code != 200:
            return []

        root = ET.fromstring(xml_resp.content)
        purchases = []

        name_el  = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
        title_el = root.find(".//reportingOwner/reportingOwnerRelationship/officerTitle")
        is_dir   = root.find(".//reportingOwner/reportingOwnerRelationship/isDirector")

        insider_name = name_el.text.strip().title() if name_el is not None else ""
        if title_el is not None and title_el.text:
            title = title_el.text.strip()
        elif is_dir is not None and is_dir.text == "1":
            title = "Director"
        else:
            title = "Officer"

        for tx in root.findall(".//nonDerivativeTransaction"):
            code_el = tx.find(".//transactionCoding/transactionCode")
            if code_el is None or code_el.text != "P":
                continue

            date_el   = tx.find(".//transactionDate/value")
            shares_el = tx.find(".//transactionAmounts/transactionShares/value")
            price_el  = tx.find(".//transactionAmounts/transactionPricePerShare/value")

            try:
                tx_date = date_el.text.strip() if date_el is not None else "N/A"
                shares  = float(shares_el.text) if shares_el is not None else 0.0
                price   = float(price_el.text)  if price_el  is not None else 0.0
                total   = shares * price
                if total >= MIN_PURCHASE_VALUE:
                    purchases.append({
                        "insider_name": insider_name,
                        "title":        title,
                        "date":         tx_date,
                        "shares":       shares,
                        "price":        price,
                        "total_value":  total,
                    })
            except Exception:
                pass

        return purchases

    except Exception as e:
        logger.debug(f"XML parse failed for {accession}: {e}")
        return []


def run_insider_tracking():
    """Scans the market universe for high-conviction C-suite open-market purchase footprints.

    Workflow:
    1. Load ticker->CIK map from local company_tickers.json (zero network calls).
    2. Download EDGAR quarterly index files (1-2 files, ~5MB each) covering last 90 days.
    3. Build a CIK->[(accession, date)] map from all Form 4 entries in the index.
    4. For each universe ticker with CIK hits, parse the Form 4 XML for P-code transactions.
    5. Fire Telegram alerts with insider name, title, shares, price, and date.
    """
    logger.info("Initializing Insider Tracking Engine (EDGAR quarterly index mode)...")
    universe = get_us_market_universe()
    if not universe:
        logger.warning("Universe empty — aborting.")
        return

    cik_map = _load_ticker_cik_map()
    if not cik_map:
        logger.error("CIK map empty — aborting.")
        return

    # Reverse map: CIK -> ticker (for matching index results back to tickers)
    cik_to_ticker = {v: k for k, v in cik_map.items()}

    # Step 1: Download quarterly index files covering the 90-day window
    cutoff   = datetime.date.today() - datetime.timedelta(days=90)
    quarters = _get_quarters_in_range(days_back=90)
    logger.info(f"Fetching EDGAR index for quarters: {quarters}")

    all_form4 = []
    for year, qtr in quarters:
        entries = _fetch_form4_index(year, qtr)
        all_form4.extend(entries)
        time.sleep(0.5)

    if not all_form4:
        logger.warning("No Form 4 entries found in EDGAR index — aborting.")
        return

    # Step 2: Filter to our universe and date range, build CIK->filings map
    universe_ciks = {cik_map[t.upper()] for t in universe if t.upper() in cik_map}
    cik_filings: dict = {}

    for cik, accession, date_filed in all_form4:
        if cik not in universe_ciks:
            continue
        try:
            if datetime.date.fromisoformat(date_filed) < cutoff:
                continue
        except Exception:
            continue
        if cik not in cik_filings:
            cik_filings[cik] = []
        cik_filings[cik].append((accession, date_filed))

    matched_tickers = len(cik_filings)
    logger.info(f"Universe tickers with Form 4 filings in last 90 days: {matched_tickers}")

    # Step 3: Process each matched ticker
    conn   = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    alerts_fired = 0

    for cik, filings in cik_filings.items():
        ticker = cik_to_ticker.get(cik)
        if not ticker or ticker not in [t.upper() for t in universe]:
            continue

        try:
            # Deduplication check
            cursor.execute("SELECT id FROM insider_signals WHERE ticker = ?", (ticker,))
            if cursor.fetchone():
                continue

            # Parse XML for each filing (cap at 5 per ticker)
            all_purchases = []
            for accession, date_filed in filings[:5]:
                purchases = _parse_form4_xml(cik, accession)
                all_purchases.extend(purchases)
                time.sleep(0.3)

            if not all_purchases:
                continue

            total_value      = sum(p["total_value"] for p in all_purchases)
            num_transactions = len(all_purchases)

            if total_value < MIN_PURCHASE_VALUE:
                continue

            curr_price = yf.Ticker(ticker).fast_info.last_price
            if not curr_price:
                continue

            # Persist signal
            cursor.execute(
                "INSERT INTO insider_signals (ticker, date_detected, price_detected) VALUES (?, date('now'), ?)",
                (ticker, curr_price)
            )
            conn.commit()

            # Build top-3 transaction detail lines
            top_txs = sorted(all_purchases, key=lambda x: x["total_value"], reverse=True)[:3]
            lines_en, lines_it = [], []
            for p in top_txs:
                name   = p["insider_name"] or "Insider"
                role   = f" — {p['title']}" if p["title"] else ""
                shares = f"{int(p['shares']):,}"
                price  = f"${p['price']:.2f}"
                val    = f"${p['total_value']:,.0f}"
                date   = p["date"]
                lines_en.append(f"• <b>{name}</b>{role}\n  {shares} shares @ {price} = {val} <i>({date})</i>")
                lines_it.append(f"• <b>{name}</b>{role}\n  {shares} azioni @ {price} = {val} <i>({date})</i>")

            remaining = num_transactions - len(top_txs)
            if remaining > 0:
                lines_en.append(f"<i>+ {remaining} other transaction(s)</i>")
                lines_it.append(f"<i>+ {remaining} altra/e transazione/i</i>")

            detail_en = "\n".join(lines_en)
            detail_it = "\n".join(lines_it)

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
                    f"<b>AI Fundamental Match + SEC Form 4:</b>\n"
                    f"Flagged as undervalued AND C-Suite is buying!\n\n"
                    f"{detail_en}\n\n"
                    f"• Total: <b>${total_value:,.0f}</b>\n"
                    f"• Current Price: <code>${curr_price:.2f}</code>"
                )
                msg_it = (
                    f"🏆 <b>ValueLens Golden Combo Alert: {ticker}</b>\n\n"
                    f"<b>Match AI Fondamentale + Form 4 SEC:</b>\n"
                    f"Segnalata come sottovalutata E il C-Suite sta comprando!\n\n"
                    f"{detail_it}\n\n"
                    f"• Totale: <b>${total_value:,.0f}</b>\n"
                    f"• Prezzo Attuale: <code>${curr_price:.2f}</code>"
                )
            else:
                msg_en = (
                    f"🟢 <b>Insider Buy Alert: {ticker}</b>\n\n"
                    f"{detail_en}\n\n"
                    f"• Total Value: <b>${total_value:,.0f}</b>\n"
                    f"• Current Price: <code>${curr_price:.2f}</code>"
                )
                msg_it = (
                    f"🟢 <b>Acquisto Insider: {ticker}</b>\n\n"
                    f"{detail_it}\n\n"
                    f"• Valore Totale: <b>${total_value:,.0f}</b>\n"
                    f"• Prezzo Attuale: <code>${curr_price:.2f}</code>"
                )

            send_alert_to_channel(msg_en, msg_it)
            logger.info(f"Insider alert fired for {ticker} ({num_transactions} buys, ${total_value:,.0f}, combo: {is_combo})")
            alerts_fired += 1

        except Exception as e:
            logger.warning(f"Insider processing skipped for {ticker}: {e}")

        time.sleep(0.3)

    conn.close()
    logger.info(f"Insider tracking complete. Matched tickers: {matched_tickers}, Alerts fired: {alerts_fired}")