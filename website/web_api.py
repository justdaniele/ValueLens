"""
ValueLens Web API — Flask backend
Run on the Raspberry Pi alongside bot.py.

Install dependencies:
    pip install flask flask-cors yfinance

Run:
    python web_api.py

The API listens on port 5000 by default.
For production behind Tailscale or a domain, use gunicorn:
    pip install gunicorn
    gunicorn -w 2 -b 0.0.0.0:5000 web_api:app
"""

import os
import re
import sqlite3
import logging
import datetime
import yfinance as yf
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ValueLensAPI: %(message)s"
)
logger = logging.getLogger("ValueLensAPI")

# Resolve paths relative to this file so the API works regardless of cwd
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = BASE_DIR  # index.html lives next to web_api.py

import time as _time
_picks_cache: dict = {"data": None, "ts": 0.0}
_PICKS_TTL_SECS = 3600

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

# Allow requests from any origin — restrict to your domain in production
CORS(app, origins=["*"])

# valuelens.db is one level up from the website/ folder
DB_NAME        = os.environ.get("VALUELENS_DB", os.path.join(BASE_DIR, "..", "valuelens.db"))
SUBSCRIBERS_DB = os.path.join(BASE_DIR, "subscribers.db")


@app.route("/")
def index():
    """Serve the main frontend page."""
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/manifest.json")
def manifest():
    return send_from_directory(STATIC_DIR, "manifest.json")


