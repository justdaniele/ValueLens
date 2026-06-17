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
        # Fetch 50d so MA20 and RSI(14) have enough warmup history to be
        # fully populated across the visible 30-day window — otherwise the
        # first ~20 days of MA20 are NaN and the line only appears halfway
        # through the chart.
        hist  = stock.history(period="50d")

        if hist.empty or "Close" not in hist.columns:
            return None

        # Compute RSI(14) and MA20 on the full 50-day series, then slice
        # down to the last 30 days for display once both are warmed up.
        full_prices = hist["Close"]

        def _rsi(series, period=14):
            delta = series.diff()
            gain  = delta.clip(lower=0).rolling(period).mean()
            loss  = (-delta.clip(upper=0)).rolling(period).mean()
            rs    = gain / loss.replace(0, float("inf"))
            return 100 - (100 / (1 + rs))

        full_rsi  = _rsi(full_prices)
        full_ma20 = full_prices.rolling(20).mean()

        hist30  = hist.tail(30)
        dates   = hist30.index
        prices  = hist30["Close"]
        rsi_values = full_rsi.reindex(dates)
        ma20       = full_ma20.reindex(dates)

        # Two-panel layout: price (top) + RSI (bottom)
        fig, (ax, ax_rsi) = plt.subplots(
            2, 1, figsize=(10, 5.5),
            gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08}
        )
        fig.patch.set_facecolor("#0A0F1E")
        for a in (ax, ax_rsi):
            a.set_facecolor("#0F1729")
            for spine in a.spines.values():
                spine.set_color("#162034")
            a.tick_params(colors="#64748B", labelsize=8)
            a.grid(True, color="#162034", linewidth=0.7, linestyle="--", zorder=1)

        # Price line + fill
        color = "#1D9E75" if prices.iloc[-1] >= prices.iloc[0] else "#DC2626"
        ax.plot(dates, prices, color=color, linewidth=2, zorder=3)
        ax.fill_between(dates, prices, prices.min() * 0.995,
                        color=color, alpha=0.12, zorder=2)

        # 20-day MA overlay — now fully populated across the visible window
        ax.plot(dates, ma20, color="#3B82F6", linewidth=1.2,
                linestyle="--", alpha=0.75, label="MA20", zorder=3)
        ax.legend(loc="upper left", fontsize=8,
                  facecolor="#0F1729", edgecolor="#162034", labelcolor="#64748B")

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        ax.set_xticklabels([])  # hide x labels on top panel

        # RSI panel
        ax_rsi.plot(dates, rsi_values, color="#D97706", linewidth=1.4, zorder=3)
        ax_rsi.axhline(70, color="#DC2626", linewidth=0.8, linestyle="--", alpha=0.6)
        ax_rsi.axhline(30, color="#1D9E75", linewidth=0.8, linestyle="--", alpha=0.6)
        ax_rsi.fill_between(dates, rsi_values, 70,
                            where=(rsi_values >= 70), color="#DC2626", alpha=0.15)
        ax_rsi.fill_between(dates, rsi_values, 30,
                            where=(rsi_values <= 30), color="#1D9E75", alpha=0.15)
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_ylabel("RSI", color="#64748B", fontsize=8)
        ax_rsi.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax_rsi.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        plt.setp(ax_rsi.get_xticklabels(), rotation=0)

        # Title on top panel
        pct_chg = ((prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0]) * 100
        rsi_now = rsi_values.dropna().iloc[-1] if not rsi_values.dropna().empty else 0
        sign    = "+" if pct_chg >= 0 else ""
        ax.set_title(
            f"{ticker}   ${prices.iloc[-1]:.2f}   {sign}{pct_chg:.2f}%  (30d)   RSI {rsi_now:.0f}",
            color="#E2E8F0", fontsize=12, fontweight="bold", pad=10
        )

        fig.tight_layout()
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

    Uses the quarterly full-index (same approach as insider_engine) to find ALL
    Form 4 filings for a company CIK — including those filed by third-party agents
    which would be missed by the submissions API.
    """
    cik = _get_cik(ticker)
    if not cik:
        return []

    today  = datetime.date.today()
    cutoff = today - datetime.timedelta(days=days_back)

    # Build quarters to cover lookback window
    quarters = set()
    d = cutoff
    while d <= today:
        quarters.add((d.year, (d.month - 1) // 3 + 1))
        d = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)

    import re as _re
    accessions = []

    _CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".edgar_index_cache.json")

    for year, quarter in sorted(quarters):
        cache_key = f"{year}_QTR{quarter}"
        index_lines = []

        # Try disk cache first (shared with insider_engine)
        try:
            with open(_CACHE_PATH) as _f:
                _cache = _json.load(_f)
            entry = _cache.get(cache_key, {})
            cached_at = datetime.datetime.fromisoformat(entry.get("cached_at", "2000-01-01"))
            if (datetime.datetime.now() - cached_at).total_seconds() / 3600 < 23:
                index_lines = [tuple(x) for x in entry.get("data", [])]
        except Exception:
            pass

        # Fetch from EDGAR if cache miss
        if not index_lines:
            idx_url = f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"
            try:
                resp = requests.get(idx_url, headers=EDGAR_HEADERS, timeout=20)
                if resp.status_code == 200:
                    data_start = 0
                    for i, line in enumerate(resp.text.splitlines()):
                        if line.startswith("-----"):
                            data_start = i + 1
                            break
                    for line in resp.text.splitlines()[data_start:]:
                        parts = _re.split(r"  +", line.strip())
                        if len(parts) >= 5 and parts[0].strip() == "4":
                            try:
                                index_lines.append((
                                    parts[2].strip().zfill(10),
                                    parts[4].strip().split("/")[-1].replace(".txt","").replace("-",""),
                                    parts[3].strip()
                                ))
                            except Exception:
                                pass
            except Exception:
                pass
            time.sleep(0.3)

        # Filter to our CIK
        for filing_cik, acc, date_filed in index_lines:
            if filing_cik.lstrip("0") != cik.lstrip("0"):
                continue
            try:
                if datetime.date.fromisoformat(date_filed) < cutoff:
                    continue
                accessions.append((acc, filing_cik))
            except Exception:
                pass

    if not accessions:
        return []

    # Parse each Form 4 XML for P-code transactions
    purchases = []
    for acc, filing_cik in accessions[:20]:
        acc_dashed = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"
        # Use the company CIK for the archive path (not the filer CIK)
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{acc_dashed}-index.htm"
        sec_url   = index_url

        try:
            idx_r = requests.get(index_url, headers=EDGAR_HEADERS, timeout=10)
            if idx_r.status_code != 200:
                continue

            xml_matches = _re.findall(r'href="(/Archives/edgar/data/[^"]+\.xml)"', idx_r.text)
            # Prefer URL without xsl subfolder
            xml_url = None
            for m in xml_matches:
                if "xsl" not in m.lower():
                    xml_url = "https://www.sec.gov" + m
                    break
            if not xml_url and xml_matches:
                # Strip xsl subfolder manually
                raw   = xml_matches[0]
                parts = [p for p in raw.split("/") if not p.startswith("xsl")]
                xml_url = "https://www.sec.gov" + "/".join(parts)
            if not xml_url:
                continue

            xml_r = requests.get(xml_url, headers=EDGAR_HEADERS, timeout=10)
            if xml_r.status_code != 200:
                continue

            try:
                root = ET.fromstring(xml_r.content)
            except ET.ParseError:
                continue

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
                    if total >= 50_000:
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

        except Exception as e:
            logger.debug(f"XML parse failed for {acc}: {e}")
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