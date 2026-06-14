import os
import re
import json
import random
import time
import logging
import sqlite3
import datetime
import requests
import xml.etree.ElementTree as ET
import yfinance as yf
from database import DB_NAME, was_recently_alerted, record_alert_sent, save_insider_transactions
from earnings_engine import send_alert_to_channel
from scanner import get_us_market_universe, get_nightly_winners

logger = logging.getLogger("InsiderEngine")

MIN_PURCHASE_VALUE = float(os.environ.get("INSIDER_MIN_VALUE", "500000"))
RANDOM_SAMPLE_SIZE = int(os.environ.get("INSIDER_RANDOM_SAMPLE", "50"))
COOLDOWN_DAYS      = int(os.environ.get("INSIDER_COOLDOWN_DAYS", "5"))
MAX_ALERTS_PER_RUN = int(os.environ.get("INSIDER_MAX_ALERTS", "5"))

COMPANY_TICKERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_tickers.json")

EDGAR_HEADERS = {
    "User-Agent": "ValueLens Intelligence Bot contact@valuelens.app",
    "Accept-Encoding": "gzip, deflate",
}

# Cache EDGAR quarterly index on disk — SEC updates it once daily at ~3am ET
_INDEX_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".edgar_index_cache.json")
_INDEX_CACHE_TTL_HOURS = 23


def _load_ticker_cik_map() -> dict:
    """Loads SEC EDGAR company_tickers.json and returns {TICKER: CIK_padded}."""
    try:
        with open(COMPANY_TICKERS_PATH) as f:
            data = json.load(f)
        return {
            e.get("ticker", "").upper(): str(e.get("cik_str", "")).zfill(10)
            for e in data.values()
            if e.get("ticker") and e.get("cik_str")
        }
    except Exception as e:
        logger.error(f"Failed to load company_tickers.json: {e}")
        return {}


def _parse_index_lines(text: str) -> list:
    """Parses Form 4 lines from EDGAR quarterly index text."""
    results = []
    data_start = 0
    for i, line in enumerate(text.splitlines()):
        if line.startswith("-----"):
            data_start = i + 1
            break
    for line in text.splitlines()[data_start:]:
        if not line.strip():
            continue
        parts = re.split(r'  +', line.strip())
        if len(parts) < 5 or parts[0].strip() != "4":
            continue
        try:
            cik        = parts[2].strip().zfill(10)
            date_filed = parts[3].strip()
            filename   = parts[4].strip()
            accession  = filename.split("/")[-1].replace(".txt", "").replace("-", "")
            results.append((cik, accession, date_filed))
        except Exception:
            pass
    return results


def _fetch_form4_index(year: int, quarter: int) -> list:
    """Downloads EDGAR quarterly Form 4 index with disk cache and retry logic.

    Cache: saves to .edgar_index_cache.json, valid for 23 hours (SEC updates daily).
    Retry: 3 attempts with exponential backoff before falling back to stale cache.
    Returns [(cik_padded, accession, date)].
    """
    import json as _json

    cache_key = f"{year}_QTR{quarter}"
    url = f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"

    # Check disk cache
    try:
        with open(_INDEX_CACHE_PATH) as f:
            cache = _json.load(f)
        entry = cache.get(cache_key, {})
        cached_at = datetime.datetime.fromisoformat(entry.get("cached_at", "2000-01-01"))
        age_hours = (datetime.datetime.now() - cached_at).total_seconds() / 3600
        if age_hours < _INDEX_CACHE_TTL_HOURS and entry.get("data"):
            logger.info(f"EDGAR index {cache_key}: loaded from cache ({age_hours:.1f}h old, {len(entry['data'])} entries).")
            return [tuple(x) for x in entry["data"]]
    except Exception:
        cache = {}

    # Fetch from EDGAR with retry + exponential backoff
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=EDGAR_HEADERS, timeout=30)
            if resp.status_code == 200:
                results = _parse_index_lines(resp.text)
                # Save to disk cache
                try:
                    cache[cache_key] = {
                        "cached_at": datetime.datetime.now().isoformat(),
                        "data": [list(r) for r in results]
                    }
                    with open(_INDEX_CACHE_PATH, "w") as f:
                        _json.dump(cache, f)
                except Exception as ce:
                    logger.debug(f"Cache write failed: {ce}")
                logger.info(f"EDGAR index {cache_key}: {len(results)} Form 4 filings fetched.")
                return results
            last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = str(e)
        wait = 2 ** attempt
        logger.warning(f"EDGAR index fetch attempt {attempt+1}/3 failed ({last_err}). Retrying in {wait}s...")
        time.sleep(wait)

    # Fallback: use stale cache if available
    stale = cache.get(cache_key, {}).get("data")
    if stale:
        logger.warning(f"EDGAR {cache_key} unreachable — using stale cache ({len(stale)} entries).")
        return [tuple(x) for x in stale]

    logger.error(f"EDGAR {cache_key} unavailable and no cache. Insider scan may miss filings.")
    return []


