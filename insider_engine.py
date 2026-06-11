import os
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


def _get_recent_form4_accessions(cik: str, ticker: str, days_back: int = 90) -> list:
    """Returns list of (accession_number, filing_date) for Form 4s in the lookback window."""
    url    = f"https://data.sec.gov/submissions/CIK{cik}.json"
    cutoff = datetime.date.today() - datetime.timedelta(days=days_back)

    try:
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=15)
        if resp.status_code != 200:
            return []

        data    = resp.json()
        filings = data.get("filings", {}).get("recent", {})
        forms   = filings.get("form", [])
        dates   = filings.get("filingDate", [])
        accnums = filings.get("accessionNumber", [])

        results = []
        for form, filed, acc in zip(forms, dates, accnums):
            if form != "4":
                continue
            try:
                if datetime.date.fromisoformat(filed) >= cutoff:
                    results.append((acc.replace("-", ""), filed))
            except Exception:
                pass

        return results

    except Exception as e:
        logger.debug(f"Submissions fetch failed for {ticker}: {e}")
        return []


def _parse_form4_xml(cik: str, accession: str) -> list:
    """Downloads and parses a Form 4 XML filing.

    Returns list of dicts for open-market purchases (transaction code 'P') only:
        insider_name, title, date, shares, price_per_share, total_value
    """
    # Build the primary document URL
    acc_dashed = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
    base_url   = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/"
    index_url  = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=10"

    # Try the standard Form 4 XML filename patterns
    xml_candidates = [
        f"{base_url}form4.xml",
        f"{base_url}0000{accession}-index.htm",
    ]

    # Fetch the filing index to find the actual XML file
    index_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{acc_dashed}-index.htm"
    try:
        idx_resp = requests.get(index_url, headers=EDGAR_HEADERS, timeout=10)
        if idx_resp.status_code == 200:
            # Extract XML document link from index
            import re
            xml_match = re.search(r'href="(/Archives/edgar/data/[^"]+\.xml)"', idx_resp.text)
            if xml_match:
                xml_url = "https://www.sec.gov" + xml_match.group(1)
            else:
                return []
        else:
            return []
    except Exception:
        return []

    try:
        xml_resp = requests.get(xml_url, headers=EDGAR_HEADERS, timeout=10)
        if xml_resp.status_code != 200:
            return []

        root = ET.fromstring(xml_resp.content)
        purchases = []

        # Extract insider identity
        insider_name = ""
        title        = ""

        name_el  = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
        title_el = root.find(".//reportingOwner/reportingOwnerRelationship/officerTitle")
        is_dir   = root.find(".//reportingOwner/reportingOwnerRelationship/isDirector")
        is_off   = root.find(".//reportingOwner/reportingOwnerRelationship/isOfficer")

        if name_el is not None:
            insider_name = name_el.text.strip().title()
        if title_el is not None and title_el.text:
            title = title_el.text.strip()
        elif is_dir is not None and is_dir.text == "1":
            title = "Director"
        elif is_off is not None and is_off.text == "1":
            title = "Officer"

        # Parse non-derivative transactions (open-market stock purchases)
        for tx in root.findall(".//nonDerivativeTransaction"):
            code_el = tx.find(".//transactionCoding/transactionCode")
            if code_el is None or code_el.text != "P":
                continue  # Only open-market purchases (code P)

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
        logger.debug(f"XML parse failed for accession {accession}: {e}")
        return []


def run_insider_tracking():
    """Scans the market universe for high-conviction C-suite open-market purchase footprints.

    Workflow:
    1. Load ticker->CIK map from local company_tickers.json.
    2. Fetch recent Form 4 accession numbers via EDGAR submissions API.
    3. Parse each Form 4 XML for open-market purchase transactions (code P).
    4. Fire Telegram alerts with insider name, title, shares, price, date.
    """
    logger.info("Initializing Insider Tracking Engine (SEC EDGAR Form 4 XML parser)...")
    universe = get_us_market_universe()
    if not universe:
        logger.warning("Universe empty — aborting.")
        return

    cik_map = _load_ticker_cik_map()
    if not cik_map:
        logger.error("CIK map empty — aborting.")
        return

    conn   = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    scanned      = 0
    alerts_fired = 0

    for ticker in universe:
        cik = cik_map.get(ticker.upper())
        if not cik:
            scanned += 1
            continue

        try:
            # Deduplication check
            cursor.execute("SELECT id FROM insider_signals WHERE ticker = ?", (ticker,))
            if cursor.fetchone():
                scanned += 1
                time.sleep(0.2)
                continue

            # Step 1: get Form 4 accession numbers
            accessions = _get_recent_form4_accessions(cik, ticker, days_back=90)
            if not accessions:
                scanned += 1
                time.sleep(0.2)
                continue

            # Step 2: parse each filing XML for real open-market purchases
            all_purchases = []
            for acc, filed_date in accessions[:10]:  # Cap at 10 filings per ticker
                purchases = _parse_form4_xml(cik, acc)
                all_purchases.extend(purchases)
                time.sleep(0.2)  # Pacing between XML downloads

            if not all_purchases:
                scanned += 1
                time.sleep(0.2)
                continue

            # Aggregate
            total_value      = sum(p["total_value"] for p in all_purchases)
            num_transactions = len(all_purchases)

            if total_value < MIN_PURCHASE_VALUE:
                scanned += 1
                time.sleep(0.2)
                continue

            # Fetch current price
            curr_price = yf.Ticker(ticker).fast_info.last_price
            if not curr_price:
                scanned += 1
                time.sleep(0.2)
                continue

            # Persist signal
            cursor.execute(
                "INSERT INTO insider_signals (ticker, date_detected, price_detected) VALUES (?, date('now'), ?)",
                (ticker, curr_price)
            )
            conn.commit()

            # Build transaction detail lines (top 3 by value)
            top_txs = sorted(all_purchases, key=lambda x: x["total_value"], reverse=True)[:3]
            detail_lines_en = []
            detail_lines_it = []
            for p in top_txs:
                name  = p["insider_name"] or "Insider"
                role  = f" — {p['title']}" if p["title"] else ""
                date  = p["date"]
                val   = f"${p['total_value']:,.0f}"
                shares = f"{int(p['shares']):,}"
                price  = f"${p['price']:.2f}"
                detail_lines_en.append(f"• <b>{name}</b>{role}\n  {shares} shares @ {price} = {val} <i>({date})</i>")
                detail_lines_it.append(f"• <b>{name}</b>{role}\n  {shares} azioni @ {price} = {val} <i>({date})</i>")

            remaining = num_transactions - len(top_txs)
            if remaining > 0:
                detail_lines_en.append(f"<i>+ {remaining} other transaction(s)</i>")
                detail_lines_it.append(f"<i>+ {remaining} altra/e transazione/i</i>")

            detail_en = "\n".join(detail_lines_en)
            detail_it = "\n".join(detail_lines_it)

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
                    f"<b>AI Fundamental Match + SEC Form 4 Filing:</b>\n"
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
            logger.info(f"Insider alert fired for {ticker} ({num_transactions} purchases, ${total_value:,.0f}, combo: {is_combo})")
            alerts_fired += 1

        except Exception as e:
            logger.warning(f"Insider validation skipped for {ticker}: {e}")

        scanned += 1
        if scanned % 50 == 0:
            logger.info(f"Progress: {scanned}/{len(universe)}, alerts: {alerts_fired}")
        time.sleep(0.3)

    conn.close()
    logger.info(f"Insider tracking complete. Scanned: {scanned}, Alerts fired: {alerts_fired}")