@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(STATIC_DIR, "sw.js")
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def get_db():
    """Opens a read-only connection to the main ValueLens SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def get_sub_db():
    """Opens the subscribers database (created on first run)."""
    conn = sqlite3.connect(SUBSCRIBERS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            subscribed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            active INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    return conn


def _strip_html(text: str) -> str:
    """Removes HTML tags from AI-generated report text."""
    return re.sub(r"<[^>]+>", "", text or "")


def _compute_upside(current_price, target_price):
    """Returns a formatted upside percentage string."""
    try:
        cp = float(current_price)
        tp = float(target_price)
        if cp > 0 and tp > 0:
            pct = ((tp - cp) / cp) * 100
            sign = "+" if pct >= 0 else ""
            return f"{sign}{pct:.1f}%"
    except (TypeError, ValueError):
        pass
    return None


# ─────────────────────────────────────────────
# /api/meta — hero stats
# ─────────────────────────────────────────────

@app.route("/api/meta")
def meta():
    """Returns summary stats shown in the hero section."""
    conn = get_db()
    cursor = conn.cursor()

    # Count distinct tickers scanned last night
    cursor.execute("""
        SELECT COUNT(DISTINCT ticker) FROM nightly_reports
        WHERE date(date_generated) = (SELECT date(MAX(date_generated)) FROM nightly_reports)
    """)
    tickers_scanned = cursor.fetchone()[0] or 0

    # Top picks = English reports from last night, ordered by target upside
    cursor.execute("""
        SELECT COUNT(*) FROM nightly_reports
        WHERE lang = 'en' AND date(date_generated) = (SELECT date(MAX(date_generated)) FROM nightly_reports)
    """)
    top_picks = cursor.fetchone()[0] or 0

    # Golden combos = tickers in both nightly_reports and insider_signals (last 24h)
    cursor.execute("""
        SELECT COUNT(DISTINCT nr.ticker)
        FROM nightly_reports nr
        JOIN insider_signals ins ON nr.ticker = ins.ticker
        WHERE date(nr.date_generated) >= date('now', '-3 days')
    """)
    golden_combos = cursor.fetchone()[0] or 0

    # Accuracy
    cursor.execute("SELECT value FROM metadata WHERE key = 'accuracy_wins'")
    wins_row = cursor.fetchone()
    cursor.execute("SELECT value FROM metadata WHERE key = 'accuracy_total'")
    total_row = cursor.fetchone()
    wins = int(wins_row[0]) if wins_row else 0
    total = int(total_row[0]) if total_row else 0
    accuracy_pct = f"{(wins/total)*100:.1f}%" if total > 0 else "N/A"

    # Last scan time
    cursor.execute("SELECT MAX(date_generated) FROM nightly_reports")
    row = cursor.fetchone()
    last_scan = row[0][:16] if row and row[0] else "pending"

    conn.close()
    return jsonify({
        "tickers_scanned": tickers_scanned,
        "top_picks": top_picks,
        "accuracy_pct": accuracy_pct,
        "golden_combos": golden_combos,
        "last_scan": last_scan
    })


# ─────────────────────────────────────────────
# /api/picks — top picks from last night's scan
# ─────────────────────────────────────────────

@app.route("/api/picks")
def picks():
    if _picks_cache["data"] and (_time.time() - _picks_cache["ts"]) < _PICKS_TTL_SECS:
        return jsonify(_picks_cache["data"])
    """
    Returns top picks from the most recent nightly scan, grouped by universe index.
    Response shape: {"sp500": [...], "nasdaq100": [...], "sp400": [...], "russell1000": [...]}
    Each pick also carries a universe_source field for flat-list consumers.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT ticker, report_text, lang, current_price, target_price, date_generated,
               COALESCE(universe_source, 'sp500') as universe_source
        FROM nightly_reports
        WHERE date(date_generated) = (SELECT date(MAX(date_generated)) FROM nightly_reports)
        ORDER BY date_generated DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    # Merge EN + IT per ticker
    by_ticker = {}
    for r in rows:
        t = r["ticker"]
        if t not in by_ticker:
            by_ticker[t] = {
                "ticker": t,
                "price": r["current_price"],
                "target": r["target_price"],
                "report_en": None,
                "report_it": None,
                "name": None,
                "signals": [],
                "universe_source": r["universe_source"],
            }
        if r["lang"] == "en":
            by_ticker[t]["report_en"] = r["report_text"]
            by_ticker[t]["price"]          = r["current_price"]
            by_ticker[t]["target"]         = r["target_price"]
            by_ticker[t]["universe_source"] = r["universe_source"]
            try:
                pe_val = yf.Ticker(t).info.get("trailingPE")
                by_ticker[t]["pe"] = round(float(pe_val), 1) if pe_val else None
            except Exception:
                by_ticker[t]["pe"] = None
        elif r["lang"] == "it":
            by_ticker[t]["report_it"] = r["report_text"]

    result = []
    for ticker, d in by_ticker.items():
        upside = _compute_upside(d["price"], d["target"])

        # Extract real Opportunity Score from AI report text
        score = _parse_opportunity_score(d["report_en"] or "")
        if score == 0:
            # Fallback: derive from upside if AI score not found
            try:
                if upside:
                    pct = float(upside.replace("+", "").replace("%", ""))
                    score = min(99, max(30, int(50 + pct * 0.8)))
                else:
                    score = 50
            except ValueError:
                score = 50

        # Parse structured sections and machine-readable scores from EN report
        sections = _parse_report_sections(d["report_en"] or "")
        sec_scores = _parse_section_scores(d["report_en"] or "")

        # Build signal tags from report keywords
        signals = _extract_signals(d["report_en"] or "")

        result.append({
            "ticker":         ticker,
            "name":           d.get("name") or ticker,
            "price":          d["price"],
            "target":         d["target"],
            "upside":         upside,
            "score":          score,
            "pe":             d.get("pe"),
            "report_en":      d["report_en"],
            "report_it":      d["report_it"],
            "signals":        signals,
            "sections":       sections,
            "dcf_score":      sec_scores["dcf_score"],
            "zombie_score":   sec_scores["zombie_score"],
            "short_score":    sec_scores["short_score"],
            "universe_source": d.get("universe_source", "sp500"),
        })

    # Sort by score descending, limit to top 10 per index
    result.sort(key=lambda x: x["score"], reverse=True)

    # Build grouped response — each index gets its top 10 picks
    grouped = {"sp500": [], "nasdaq100": [], "sp400": [], "russell1000": []}
    counts  = {"sp500": 0, "nasdaq100": 0, "sp400": 0, "russell1000": 0}
    for pick in result:
        src = pick.get("universe_source", "sp500")
        if src in grouped and counts.get(src, 0) < 10:
            grouped[src].append(pick)
            counts[src] = counts.get(src, 0) + 1

    _picks_cache["data"] = grouped
    _picks_cache["ts"]   = _time.time()
    return jsonify(grouped)


