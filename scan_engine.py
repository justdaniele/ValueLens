"""
scan_engine.py — On-demand full ticker analysis triggered via Telegram /scan command.

Aggregates all ValueLens intelligence layers into a single concise report:
- AI fundamental brief (Opportunity Score, DCF/Zombie/Short scores)
- Insider buy activity (EDGAR Form 4, P-code only)
- Next earnings date
- 30-day price chart image (PNG, sent as Telegram photo)
"""

import io
import os
import re
import json
import time
import logging
import datetime
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import yfinance as yf

from analyzer import analyze_company, generate_earnings_sentiment_layer

logger = logging.getLogger("ScanEngine")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
COMPANY_TICKERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "company_tickers.json")

EDGAR_HEADERS = {
    "User-Agent": "ValueLens Intelligence Bot contact@valuelens.app",
    "Accept-Encoding": "gzip, deflate",
}


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def _generate_chart(ticker: str):
    """Generates a 30-day closing price chart as PNG bytes.

    Uses a dark theme matching the ValueLens dashboard aesthetic.
    Returns None if matplotlib is unavailable or data fetch fails.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend — no display needed
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import numpy as np

        stock = yf.Ticker(ticker)
        hist  = stock.history(period="30d")

        if hist.empty or "Close" not in hist.columns:
            return None

        prices = hist["Close"]
        dates  = prices.index

        fig, ax = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor("#0A0F1E")
        ax.set_facecolor("#0F1729")

        # Price line and fill
        color   = "#1D9E75" if prices.iloc[-1] >= prices.iloc[0] else "#DC2626"
        ax.plot(dates, prices, color=color, linewidth=2, zorder=3)
        ax.fill_between(dates, prices, prices.min() * 0.995,
                        color=color, alpha=0.12, zorder=2)

        # Style
        ax.tick_params(colors="#64748B", labelsize=9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        plt.setp(ax.get_xticklabels(), rotation=0)

        for spine in ax.spines.values():
            spine.set_color("#162034")

        ax.yaxis.set_tick_params(labelcolor="#64748B")
        ax.yaxis.label.set_color("#64748B")
        ax.grid(True, color="#162034", linewidth=0.8, linestyle="--", zorder=1)

        # Title
        pct_chg = ((prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0]) * 100
        sign    = "+" if pct_chg >= 0 else ""
        ax.set_title(
            f"{ticker}   ${prices.iloc[-1]:.2f}   {sign}{pct_chg:.2f}%  (30d)",
            color="#E2E8F0", fontsize=13, fontweight="bold", pad=12
        )

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf.read()

    except Exception as e:
        logger.warning(f"Chart generation failed for {ticker}: {e}")
        return None


# ---------------------------------------------------------------------------
# Insider activity (EDGAR P-code, fast single-ticker path)
# ---------------------------------------------------------------------------

def _get_cik(ticker: str):
    """Returns zero-padded CIK for a ticker from the local company_tickers.json."""
    try:
        with open(COMPANY_TICKERS_PATH) as f:
            data = json.load(f)
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker.upper():
                return str(entry["cik_str"])  # Raw CIK, no padding — matches EDGAR index format
    except Exception:
        pass
    return None


def _get_recent_insider_buys(ticker: str, days_back: int = 90) -> list:
    """Fetches confirmed open-market purchases (Form 4, code P) from EDGAR.

    Scans the current quarter's index for Form 4 filings, then parses XML.
    Returns up to 3 P-code transactions above $100k, sorted by value desc.
    """
    cik = _get_cik(ticker)
    if not cik:
        return []

    today   = datetime.date.today()
    cutoff  = today - datetime.timedelta(days=days_back)

    # Build list of quarters to cover the lookback window
    quarters_to_check = set()
    d = cutoff
    while d <= today:
        quarters_to_check.add((d.year, (d.month - 1) // 3 + 1))
        d = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)

    import re as _re
    accessions = []

    for year, quarter in sorted(quarters_to_check):
        idx_url = f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"
        try:
            resp = requests.get(idx_url, headers=EDGAR_HEADERS, timeout=20)
            if resp.status_code != 200:
                continue

            data_start = 0
            for i, line in enumerate(resp.text.splitlines()):
                if line.startswith("-----"):
                    data_start = i + 1
                    break

            for line in resp.text.splitlines()[data_start:]:
                parts = _re.split(r'  +', line.strip())
                if len(parts) < 5 or parts[0].strip() != "4":
                    continue
                try:
                    filing_cik  = parts[2].strip()
                    date_filed  = parts[3].strip()
                    filename    = parts[4].strip()
                    if filing_cik != cik:
                        continue
                    if datetime.date.fromisoformat(date_filed) < cutoff:
                        continue
                    acc = filename.split("/")[-1].replace(".txt", "").replace("-", "")
                    accessions.append(acc)
                except Exception:
                    pass
            time.sleep(0.3)
        except Exception:
            continue

    if not accessions:
        return []

    purchases = []
    for acc in accessions[:5]:
        acc_dashed = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"
        index_url  = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{acc_dashed}-index.htm"
        sec_url    = index_url

        try:
            idx_r = requests.get(index_url, headers=EDGAR_HEADERS, timeout=10)
            if idx_r.status_code != 200:
                continue
            import re as _re
            xml_m = _re.search(r'href="(/Archives/edgar/data/[^"]+\.xml)"', idx_r.text)
            if not xml_m:
                continue
            xml_url = "https://www.sec.gov" + xml_m.group(1)
            xml_r   = requests.get(xml_url, headers=EDGAR_HEADERS, timeout=10)
            if xml_r.status_code != 200:
                continue

            root = ET.fromstring(xml_r.content)
            name_el  = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
            title_el = root.find(".//reportingOwner/reportingOwnerRelationship/officerTitle")
            name  = name_el.text.strip().title() if name_el is not None else "Insider"
            title = title_el.text.strip() if title_el is not None and title_el.text else "Officer"

            for tx in root.findall(".//nonDerivativeTransaction"):
                code_el = tx.find(".//transactionCoding/transactionCode")
                if code_el is None or code_el.text != "P":
                    continue
                try:
                    date_el   = tx.find(".//transactionDate/value")
                    shares_el = tx.find(".//transactionAmounts/transactionShares/value")
                    price_el  = tx.find(".//transactionAmounts/transactionPricePerShare/value")
                    shares = float(shares_el.text) if shares_el is not None else 0.0
                    price  = float(price_el.text)  if price_el  is not None else 0.0
                    total  = shares * price
                    if total >= 50_000:  # Lower threshold for manual /scan vs auto alerts ($500k)
                        purchases.append({
                            "name":    name,
                            "title":   title,
                            "shares":  shares,
                            "price":   price,
                            "total":   total,
                            "date":    date_el.text.strip() if date_el is not None else "N/A",
                            "sec_url": sec_url,
                        })
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.2)

    return sorted(purchases, key=lambda x: x["total"], reverse=True)[:3]


# ---------------------------------------------------------------------------
# Earnings date
# ---------------------------------------------------------------------------

def _get_next_earnings(ticker: str) -> str:
    """Returns the next earnings date string or 'N/A'."""
    try:
        stock = yf.Ticker(ticker)
        cal   = stock.calendar
        if cal and isinstance(cal, dict):
            dates = cal.get("Earnings Date")
            if dates:
                d = dates[0] if isinstance(dates, list) else dates
                return str(pd.Timestamp(d).date())
        info = stock.info
        for key in ("earningsTimestamp", "earningsTimestampStart"):
            ts = info.get(key)
            if ts:
                return str(datetime.datetime.utcfromtimestamp(ts).date())
    except Exception:
        pass
    return "N/A"


# ---------------------------------------------------------------------------
# Score extraction
# ---------------------------------------------------------------------------

def _extract_score(report_text: str) -> tuple[int, int, int, int]:
    """Parses Opportunity Score and DCF/Zombie/Short scores from AI report text.

    Returns (opportunity_score, dcf_score, zombie_score, short_score).
    """
    opp, dcf, zombie, short = 50, 0, 0, 0

    m = re.search(r'Opportunity Score[:\s]*(\d+)/100', report_text)
    if m:
        opp = int(m.group(1))

    m2 = re.search(r'SCORES:\s*DCF=([+-]?\d+)\s*\|\s*ZOMBIE=([+-]?\d+)\s*\|\s*SHORT=([+-]?\d+)', report_text)
    if m2:
        dcf, zombie, short = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))

    return opp, dcf, zombie, short


def _extract_verdict(report_text: str) -> str:
    """Extracts the one-sentence Verdict from the AI report."""
    m = re.search(r'Verdict:\s*(.+?)(?:</i>|$)', report_text, re.IGNORECASE | re.DOTALL)
    if m:
        verdict = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return verdict[:200]
    return ""


# ---------------------------------------------------------------------------
# Main scan function
# ---------------------------------------------------------------------------

def run_full_scan(ticker: str, admin_chat_id: int) -> None:
    """Executes a full on-demand scan for a ticker and sends results to the admin chat.

    Sends a photo (30-day chart) with a comprehensive caption covering:
    - Current price, analyst target, upside
    - AI Opportunity Score and individual scores
    - AI Verdict (one sentence)
    - Insider buy activity (EDGAR P-code)
    - Next earnings date
    - EES (Earnings Expectation Score) if applicable
    """
    ticker = ticker.upper().strip()
    logger.info(f"Running full scan for {ticker}...")

    send_url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    photo_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    # --- Notify start ---
    requests.post(send_url, json={
        "chat_id": admin_chat_id,
        "text": f"🔍 Scanning <b>{ticker}</b>...",
        "parse_mode": "HTML"
    }, timeout=10)

    try:
        # 1. Fetch stock data
        stock = yf.Ticker(ticker)
        info  = stock.info
        if not info.get("shortName"):
            requests.post(send_url, json={
                "chat_id": admin_chat_id,
                "text": f"❌ Ticker <b>{ticker}</b> not found.",
                "parse_mode": "HTML"
            }, timeout=10)
            return

        company_name = info.get("shortName", ticker)
        curr_price   = stock.fast_info.last_price or info.get("regularMarketPrice", 0)
        target_price = info.get("targetMeanPrice")
        pe_ratio     = info.get("trailingPE")
        short_float  = info.get("shortPercentOfFloat")

        upside_str = ""
        if target_price and curr_price and curr_price > 0:
            upside = ((target_price - curr_price) / curr_price) * 100
            sign   = "+" if upside >= 0 else ""
            upside_str = f" → <b>{sign}{upside:.1f}%</b> upside"

        # 2. AI fundamental analysis
        report = analyze_company(ticker, mode="PRO", lang="en", company_info=info)
        opp, dcf, zombie, short_score = _extract_score(report)
        verdict = _extract_verdict(report)

        # Score bar emoji
        def score_bar(s: int) -> str:
            if s >= 7:   return "🟢🟢🟢"
            elif s >= 3: return "🟢🟢⬜"
            elif s >= 0: return "🟢⬜⬜"
            elif s >= -3: return "🔴⬜⬜"
            elif s >= -7: return "🔴🔴⬜"
            else:         return "🔴🔴🔴"

        opp_emoji = "💎" if opp >= 70 else "🟡" if opp >= 50 else "🔴"

        # 3. Insider buys
        insider_lines = []
        insiders = _get_recent_insider_buys(ticker, days_back=90)
        if insiders:
            for p in insiders[:2]:
                insider_lines.append(
                    f"  • <b>{p['name']}</b> ({p['title']})\n"
                    f"    {int(p['shares']):,} shares @ ${p['price']:.2f} = <b>${p['total']:,.0f}</b> <i>({p['date']})</i>"
                )
        insider_section = "\n".join(insider_lines) if insider_lines else "  No confirmed P-code purchases in last 90 days."

        # 4. Earnings
        earnings_date = _get_next_earnings(ticker)

        # 5. EES score
        try:
            ees = generate_earnings_sentiment_layer(ticker, company_name)
            ees_str = f"{'+' if ees >= 0 else ''}{ees}/70"
            ees_label = "🟢 Bullish" if ees >= 30 else "🔴 Bearish" if ees <= -30 else "⬜ Neutral"
        except Exception:
            ees_str, ees_label = "N/A", ""

        # 6. Build caption
        caption = (
            f"🔍 <b>ValueLens Full Scan: {ticker}</b>\n"
            f"<i>{company_name}</i>\n\n"
            f"💰 <b>Price:</b> <code>${curr_price:.2f}</code>"
            + (f" → Target: <code>${target_price:.2f}</code>{upside_str}" if target_price else "")
            + (f"\n📊 P/E: <code>{pe_ratio:.1f}x</code>" if pe_ratio else "")
            + (f"  |  Short: <code>{short_float*100:.1f}%</code>" if short_float else "")
            + f"\n\n{opp_emoji} <b>Opportunity Score: {opp}/100</b>\n"
            f"  DCF {score_bar(dcf)} Zombie {score_bar(zombie)} Short {score_bar(short_score)}\n\n"
            + (f"💬 <i>{verdict}</i>\n\n" if verdict else "")
            + f"👔 <b>Insider Activity (90d):</b>\n{insider_section}\n\n"
            f"📅 <b>Next Earnings:</b> <code>{earnings_date}</code>\n"
            + (f"🎯 <b>EES Score:</b> <code>{ees_str}</code>  {ees_label}" if ees_str != "N/A" else "")
        )

        # Trim to Telegram's 1024 char caption limit
        if len(caption) > 1020:
            caption = caption[:1017] + "..."

        # 7. Generate chart and send
        chart_bytes = _generate_chart(ticker)

        if chart_bytes:
            requests.post(photo_url, files={"photo": (f"{ticker}.png", chart_bytes, "image/png")},
                         data={"chat_id": admin_chat_id, "caption": caption, "parse_mode": "HTML"},
                         timeout=30)
        else:
            # Fallback: send as text if chart fails
            requests.post(send_url, json={
                "chat_id": admin_chat_id,
                "text": caption,
                "parse_mode": "HTML"
            }, timeout=10)

        logger.info(f"Full scan complete for {ticker}. Score: {opp}/100")

    except Exception as e:
        logger.error(f"Full scan failed for {ticker}: {e}")
        requests.post(send_url, json={
            "chat_id": admin_chat_id,
            "text": f"❌ Scan failed for <b>{ticker}</b>: {e}",
            "parse_mode": "HTML"
        }, timeout=10)