def _parse_form4_p_code(cik: str, accession: str) -> list:
    """Downloads and parses a Form 4 XML filing.

    Returns only open-market PURCHASES (transaction code P).
    Each result: insider_name, title, shares, price, total_value, date, accession_no, sec_url.
    """
    acc_dashed = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
    index_url  = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{acc_dashed}-index.htm"
    sec_index_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{acc_dashed}-index.htm"

    try:
        idx_resp = requests.get(index_url, headers=EDGAR_HEADERS, timeout=10)
        if idx_resp.status_code != 200:
            return []
        # Find all XML links — prefer non-xsl paths (raw Form 4 XML)
        xml_matches = re.findall(r'href="(/Archives/edgar/data/[^"]+\.xml)"', idx_resp.text)
        if not xml_matches:
            return []
        xml_url = None
        for m in xml_matches:
            if "xsl" not in m.lower():
                xml_url = "https://www.sec.gov" + m
                break
        if not xml_url:
            # Fallback: strip xsl subfolder from first match
            parts = [p for p in xml_matches[0].split("/") if not p.startswith("xsl")]
            xml_url = "https://www.sec.gov" + "/".join(parts)
    except Exception:
        return []

    try:
        xml_resp = requests.get(xml_url, headers=EDGAR_HEADERS, timeout=10)
        if xml_resp.status_code != 200:
            return []

        root = ET.fromstring(xml_resp.content)
        purchases = []

        # Extract insider identity
        name_el  = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
        title_el = root.find(".//reportingOwner/reportingOwnerRelationship/officerTitle")
        is_dir   = root.find(".//reportingOwner/reportingOwnerRelationship/isDirector")

        insider_name = name_el.text.strip().title() if name_el is not None else "Insider"
        if title_el is not None and title_el.text:
            title = title_el.text.strip()
        elif is_dir is not None and is_dir.text == "1":
            title = "Director"
        else:
            title = "Officer"

        # Only non-derivative transactions with code P (open-market purchase)
        for tx in root.findall(".//nonDerivativeTransaction"):
            code_el = tx.find(".//transactionCoding/transactionCode")
            if code_el is None or code_el.text != "P":
                continue  # Skip sales, gifts, option exercises — only open-market buys

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
                        "accession_no": acc_dashed,
                        "sec_url":      sec_index_url,
                    })
            except Exception:
                pass

        return purchases

    except Exception as e:
        logger.debug(f"XML parse failed for {accession}: {e}")
        return []