def _parse_opportunity_score(report_text: str) -> int:
    """Extracts the Opportunity Score integer from the AI report text."""
    import re
    match = re.search(r'Opportunity Score[:\s]*(\d{1,3})\s*/\s*100', report_text, re.IGNORECASE)
    if match:
        return min(99, max(1, int(match.group(1))))
    return 0


def _parse_section_scores(report_text: str) -> dict:
    """Extracts the machine-readable SCORES line from the AI report.
    Expected format: SCORES: DCF=X | ZOMBIE=X | SHORT=X
    Returns dict with keys dcf_score, zombie_score, short_score (integers -10 to +10).
    """
    import re
    defaults = {"dcf_score": 0, "zombie_score": 0, "short_score": 0}
    if not report_text:
        return defaults
    match = re.search(
        r"SCORES:\s*DCF=(-?\d+)\s*\|\s*ZOMBIE=(-?\d+)\s*\|\s*SHORT=(-?\d+)",
        report_text, re.IGNORECASE
    )
    if not match:
        return defaults
    clamp = lambda v: max(-10, min(10, int(v)))
    return {
        "dcf_score":    clamp(match.group(1)),
        "zombie_score": clamp(match.group(2)),
        "short_score":  clamp(match.group(3)),
    }


def _parse_report_sections(report_text: str) -> dict:
    """Splits the AI report into named sections for structured display."""
    import re
    sections = {"dcf": "", "zombie": "", "short": "", "verdict": ""}
    if not report_text:
        return sections

    # Strip HTML tags for cleaner section parsing
    clean = re.sub(r'<[^>]+>', '', report_text)

    dcf_match     = re.search(r"(?:Reverse DCF:?\*?\*?)\s*(.+?)(?=(?:Zombie|Short Interest|━|💎)|$)", clean, re.DOTALL | re.IGNORECASE)
    zombie_match  = re.search(r"(?:Zombie Detector:?\*?\*?)\s*(.+?)(?=(?:Short Interest|━|💎)|$)", clean, re.DOTALL | re.IGNORECASE)
    short_match   = re.search(r"(?:Short Interest[^:]*:?\*?\*?)\s*(.+?)(?=(?:━|💎|Verdict)|$)", clean, re.DOTALL | re.IGNORECASE)
    verdict_match = re.search(r"Verdict:\s*(.+?)(?:\n|$)", clean, re.IGNORECASE)

    if dcf_match:    sections["dcf"]     = dcf_match.group(1).strip()[:180]
    if zombie_match: sections["zombie"]  = zombie_match.group(1).strip()[:180]
    if short_match:  sections["short"]   = short_match.group(1).strip()[:180]
    if verdict_match: sections["verdict"] = verdict_match.group(1).strip()[:200]

    return sections


def _extract_signals(report_text: str) -> list:
    """Parses the AI report text and extracts key signal tags."""
    text = report_text.lower()
    signals = []
    if "undervalued" in text or "dcf" in text:
        signals.append({"label": "Undervalued (DCF)", "type": "green"})
    if "short interest" in text or "squeeze" in text:
        signals.append({"label": "Short squeeze risk", "type": "amber"})
    if "zombie" in text or "cash flow" in text:
        signals.append({"label": "FCF positive", "type": "green"})
    if "buy" in text and "analyst" in text:
        signals.append({"label": "Analyst buy", "type": "green"})
    if "earnings" in text:
        signals.append({"label": "Earnings catalyst", "type": "amber"})
    if "insider" in text:
        signals.append({"label": "Insider buy", "type": "green"})
    return signals[:4]


# ─────────────────────────────────────────────
# /api/price_history/<ticker> — 30-day price chart
# ─────────────────────────────────────────────

