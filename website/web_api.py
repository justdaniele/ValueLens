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
        WHERE date(date_generated) >= date('now', '-1 day')
    """)
    tickers_scanned = cursor.fetchone()[0] or 0

    # Top picks = English reports from last night, ordered by target upside
    cursor.execute("""
        SELECT COUNT(*) FROM nightly_reports
        WHERE lang = 'en' AND date(date_generated) >= date('now', '-1 day')
    """)
    top_picks = cursor.fetchone()[0] or 0

    # Golden combos = tickers in both nightly_reports and insider_signals (last 24h)
    cursor.execute("""
        SELECT COUNT(DISTINCT nr.ticker)
        FROM nightly_reports nr
        JOIN insider_signals ins ON nr.ticker = ins.ticker
        WHERE date(nr.date_generated) >= date('now', '-1 day')
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
    """
    Returns the top picks from the most recent nightly scan.
    Fetches both EN and IT reports and merges them per ticker.
    Score is approximated from target vs current price upside.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT ticker, report_text, lang, current_price, target_price, date_generated
        FROM nightly_reports
        WHERE date(date_generated) >= date('now', '-1 day')
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
                "signals": []
            }
        if r["lang"] == "en":
            by_ticker[t]["report_en"] = r["report_text"]
            by_ticker[t]["price"] = r["current_price"]
            by_ticker[t]["target"] = r["target_price"]
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
            "ticker": ticker,
            "name": d.get("name") or ticker,
            "price": d["price"],
            "target": d["target"],
            "upside": upside,
            "score": score,
            "report_en": d["report_en"],
            "report_it": d["report_it"],
            "signals": signals,
            "sections": sections,
            "dcf_score":    sec_scores["dcf_score"],
            "zombie_score": sec_scores["zombie_score"],
            "short_score":  sec_scores["short_score"],
        })

    # Sort by score descending, limit to top 10
    result.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(result[:10])


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
    """Fetches 30 days of daily closing prices from yfinance for a given ticker."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="30d")
        if hist.empty:
            return jsonify({"error": "No data"}), 404
        labels = [str(d.date()) for d in hist.index]
        prices = [round(float(p), 2) for p in hist["Close"]]
        return jsonify({"labels": labels, "prices": prices})
    except Exception as e:
        logger.error(f"Price history failed for {ticker}: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# /api/live_prices — current prices for insider % change column
# ─────────────────────────────────────────────

@app.route("/api/live_prices")
def live_prices():
    """
    Returns the latest price for a comma-separated list of tickers.
    Called by the frontend only during NYSE market hours (09:30–16:00 ET).
    Uses yfinance fast_info to minimise API load — one call per ticker.

    Example: /api/live_prices?tickers=AAPL,MSFT,NVDA
    Returns: { "AAPL": 213.40, "MSFT": 441.20, "NVDA": 128.50 }
    """
    tickers_param = request.args.get("tickers", "")
    if not tickers_param:
        return jsonify({}), 400

    tickers = [t.strip().upper() for t in tickers_param.split(",") if t.strip()]
    # Hard limit — never fetch more than 20 at once to protect the Pi
    tickers = tickers[:20]

    result = {}
    for ticker in tickers:
        try:
            price = yf.Ticker(ticker).fast_info.last_price
            if price:
                result[ticker] = round(float(price), 2)
        except Exception as e:
            logger.debug(f"live_prices: could not fetch {ticker}: {e}")

    return jsonify(result)


# ─────────────────────────────────────────────
# /api/insiders — insider buy signals
# ─────────────────────────────────────────────

@app.route("/api/insiders")
def insiders():
    """Returns all active insider buy signals from the database."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticker, date_detected, price_detected, status
        FROM insider_signals
        WHERE status = 'ACTIVE'
        ORDER BY date_detected DESC
        LIMIT 25
    """)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        result.append({
            "ticker": r["ticker"],
            "date_detected": r["date_detected"],
            "price_detected": r["price_detected"],
            "status": r["status"],
            "value": None  # Value not stored in current schema; can be enriched later
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

        result.append({
            "ticker": r["ticker"],
            "name": r["ticker"],
            "price": r["current_price"],
            "target": r["target_price"],
            "score": score,
            "insider_value": "See Telegram",
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
        WHERE lang = 'en' AND date(date_generated) >= date('now', '-1 day')
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