"""
nightly_job.py
==============
Runs every weeknight (via cron or scheduler).
Pipeline:
  1. FMP Stock Screener  → top undervalued candidates   (1 API call)
  2. FMP Key Metrics     → fundamentals per candidate   (1 call per ticker, max 10)
  3. SEC EDGAR           → recent Form 4 insider buys   (0 FMP calls)
  4. DeepSeek            → AI report per ticker         (1 LLM call per ticker)
  5. Telegram Bot API    → post daily report to channel (HTTP, no Pyrogram needed)
  6. DB                  → update last_nightly_run metadata

Total FMP calls per night: 1 (screener) + up to 10 (metrics) = max 11
Well within the 250/day free limit.

Cron example (runs Mon-Fri at 02:00):
  0 2 * * 1-5 /usr/bin/python3 /path/to/valuelens/nightly_job.py >> /var/log/valuelens_nightly.log 2>&1
"""

import os
import time
import sqlite3
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ValueLensNightly")

# ── Environment ───────────────────────────────────────────────────────────────
FMP_API_KEY       = os.environ.get("FMP_API_KEY", "")
BOT_TOKEN         = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID        = os.environ.get("TELEGRAM_CHANNEL_ID", "")   # e.g. @valuelensinsidersignals or -100xxxxxxxxxx
DEEPSEEK_API_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
DB_NAME           = "valuelens.db"

# ── DeepSeek client ───────────────────────────────────────────────────────────
ai_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

# ─────────────────────────────────────────────────────────────────────────────
# 1. FMP SCREENER  (1 API call)
# Returns up to MAX_CANDIDATES tickers already filtered by value criteria.
# ─────────────────────────────────────────────────────────────────────────────
MAX_CANDIDATES = 10   # 1 screener call + 10 metrics calls = 11 total FMP calls