@app.route("/api/price_history/<ticker>")
def price_history(ticker: str):
    """Returns 30-day price history with RSI(14) and MA20 for chart overlays."""
    try:
        stock = yf.Ticker(ticker)
        # Fetch 60d to have enough data for RSI(14) warmup period
        hist = stock.history(period="60d")
        if hist.empty:
            return jsonify({"error": "No data"}), 404

        closes = hist["Close"]

        # RSI(14) — computed manually, no external dependency
        delta = closes.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, float("inf"))
        rsi   = (100 - (100 / (1 + rs))).round(1)

        # MA20
        ma20 = closes.rolling(20).mean().round(2)

        # Return only last 30 trading days
        hist30 = hist.tail(30)
        idx30  = hist30.index

        labels  = [str(d.date()) for d in idx30]
        prices  = [round(float(p), 2) for p in hist30["Close"]]
        rsi_vals = [None if str(v) == "nan" else float(v) for v in rsi.reindex(idx30)]
        ma20_vals = [None if str(v) == "nan" else float(v) for v in ma20.reindex(idx30)]

        # Current RSI for label
        current_rsi = next((v for v in reversed(rsi_vals) if v is not None), None)

        return jsonify({
            "labels":  labels,
            "prices":  prices,
            "rsi":     rsi_vals,
            "ma20":    ma20_vals,
            "current_rsi": round(current_rsi, 1) if current_rsi else None,
        })
    except Exception as e:
        logger.error(f"Price history failed for {ticker}: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# /api/live_prices — current prices, dual mode
# ─────────────────────────────────────────────

# Small in-memory cache so a 10s frontend poll doesn't hammer yfinance when
# multiple browser tabs/users are open at once. Keyed by ticker, values are
# {"price": float, "change": float, "ts": epoch_seconds}.
_live_price_cache: dict = {}
_LIVE_PRICE_TTL_SECS = 8  # slightly under the 10s frontend poll interval


def _fetch_live_quote(ticker: str):
    """Fetches a single ticker's price + % change via yfinance fast_info.
    Returns None on failure. Uses fast_info exclusively — no direct Yahoo
    HTTP calls, which get rate-limited/blocked without a browser session.
    """
    try:
        info = yf.Ticker(ticker).fast_info
        price = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
        prev_close = getattr(info, "previous_close", None) or getattr(info, "previousClose", None)
        if not price:
            return None
        change = None
        if prev_close and prev_close > 0:
            change = round(((price - prev_close) / prev_close) * 100, 2)
        return {"price": round(float(price), 2), "change": change if change is not None else 0.0}
    except Exception as e:
        logger.debug(f"live_prices: could not fetch {ticker}: {e}")
        return None


def _get_live_quotes(tickers: list) -> dict:
    """Returns {ticker: {price, change}} for the given tickers, using the
    short-lived in-memory cache to avoid refetching within _LIVE_PRICE_TTL_SECS.
    """
    now = _time.time()
    result = {}
    to_fetch = []

    for t in tickers:
        cached = _live_price_cache.get(t)
        if cached and (now - cached["ts"]) < _LIVE_PRICE_TTL_SECS:
            result[t] = {"price": cached["price"], "change": cached["change"]}
        else:
            to_fetch.append(t)

    for t in to_fetch:
        quote = _fetch_live_quote(t)
        if quote:
            result[t] = quote
            _live_price_cache[t] = {**quote, "ts": now}

    return result


@app.route("/api/live_prices")
def live_prices():
    """
    Dual-mode live price endpoint.

    EXPLICIT MODE — called with ?tickers=AAPL,MSFT (used by the insider
    table and anywhere a fixed ticker list is known ahead of time):
    returns {ticker: {price, change}}.

    AUTO MODE — called with no params (used by the dashboard-wide 10s
    poller covering hero stats, pick cards, and the virtual portfolio):
    auto-detects every ticker currently relevant — last night's picks,
    active insider signals, and open virtual portfolio positions — and
    returns the same {ticker: {price, change}} shape for all of them.

    Both modes share the same short-lived cache, so overlapping requests
    (e.g. picks + portfolio both wanting AAPL) only hit yfinance once.
    """
    tickers_param = request.args.get("tickers", "")

    if tickers_param:
        tickers = [t.strip().upper() for t in tickers_param.split(",") if t.strip()][:30]
        return jsonify(_get_live_quotes(tickers))

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT ticker FROM nightly_reports
        WHERE date(date_generated) = (SELECT date(MAX(date_generated)) FROM nightly_reports)
    """)
    pick_tickers = [r["ticker"] for r in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT ticker FROM insider_signals WHERE status = 'ACTIVE'")
    insider_tickers = [r["ticker"] for r in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT ticker FROM virtual_positions WHERE status = 'OPEN'")
    portfolio_tickers = [r["ticker"] for r in cursor.fetchall()]

    conn.close()

    all_tickers = list(set(pick_tickers + insider_tickers + portfolio_tickers))
    if not all_tickers:
        return jsonify({})

    return jsonify(_get_live_quotes(all_tickers))


# ─────────────────────────────────────────────
# /api/insiders — insider buy signals
# ─────────────────────────────────────────────

@app.route("/api/insiders")
def insiders():
    """Returns all active insider buy signals from the database."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticker, date_detected, price_detected, total_value, num_transactions, status
        FROM insider_signals
        WHERE status = 'ACTIVE'
        ORDER BY date_detected DESC
        LIMIT 25
    """)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        tv = r["total_value"] if r["total_value"] else 0.0
        result.append({
            "ticker":           r["ticker"],
            "date_detected":    r["date_detected"],
            "price_detected":   r["price_detected"],
            "num_transactions": r["num_transactions"] or 0,
            "total_value":      tv if tv > 0 else None,
            "value_formatted":  f"${tv:,.0f}" if tv and tv > 0 else None,
            "status":           r["status"],
        })
    return jsonify(result)


# ─────────────────────────────────────────────
# /api/golden_combos — AI pick + insider buy overlap
# ─────────────────────────────────────────────

@app.route("/api/golden_combos")
def golden_combos():
    """
    Returns tickers that appear in both nightly_reports (last 7 days)
    and insider_signals simultaneously — the Golden Combo condition.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT nr.ticker, nr.current_price, nr.target_price,
               nr.date_generated, ins.date_detected
        FROM nightly_reports nr
        JOIN insider_signals ins ON nr.ticker = ins.ticker
        WHERE date(nr.date_generated) >= date('now', '-7 days')
          AND nr.lang = 'en'
        ORDER BY nr.date_generated DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        upside = _compute_upside(r["current_price"], r["target_price"])
        score = 50
        try:
            if upside:
                pct = float(upside.replace("+", "").replace("%", ""))
                score = min(99, max(50, int(60 + pct * 0.8)))
        except ValueError:
            pass

        tv = r["total_value"] if r["total_value"] else 0.0
        result.append({
            "ticker":         r["ticker"],
            "name":           r["ticker"],
            "price":          r["current_price"],
            "target":         r["target_price"],
            "score":          score,
            "insider_value":  f"${tv:,.0f}" if tv and tv > 0 else None,
            "price_at_detection": r["current_price"],
            "date_detected": r["date_detected"][:10] if r["date_detected"] else None,
            "description": (
                f"AI fundamental scan flagged {r['ticker']} as high-conviction, "
                f"and C-suite executives have executed open-market purchases. "
                f"Dual-signal alignment — the strongest setup ValueLens tracks."
            )
        })
    return jsonify(result)


# ─────────────────────────────────────────────
# /api/subscribe — email capture
# ─────────────────────────────────────────────

@app.route("/api/insider_transactions/<ticker>")
def insider_transactions(ticker):
    """Returns transaction details for a specific ticker on-demand (called when user expands row)."""
    import pandas as pd, math, datetime as dt
    cutoff = dt.date.today() - dt.timedelta(days=90)
    transactions = []
    try:
        df = yf.Ticker(ticker.upper()).insider_transactions
        if df is not None and not df.empty and "Value" in df.columns:
            for _, row in df.iterrows():
                try:
                    tx_date = pd.to_datetime(row["Start Date"]).date()
                    val     = float(row["Value"])
                    if math.isnan(val) or val < 500000 or tx_date < cutoff:
                        continue
                    shares = float(row.get("Shares", 0)) if "Shares" in row else 0.0
                    price  = val / shares if shares > 0 else 0.0
                    transactions.append({
                        "insider_name": str(row.get("Insider", "")).strip().title(),
                        "title":        str(row.get("Position", "")).strip(),
                        "date":         str(tx_date),
                        "shares":       shares,
                        "price":        round(price, 2),
                        "total_value":  val,
                    })
                except Exception:
                    pass
    except Exception:
        pass
    return jsonify(transactions[:5])


@app.route("/api/earnings")
def earnings():
    """Returns earnings sniper predictions, deduplicated to one row per ticker
    (the most recent signal wins), split into two groups:

      - upcoming: earnings_date is in the future (or unknown and not yet
        evaluated by the 24h fallback timer)
      - released: earnings_date has passed (or the 24h fallback fired),
        limited to the last 14 days so the list doesn't grow unbounded

    Response shape: {"upcoming": [...], "released": [...]}
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticker, price_at_signal, prediction, ees_score, is_evaluated,
               timestamp, earnings_date
        FROM earnings_predictions
        WHERE date(timestamp) >= date('now', '-14 days')
        ORDER BY timestamp DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    # Deduplicate — keep only the most recent row per ticker
    # (rows are already ordered DESC by timestamp, so first occurrence wins)
    seen = set()
    deduped = []
    for r in rows:
        if r["ticker"] in seen:
            continue
        seen.add(r["ticker"])
        deduped.append(r)

    now = datetime.datetime.now()
    upcoming_list = []
    released_list = []

    for r in deduped:
        # Fetch current price for live change calculation
        curr_price = None
        try:
            curr_price = yf.Ticker(r["ticker"]).fast_info.last_price
        except Exception:
            pass

        signal_price = r["price_at_signal"] or 0
        change_pct = None
        if curr_price and signal_price > 0:
            change_pct = round(((curr_price - signal_price) / signal_price) * 100, 2)

        entry = {
            "ticker":        r["ticker"],
            "prediction":    r["prediction"],
            "ees_score":     r["ees_score"] or 0,
            "price_signal":  signal_price,
            "price_current": round(curr_price, 2) if curr_price else None,
            "change_pct":    change_pct,
            "timestamp":     r["timestamp"][:10] if r["timestamp"] else None,
            "earnings_date": r["earnings_date"][:10] if r["earnings_date"] else None,
        }

        # Determine Upcoming vs Released using the real earnings_date when available.
        # Falls back to the is_evaluated flag (24h timer) for legacy rows without it.
        is_released = False
        if r["earnings_date"]:
            try:
                ed = datetime.datetime.fromisoformat(r["earnings_date"])
                is_released = ed <= now
            except ValueError:
                is_released = bool(r["is_evaluated"])
        else:
            is_released = bool(r["is_evaluated"])

        if is_released:
            released_list.append(entry)
        else:
            upcoming_list.append(entry)

    return jsonify({"upcoming": upcoming_list, "released": released_list})


@app.route("/api/portfolio")
def portfolio():
    """Returns virtual portfolio summary and all positions."""
    conn = get_db()
    cursor = conn.cursor()

    STARTING_CASH = 100_000.0

    # Open positions with live P&L
    cursor.execute("""
        SELECT id, ticker, entry_price, target_price, shares,
               position_value, opened_at, status
        FROM virtual_positions WHERE status = 'OPEN'
        ORDER BY opened_at DESC
    """)
    open_rows = cursor.fetchall()

    # Closed positions
    cursor.execute("""
        SELECT id, ticker, entry_price, target_price, shares,
               position_value, opened_at, closed_at,
               close_price, close_reason, pnl_pct
        FROM virtual_positions WHERE status = 'CLOSED'
        ORDER BY closed_at DESC LIMIT 50
    """)
    closed_rows = cursor.fetchall()
    conn.close()

    open_positions = []
    total_invested = 0.0
    total_unrealized_pnl = 0.0

    # Fetch all open-position prices in one batch via the shared short-lived
    # cache — avoids hammering yfinance on every 10s portfolio page poll.
    open_tickers = [r["ticker"] for r in open_rows]
    live_quotes  = _get_live_quotes(open_tickers) if open_tickers else {}

    for r in open_rows:
        quote = live_quotes.get(r["ticker"])
        curr_price = quote["price"] if quote else None

        entry   = r["entry_price"]
        shares  = r["shares"]
        pos_val = r["position_value"]
        curr_val = (curr_price * shares) if curr_price else pos_val
        pnl_pct  = ((curr_price - entry) / entry * 100) if curr_price else 0.0
        pnl_abs  = curr_val - pos_val

        total_invested       += pos_val
        total_unrealized_pnl += pnl_abs

        open_positions.append({
            "id":            r["id"],
            "ticker":        r["ticker"],
            "entry_price":   entry,
            "target_price":  r["target_price"],
            "shares":        round(shares, 4),
            "cost_basis":    pos_val,
            "current_price": round(curr_price, 2) if curr_price else None,
            "current_value": round(curr_val, 2),
            "pnl_pct":       round(pnl_pct, 2),
            "pnl_abs":       round(pnl_abs, 2),
            "opened_at":     r["opened_at"][:10] if r["opened_at"] else None,
        })

    closed_positions = []
    total_realized_pnl = 0.0

    for r in closed_rows:
        pnl_abs = ((r["pnl_pct"] or 0) / 100) * r["position_value"]
        total_realized_pnl += pnl_abs
        closed_positions.append({
            "ticker":       r["ticker"],
            "entry_price":  r["entry_price"],
            "close_price":  r["close_price"],
            "pnl_pct":      round(r["pnl_pct"] or 0, 2),
            "pnl_abs":      round(pnl_abs, 2),
            "close_reason": r["close_reason"],
            "opened_at":    r["opened_at"][:10] if r["opened_at"] else None,
            "closed_at":    r["closed_at"][:10] if r["closed_at"] else None,
        })

    cash_available   = max(0.0, STARTING_CASH - total_invested)
    portfolio_value  = cash_available + total_invested + total_unrealized_pnl
    total_return_pct = ((portfolio_value - STARTING_CASH) / STARTING_CASH) * 100

    # Allocation breakdown for pie chart
    allocation = [{"ticker": p["ticker"], "value": round(p["current_value"], 2)} for p in open_positions]
    allocation.append({"ticker": "CASH", "value": round(cash_available, 2)})

    return jsonify({
        "summary": {
            "starting_cash":       STARTING_CASH,
            "cash_available":      round(cash_available, 2),
            "total_invested":      round(total_invested, 2),
            "portfolio_value":     round(portfolio_value, 2),
            "total_return_pct":    round(total_return_pct, 2),
            "unrealized_pnl":      round(total_unrealized_pnl, 2),
            "realized_pnl":        round(total_realized_pnl, 2),
            "open_positions":      len(open_positions),
        },
        "open_positions":   open_positions,
        "closed_positions": closed_positions,
        "allocation":       allocation,
    })



@app.route("/api/subscribe", methods=["POST"])
def subscribe():
    """
    Saves a subscriber email to the local SQLite subscribers database.
    Call /api/send_digest to email all subscribers (see below).
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not email or "@" not in email or "." not in email:
        return jsonify({"error": "Invalid email address."}), 400

    conn = get_sub_db()
    try:
        conn.execute("INSERT INTO subscribers (email) VALUES (?)", (email,))
        conn.commit()
        logger.info(f"New subscriber: {email}")
        return jsonify({"ok": True, "message": "Subscribed successfully."})
    except sqlite3.IntegrityError:
        return jsonify({"ok": True, "message": "Already subscribed."})
    finally:
        conn.close()


@app.route("/api/subscribers")
def list_subscribers():
    """
    Admin endpoint — lists all active subscribers.
    Protect this in production (e.g. require a secret header or bind to localhost only).
    """
    conn = get_sub_db()
    rows = conn.execute(
        "SELECT email, subscribed_at FROM subscribers WHERE active = 1 ORDER BY subscribed_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([{"email": r[0], "subscribed_at": r[1]} for r in rows])


# ─────────────────────────────────────────────
# /api/send_digest — broadcast morning email to all subscribers
# ─────────────────────────────────────────────
#
# This endpoint is called from bot.py after morning_broadcast() runs.
# It reads today's top picks from the DB, builds an HTML email,
# and sends it via Brevo (ex Sendinblue) free API.
#
# Setup:
#   1. Create free account at https://app.brevo.com
#   2. Go to SMTP & API > API Keys > Create API key
#   3. Set env var: BREVO_API_KEY=your_key
#   4. Set env var: BREVO_SENDER_EMAIL=your@verified-email.com
#   5. pip install sib-api-v3-sdk
#
# Then add this line to bot.py inside core_scheduler_loop()
# right after morning_broadcast():
#
#   import requests as _req
#   _req.post("http://localhost:5000/api/send_digest", timeout=30)
#
# ─────────────────────────────────────────────

@app.route("/api/send_digest", methods=["POST"])
def send_digest():
    """Sends the morning picks digest to all active subscribers via Brevo."""
    import sib_api_v3_sdk
    from sib_api_v3_sdk.rest import ApiException

    brevo_key = os.environ.get("BREVO_API_KEY", "")
    sender_email = os.environ.get("BREVO_SENDER_EMAIL", "")

    if not brevo_key or not sender_email:
        return jsonify({"error": "BREVO_API_KEY or BREVO_SENDER_EMAIL not set"}), 500

    # Fetch today's picks
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticker, report_text, current_price, target_price
        FROM nightly_reports
        WHERE lang = 'en' AND date(date_generated) = (SELECT date(MAX(date_generated)) FROM nightly_reports)
        ORDER BY date_generated DESC LIMIT 5
    """)
    picks_rows = cursor.fetchall()
    conn.close()

    if not picks_rows:
        return jsonify({"ok": True, "message": "No picks to send today."})

    # Build HTML email body
    picks_html = ""
    for row in picks_rows:
        upside = _compute_upside(row["current_price"], row["target_price"]) or "—"
        report_clean = _strip_html(row["report_text"])[:400]
        picks_html += f"""
        <div style="border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin-bottom:12px;">
          <div style="font-family:monospace;font-size:18px;font-weight:600;color:#1a202c">{row['ticker']}</div>
          <div style="font-size:12px;color:#64748b;margin-bottom:8px;">
            Price: ${float(row['current_price'] or 0):.2f} &nbsp;|&nbsp;
            Target: ${float(row['target_price'] or 0):.2f} &nbsp;|&nbsp;
            Upside: <span style="color:#1D9E75;font-weight:600">{upside}</span>
          </div>
          <div style="font-size:13px;color:#334155;line-height:1.6">{report_clean}</div>
        </div>"""

    today_str = datetime.date.today().strftime("%B %d, %Y")
    html_body = f"""
    <html><body style="font-family:'Helvetica Neue',sans-serif;max-width:600px;margin:0 auto;padding:24px;">
      <div style="border-bottom:2px solid #1D9E75;padding-bottom:12px;margin-bottom:24px;">
        <span style="font-size:20px;font-weight:700;color:#0f172a">ValueLens</span>
        <span style="font-size:12px;color:#64748b;margin-left:12px;">Morning Brief · {today_str}</span>
      </div>
      <p style="font-size:13px;color:#64748b;margin-bottom:20px;">
        Your automated equity intelligence report. Top picks from last night's scan:
      </p>
      {picks_html}
      <p style="font-size:11px;color:#94a3b8;margin-top:24px;border-top:1px solid #e2e8f0;padding-top:16px;">
        ⚠ Not financial advice. Informational only. UK/EU disclaimer applies.<br/>
        <a href="__unsubscribe__" style="color:#94a3b8">Unsubscribe</a>
      </p>
    </body></html>"""

    # Fetch subscriber list
    sub_conn = get_sub_db()
    subs = sub_conn.execute(
        "SELECT email FROM subscribers WHERE active = 1"
    ).fetchall()
    sub_conn.close()

    if not subs:
        return jsonify({"ok": True, "message": "No subscribers."})

    # Send via Brevo
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = brevo_key
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )

    sent = 0
    failed = 0
    for row in subs:
        try:
            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": row[0]}],
                sender={"email": sender_email, "name": "ValueLens"},
                subject=f"ValueLens Morning Brief — {today_str}",
                html_content=html_body
            )
            api_instance.send_transac_email(send_smtp_email)
            sent += 1
        except ApiException as e:
            logger.error(f"Failed to send to {row[0]}: {e}")
            failed += 1

    logger.info(f"Digest sent: {sent} OK, {failed} failed.")
    return jsonify({"ok": True, "sent": sent, "failed": failed})


if __name__ == "__main__":
    logger.info("ValueLens Web API starting on port 5000...")
    app.run(host="0.0.0.0", port=5000, debug=False)