def _fire_insider_alert(ticker: str, purchases: list, curr_price: float,
                        is_combo: bool, cursor, conn):
    """Sends Telegram alert and persists signal + transactions to database."""
    total_value      = sum(p["total_value"] for p in purchases)
    num_transactions = len(purchases)

    top_txs = sorted(purchases, key=lambda x: x["total_value"], reverse=True)[:3]
    lines_en, lines_it = [], []

    for p in top_txs:
        name   = p["insider_name"] or "Insider"
        role   = f" — {p['title']}" if p["title"] else ""
        shares = f"{int(p['shares']):,}" if p["shares"] > 0 else "N/A"
        price  = f"${p['price']:.2f}" if p["price"] > 0 else "N/A"
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

    if is_combo:
        msg_en = (
            f"🏆 <b>ValueLens Golden Combo Alert: {ticker}</b>\n\n"
            f"<b>AI Fundamental Match + SEC Form 4 (P-code):</b>\n"
            f"Flagged as undervalued AND C-Suite is buying open-market!\n\n"
            f"{detail_en}\n\n"
            f"• Total: <b>${total_value:,.0f}</b>\n"
            f"• Current Price: <code>${curr_price:.2f}</code>"
        )
        msg_it = (
            f"🏆 <b>ValueLens Golden Combo Alert: {ticker}</b>\n\n"
            f"<b>Match AI Fondamentale + Form 4 SEC (codice P):</b>\n"
            f"Segnalata come sottovalutata E il C-Suite compra a mercato aperto!\n\n"
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

    # Persist signal summary
    cursor.execute(
        """INSERT OR IGNORE INTO insider_signals
           (ticker, date_detected, price_detected, total_value, num_transactions)
           VALUES (?, date('now'), ?, ?, ?)""",
        (ticker, curr_price, total_value, num_transactions)
    )
    conn.commit()

    # Persist individual transactions for on-demand web display
    save_insider_transactions(ticker, purchases)

    record_alert_sent(ticker, alert_type="insider")
    logger.info(f"Insider alert fired for {ticker} ({num_transactions} P-code buys, ${total_value:,.0f}, combo: {is_combo})")


def run_insider_tracking():
    """Scans for high-conviction C-suite open-market purchases using EDGAR Form 4 (P-code only).

    Workflow:
    1. Download EDGAR quarterly index (1-2 HTTP calls) to find all Form 4 filings.
    2. Match filings to scan targets (winners + random sample, ~60 tickers).
    3. For each matched ticker, parse Form 4 XML — only transaction code P (open-market purchase).
       This eliminates sales, RSU vesting, option exercises, Form 144, and stock awards.
    4. Fire alerts only for confirmed buys >= MIN_PURCHASE_VALUE.
    5. Save transactions with accession numbers for precise SEC links on the dashboard.
    """
    logger.info("Initializing Insider Tracking Engine (EDGAR Form 4, P-code filter)...")

    universe = get_us_market_universe()
    if not universe:
        logger.warning("Universe empty — aborting.")
        return

    cik_map = _load_ticker_cik_map()
    if not cik_map:
        logger.error("CIK map empty — aborting.")
        return

    # Build reverse CIK → ticker map
    cik_to_ticker = {v: k for k, v in cik_map.items()}

    # Download EDGAR quarterly index (1-2 calls covering last 90 days)
    today   = datetime.date.today()
    cutoff  = today - datetime.timedelta(days=90)
    quarters = set()
    d = cutoff
    while d <= today:
        quarters.add((d.year, (d.month - 1) // 3 + 1))
        d = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)

    all_form4 = []
    for year, qtr in sorted(quarters):
        entries = _fetch_form4_index(year, qtr)
        all_form4.extend(entries)
        time.sleep(0.5)

    if not all_form4:
        logger.warning("No Form 4 entries from EDGAR index.")
        return

    # Build CIK → [(accession, date)] map for all entries within 90 days
    cik_filings: dict = {}
    for cik, accession, date_filed in all_form4:
        try:
            if datetime.date.fromisoformat(date_filed) < cutoff:
                continue
        except Exception:
            continue
        if cik not in cik_filings:
            cik_filings[cik] = []
        cik_filings[cik].append((accession, date_filed))

    logger.info(f"EDGAR: {len(cik_filings)} CIKs with Form 4 filings in last 90 days.")

    # Build scan list: winners + random sample
    nightly_winners_list = get_nightly_winners()
    nightly_winners      = set(t.upper() for t in nightly_winners_list)
    remaining     = [t for t in universe if t.upper() not in nightly_winners]
    random_sample = random.sample(remaining, min(RANDOM_SAMPLE_SIZE, len(remaining)))
    scan_list     = nightly_winners_list + random_sample

    logger.info(f"Scan targets: {len(scan_list)} ({len(nightly_winners_list)} winners + {len(random_sample)} random)")

    conn   = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    alerts_fired = 0
    scanned      = 0

    for ticker in scan_list:
        is_winner = ticker.upper() in nightly_winners

        if not is_winner and alerts_fired >= MAX_ALERTS_PER_RUN:
            continue

        try:
            # Skip if recently alerted
            if was_recently_alerted(ticker, cooldown_days=COOLDOWN_DAYS):
                scanned += 1
                continue

            cik = cik_map.get(ticker.upper())
            if not cik or cik not in cik_filings:
                scanned += 1
                continue

            # Parse Form 4 XML — only P-code transactions
            all_purchases = []
            for accession, date_filed in cik_filings[cik][:10]:
                purchases = _parse_form4_p_code(cik, accession)
                all_purchases.extend(purchases)
                time.sleep(0.2)

            if not all_purchases:
                scanned += 1
                continue

            total_value = sum(p["total_value"] for p in all_purchases)
            if total_value < MIN_PURCHASE_VALUE:
                scanned += 1
                continue

            curr_price = yf.Ticker(ticker).fast_info.last_price
            if not curr_price:
                scanned += 1
                continue

            is_combo = ticker.upper() in nightly_winners
            _fire_insider_alert(ticker, all_purchases, curr_price, is_combo, cursor, conn)
            alerts_fired += 1

        except Exception as e:
            logger.warning(f"Insider check failed for {ticker}: {e}")

        scanned += 1
        if scanned % 20 == 0:
            logger.info(f"Progress: {scanned}/{len(scan_list)}, alerts: {alerts_fired}")
        time.sleep(0.3)

    conn.close()
    logger.info(f"Insider tracking complete. Scanned: {scanned}, Alerts fired: {alerts_fired}")