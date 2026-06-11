import os
import random
import time
import logging
import sqlite3
import datetime
import pandas as pd
import yfinance as yf
from database import DB_NAME, was_recently_alerted, record_alert_sent
from earnings_engine import send_alert_to_channel
from scanner import get_us_market_universe, get_nightly_winners

logger = logging.getLogger("InsiderEngine")

MIN_PURCHASE_VALUE = float(os.environ.get("INSIDER_MIN_VALUE", "500000"))
RANDOM_SAMPLE_SIZE = int(os.environ.get("INSIDER_RANDOM_SAMPLE", "50"))
COOLDOWN_DAYS      = int(os.environ.get("INSIDER_COOLDOWN_DAYS", "5"))


def _get_insider_buys(ticker: str, days_back: int = 90) -> list:
    """Fetches open-market insider purchases for a ticker via yfinance.

    Returns list of dicts: insider_name, title, date, shares, price, total_value.
    Only includes purchases above MIN_PURCHASE_VALUE within the lookback window.
    """
    today  = datetime.date.today()
    cutoff = today - datetime.timedelta(days=days_back)

    try:
        df = yf.Ticker(ticker).insider_transactions
        if df is None or df.empty:
            return []

        required = {"Transaction", "Value", "Start Date", "Insider", "Position"}
        missing  = required - set(df.columns)
        if missing:
            # Fallback column names used by older yfinance versions
            required = {"Transaction", "Value", "Start Date"}
            if not required.issubset(df.columns):
                return []

        # yfinance no longer populates the Transaction field reliably.
        # Filter by value > MIN_PURCHASE_VALUE and positive shares as proxy for
        # open-market purchases. Zero-value rows are RSU grants or option exercises.
        results = []

        for _, row in df.iterrows():
            try:
                tx_date = pd.to_datetime(row["Start Date"]).date()
                if tx_date < cutoff or tx_date > today:
                    continue

                val = float(row["Value"])
                import math
                if math.isnan(val) or val < MIN_PURCHASE_VALUE:
                    continue

                shares = float(row.get("Shares", 0)) if "Shares" in row else 0.0
                price  = val / shares if shares > 0 else 0.0

                insider_name = str(row.get("Insider", "Insider")).strip().title()
                title        = str(row.get("Position", "")).strip()

                results.append({
                    "insider_name": insider_name,
                    "title":        title,
                    "date":         str(tx_date),
                    "shares":       shares,
                    "price":        price,
                    "total_value":  val,
                })
            except Exception:
                pass

        return results

    except Exception as e:
        logger.debug(f"yfinance insider fetch failed for {ticker}: {e}")
        return []


def _fire_insider_alert(ticker: str, purchases: list, curr_price: float,
                        is_combo: bool, cursor, conn):
    """Sends the Telegram alert and records the signal in the database."""
    total_value      = sum(p["total_value"] for p in purchases)
    num_transactions = len(purchases)

    # Build detail lines for top 3 purchases by value
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

    # Persist to insider_signals with value data for web dashboard display
    cursor.execute(
        """INSERT OR IGNORE INTO insider_signals
           (ticker, date_detected, price_detected, total_value, num_transactions)
           VALUES (?, date('now'), ?, ?, ?)""",
        (ticker, curr_price, total_value, num_transactions)
    )
    conn.commit()

    # Mark in unified deduplication table
    record_alert_sent(ticker, alert_type="insider")

    logger.info(f"Insider alert fired for {ticker} ({num_transactions} buys, ${total_value:,.0f}, combo: {is_combo})")


def _process_ticker(ticker: str, universe_set: set, nightly_winners: set,
                    cursor, conn) -> bool:
    """Checks a single ticker for insider buys and fires alert if criteria met.

    Returns True if an alert was fired.
    """
    # Skip if already alerted recently (unified cooldown)
    if was_recently_alerted(ticker, cooldown_days=COOLDOWN_DAYS):
        logger.debug(f"Skipping {ticker} — within cooldown window.")
        return False

    purchases = _get_insider_buys(ticker, days_back=90)
    if not purchases:
        return False

    total_value = sum(p["total_value"] for p in purchases)
    if total_value < MIN_PURCHASE_VALUE:
        return False

    curr_price = yf.Ticker(ticker).fast_info.last_price
    if not curr_price:
        return False

    is_combo = ticker in nightly_winners
    _fire_insider_alert(ticker, purchases, curr_price, is_combo, cursor, conn)
    return True


def run_insider_tracking():
    """Scans for high-conviction C-suite open-market purchases using a hybrid strategy.

    Strategy:
    1. Always check tonight's fundamental winners (from scanner nightly cache) first.
       These are the highest-priority tickers for Golden Combo alerts.
    2. Additionally check a random sample of INSIDER_RANDOM_SAMPLE tickers from the
       remaining universe. The sample rotates each night, providing full universe
       coverage over ~10 days without the time cost of scanning all 516 tickers.
    3. Unified cooldown via sent_alerts table prevents the same ticker from being
       alerted for both fundamental and insider signals within INSIDER_COOLDOWN_DAYS.

    Total tickers checked per night: len(winners) + RANDOM_SAMPLE_SIZE (~60-62).
    Estimated runtime: ~2 minutes.
    """
    logger.info("Initializing Insider Tracking Engine (hybrid mode: winners + random sample)...")

    universe = get_us_market_universe()
    if not universe:
        logger.warning("Universe empty — aborting.")
        return

    universe_set   = set(t.upper() for t in universe)
    nightly_winners_list = get_nightly_winners()
    nightly_winners      = set(t.upper() for t in nightly_winners_list)

    logger.info(f"Tonight's fundamental winners to check: {len(nightly_winners)}")

    # Build random sample from tickers NOT already in the winners list
    remaining = [t for t in universe if t.upper() not in nightly_winners]
    random_sample = random.sample(remaining, min(RANDOM_SAMPLE_SIZE, len(remaining)))

    # Combined scan list: winners first (priority), then random sample
    scan_list = nightly_winners_list + random_sample
    logger.info(f"Total insider scan targets: {len(scan_list)} ({len(nightly_winners_list)} winners + {len(random_sample)} random)")

    conn   = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    alerts_fired       = 0
    scanned            = 0
    MAX_ALERTS_PER_RUN = int(os.environ.get("INSIDER_MAX_ALERTS", "5"))

    for ticker in scan_list:
        is_winner = ticker.upper() in nightly_winners
        # Winners (potential Golden Combo) always processed — no cap applies
        # Random sample stops after MAX_ALERTS_PER_RUN non-combo alerts
        if not is_winner and alerts_fired >= MAX_ALERTS_PER_RUN:
            # Cap reached for random sample — still process any remaining winners
            if ticker.upper() not in nightly_winners:
                continue
        try:
            fired = _process_ticker(ticker.upper(), universe_set, nightly_winners, cursor, conn)
            if fired:
                alerts_fired += 1
        except Exception as e:
            logger.warning(f"Insider check failed for {ticker}: {e}")

        scanned += 1
        if scanned % 20 == 0:
            logger.info(f"Insider scan progress: {scanned}/{len(scan_list)}, alerts: {alerts_fired}")
        time.sleep(0.5)

    conn.close()
    logger.info(f"Insider tracking complete. Scanned: {scanned}, Alerts fired: {alerts_fired}")