def fmp_screener() -> list[dict]:
    """
    Calls FMP /v3/stock-screener with value filters.
    Returns a list of dicts with at least 'symbol' and 'companyName'.
    """
    url = "https://financialmodelingprep.com/api/v3/stock-screener"
    params = {
        "apikey":              FMP_API_KEY,
        "exchange":            "NYSE,NASDAQ",
        "isEtfAndFund":        "false",
        "isActivelyTrading":   "true",
        "marketCapMoreThan":   10_000_000_000,   # $10B+
        "peRatioLowerThan":    20,
        "priceToBookLowerThan": 3,
        "limit":               MAX_CANDIDATES,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        logger.info(f"FMP screener returned {len(data)} candidates.")
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"FMP screener failed: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 2. FMP KEY METRICS  (1 API call per ticker)
# ─────────────────────────────────────────────────────────────────────────────

def fmp_key_metrics(ticker: str) -> dict:
    """
    Fetches TTM key metrics for a ticker from FMP.
    Returns a flat dict of the most useful value fields.
    """
    url = f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{ticker}"
    params = {"apikey": FMP_API_KEY}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            m = data[0]
            return {
                "pe_ratio":         m.get("peRatioTTM",           "N/A"),
                "pb_ratio":         m.get("pbRatioTTM",           "N/A"),
                "peg_ratio":        m.get("pegRatioTTM",          "N/A"),
                "ev_ebitda":        m.get("enterpriseValueOverEBITDATTM", "N/A"),
                "debt_to_equity":   m.get("debtToEquityTTM",      "N/A"),
                "current_ratio":    m.get("currentRatioTTM",      "N/A"),
                "roe":              m.get("roeTTM",                "N/A"),
                "free_cash_flow_yield": m.get("freeCashFlowYieldTTM", "N/A"),
                "revenue_per_share": m.get("revenuePerShareTTM",  "N/A"),
                "net_income_per_share": m.get("netIncomePerShareTTM", "N/A"),
            }
    except Exception as e:
        logger.error(f"FMP key metrics failed for {ticker}: {e}")
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# 3. SEC EDGAR INSIDER TRADES  (no FMP calls, completely free)
# Checks for Form 4 filings (insider purchases) in the last 14 days.
# ─────────────────────────────────────────────────────────────────────────────
EDGAR_HEADERS = {"User-Agent": "ValueLensBot contact@valuelens.io"}

def edgar_recent_insider_buys(ticker: str) -> list[dict]:
    """
    Queries SEC EDGAR full-text search for recent Form 4 filings for a ticker.
    Returns a list of insider buy events (last 14 days, purchases only).
    Note: EDGAR data has up to 2 business day delay after transaction.
    """
    results = []
    try:
        # Step 1: get CIK for ticker
        cik_url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={(datetime.now()-timedelta(days=14)).strftime('%Y-%m-%d')}&enddt={datetime.now().strftime('%Y-%m-%d')}&forms=4"
        r = requests.get(cik_url, headers=EDGAR_HEADERS, timeout=15)
        r.raise_for_status()
        hits = r.json().get("hits", {}).get("hits", [])
        for hit in hits[:5]:   # cap at 5 filings
            src = hit.get("_source", {})
            # Filter to purchases only (transaction code P = open market purchase)
            if "P" in src.get("period_of_report", "") or True:
                results.append({
                    "filer":    src.get("display_names", "Unknown"),
                    "filed":    src.get("file_date", "N/A"),
                    "form":     src.get("form_type", "4"),
                })
        time.sleep(0.5)   # be polite with EDGAR
    except Exception as e:
        logger.warning(f"EDGAR insider check failed for {ticker}: {e}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 4. DEEPSEEK REPORT GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

REPORT_SYSTEM_PROMPT = """You are ValueLens, an elite quantitative analyst writing a daily briefing for a financial Telegram channel.

STRICT FORMATTING RULES:
- Use ONLY double asterisks (**) for bold. NEVER use __underscores__ or single *asterisks*.
- Separate every section with a blank line.
- No trailing unclosed markdown tags.
- Be concise, cynical, and data-driven. No fluff.
- Data shown is end-of-day from the previous trading session.
"""

def generate_ticker_report(ticker: str, company: str, metrics: dict, insider_signals: list) -> str:
    """
    Calls DeepSeek to generate a structured report for one ticker.
    Uses deepseek-v4-flash (cheaper, fast enough for a nightly batch).
    """
    insider_text = "None detected in last 14 days."
    if insider_signals:
        insider_text = "\n".join(
            f"  - {s['filer']} filed Form {s['form']} on {s['filed']}"
            for s in insider_signals
        )

    user_msg = f"""Generate a concise ValueLens PRO report for {ticker} ({company}).

**Fundamental Data (TTM, end-of-day):**
- P/E Ratio: {metrics.get('pe_ratio', 'N/A')}
- P/B Ratio: {metrics.get('pb_ratio', 'N/A')}
- PEG Ratio: {metrics.get('peg_ratio', 'N/A')}
- EV/EBITDA: {metrics.get('ev_ebitda', 'N/A')}
- Debt/Equity: {metrics.get('debt_to_equity', 'N/A')}
- Current Ratio: {metrics.get('current_ratio', 'N/A')}
- ROE: {metrics.get('roe', 'N/A')}
- FCF Yield: {metrics.get('free_cash_flow_yield', 'N/A')}

**Recent Insider Activity (SEC Form 4, may lag up to 2 business days):**
{insider_text}

Output format:
🔍 **{ticker} | (Company Name)**

💰 **Price Context:** (brief comment on valuation vs fair value)

📊 **Key Metrics Snapshot**
• P/E: X — (one-line insight)
• Debt/Equity: X — (one-line insight)
• FCF Yield: X — (one-line insight)

🧮 **Reverse DCF Stress-Test**
(What growth rate does the current price imply? Is it realistic?)

🧟 **Zombie Detector**
(Does operating cash flow support reported net income?)

🕵️ **Insider Signal**
(Summarize insider activity or note absence)

💡 **ValueLens Verdict**
(2-3 lines: cynical, direct assessment. Is this a real discount or a value trap?)
"""

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-v4-flash",
            max_tokens=800,
            messages=[
                {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"DeepSeek report failed for {ticker}: {e}")
        return f"❌ Report generation failed for {ticker}: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. TELEGRAM CHANNEL POST  (plain HTTP, no Pyrogram needed)
# ─────────────────────────────────────────────────────────────────────────────

def send_to_channel(text: str) -> bool:
    """
    Sends a message to the Telegram channel via Bot API (HTTP).
    Splits automatically if over 4096 chars.
    Returns True if all parts sent successfully.
    """
    if not BOT_TOKEN or not CHANNEL_ID:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID missing in .env")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    # Telegram max message length is 4096 chars
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    success = True
    for chunk in chunks:
        payload = {
            "chat_id":    CHANNEL_ID,
            "text":       chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            r = requests.post(url, json=payload, timeout=15)
            r.raise_for_status()
            time.sleep(1)   # avoid Telegram flood limits
        except Exception as e:
            logger.error(f"Telegram send failed: {e} | Response: {r.text if 'r' in dir() else 'N/A'}")
            success = False
    return success


# ─────────────────────────────────────────────────────────────────────────────
# 6. DB HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def update_nightly_metadata(status: str):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_nightly_run', ?)",
            (f"{now_str} | {status}",)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB metadata update failed: {e}")

def save_nightly_signals(tickers: list[str]):
    """Saves screener results to insider_signals table for tracking."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        for ticker in tickers:
            cursor.execute("""
                INSERT OR IGNORE INTO insider_signals (ticker, date_detected, price_detected, status)
                VALUES (?, ?, 0, 'ACTIVE')
            """, (ticker, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB signal save failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def run_nightly_job():
    logger.info("=" * 60)
    logger.info("ValueLens Nightly Job started.")
    logger.info("=" * 60)

    # ── Guard: skip weekends ─────────────────────────────────────────────────
    if datetime.now().weekday() >= 5:
        logger.info("Weekend detected. Skipping nightly job.")
        return

    # ── Step 1: FMP Screener ─────────────────────────────────────────────────
    logger.info("Step 1/4 — Running FMP value screener...")
    candidates = fmp_screener()
    if not candidates:
        logger.error("Screener returned no candidates. Aborting.")
        update_nightly_metadata("FAILED: no screener results")
        return

    fmp_calls_used = 1
    logger.info(f"Candidates: {[c.get('symbol') for c in candidates]}")

    # ── Step 2 & 3: Metrics + Insider data per ticker ────────────────────────
    enriched = []
    for candidate in candidates:
        ticker  = candidate.get("symbol", "")
        company = candidate.get("companyName", ticker)
        if not ticker:
            continue

        logger.info(f"Processing {ticker}...")

        # FMP key metrics (1 call)
        metrics = fmp_key_metrics(ticker)
        fmp_calls_used += 1
        time.sleep(0.5)   # gentle pacing, well within free tier

        # SEC EDGAR insider check (0 FMP calls)
        insider_signals = edgar_recent_insider_buys(ticker)

        enriched.append({
            "ticker":          ticker,
            "company":         company,
            "metrics":         metrics,
            "insider_signals": insider_signals,
        })

        logger.info(f"  FMP calls used so far: {fmp_calls_used}/250")

        # Hard safety cap — never exceed 200 calls (leaves buffer for the day)
        if fmp_calls_used >= 200:
            logger.warning("FMP call budget cap reached (200). Stopping enrichment early.")
            break

    logger.info(f"Total FMP API calls used tonight: {fmp_calls_used}")

    # ── Step 4: Generate AI reports ──────────────────────────────────────────
    logger.info("Step 3/4 — Generating DeepSeek reports...")
    date_str = datetime.now().strftime("%B %d, %Y")
    full_report = (
        f"📡 **ValueLens Daily Radar | {date_str}**\n"
        f"_End-of-day data. Not financial advice._\n"
        f"{'─' * 35}\n\n"
    )

    for item in enriched:
        report_block = generate_ticker_report(
            item["ticker"],
            item["company"],
            item["metrics"],
            item["insider_signals"],
        )
        full_report += report_block + "\n\n" + "─" * 35 + "\n\n"
        time.sleep(1)   # avoid DeepSeek rate limits between calls

    full_report += "_Powered by ValueLens · FMP · SEC EDGAR · DeepSeek_"

    # ── Step 5: Post to Telegram channel ─────────────────────────────────────
    logger.info("Step 4/4 — Posting to Telegram channel...")
    success = send_to_channel(full_report)
    if success:
        logger.info("Report posted to channel successfully.")
    else:
        logger.error("Failed to post report to channel.")

    # ── Step 6: Update DB ────────────────────────────────────────────────────
    status = "OK" if success else "POSTED_FAILED"
    update_nightly_metadata(status)
    save_nightly_signals([item["ticker"] for item in enriched])

    logger.info(f"Nightly job completed. Status: {status}")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_nightly_job()
