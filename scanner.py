import os
import time
import logging
import datetime
import requests
import sqlite3
import html
import pandas as pd
import yfinance as yf

# HEADLESS MATPLOTLIB CONFIGURATION FOR SERVER DEPLOYMENT
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from dotenv import load_dotenv
from analyzer import analyze_company
from database import DB_NAME, init_db, save_report_to_db

load_dotenv()

logger = logging.getLogger("ValueLensScanner")

BOT_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID_IT = os.environ.get("TELEGRAM_CHANNEL_ID_IT", "")
CHANNEL_ID_EN = os.environ.get("TELEGRAM_CHANNEL_ID_EN", "")

# Which universes to scan — change via .env: SCAN_UNIVERSE=sp500,nasdaq100
SCAN_UNIVERSE = os.environ.get("SCAN_UNIVERSE", "sp500,nasdaq100").lower()


# ---------------------------------------------------------------------------
# Shared HTML sanitiser
# ---------------------------------------------------------------------------

def _sanitise_html(text: str) -> str:
    """Escapes raw text then restores the HTML tags ValueLens intentionally uses."""
    safe = html.escape(text, quote=False)
    for tag in ("b", "i", "code", "pre"):
        safe = safe.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    return safe


# ---------------------------------------------------------------------------
# Universe helpers
# ---------------------------------------------------------------------------

def get_sp500_tickers() -> list:
    """Retrieves S&P 500 tickers from local cache, refreshing from Wikipedia every 7 days."""
    return _get_tickers_cached(
        cache_file="sp500_tickers.txt",
        url="https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        symbol_col="Symbol",
        label="S&P 500"
    )


def get_nasdaq100_tickers() -> list:
    """Retrieves NASDAQ-100 tickers from local cache, refreshing from Wikipedia every 7 days."""
    return _get_tickers_cached(
        cache_file="nasdaq100_tickers.txt",
        url="https://en.wikipedia.org/wiki/Nasdaq-100",
        symbol_col="Ticker",
        label="NASDAQ-100"
    )


def _get_tickers_cached(cache_file: str, url: str, symbol_col: str, label: str) -> list:
    """Generic cached ticker fetcher shared by S&P 500 and NASDAQ-100."""
    cache_expiry_days = 7

    if os.path.exists(cache_file):
        file_time = datetime.datetime.fromtimestamp(os.path.getmtime(cache_file))
        if datetime.datetime.now() - file_time < datetime.timedelta(days=cache_expiry_days):
            logger.info(f"Loading {label} universe from local cache.")
            with open(cache_file, "r") as f:
                return [line.strip() for line in f if line.strip()]

    logger.info(f"Cache missing or expired. Syncing {label} roster from Wikipedia...")
    try:
        headers  = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        tables  = pd.read_html(response.text)
        tickers = None

        for table in tables:
            if symbol_col in table.columns:
                tickers = [t.replace('.', '-') for t in table[symbol_col].dropna().tolist()]
                break

        if not tickers:
            raise ValueError(f"Column '{symbol_col}' not found in any Wikipedia table.")

        with open(cache_file, "w") as f:
            for t in tickers:
                f.write(f"{t}\n")

        logger.info(f"Cached {len(tickers)} {label} tickers.")
        return tickers

    except Exception as e:
        logger.error(f"Error downloading {label} list: {e}")
        if os.path.exists(cache_file):
            logger.warning(f"Returning expired {label} cache as fallback.")
            with open(cache_file, "r") as f:
                return [line.strip() for line in f if line.strip()]
        return []


def get_us_market_universe() -> list:
    """
    Returns a single deduplicated list of tickers from all configured universes.
    S&P 500 first, then NASDAQ-100 exclusives appended at the end.
    The screening pipeline is completely index-agnostic — it just sees one list.
    Controlled by SCAN_UNIVERSE env var (default: sp500,nasdaq100).
    """
    seen   = set()
    merged = []

    if "sp500" in SCAN_UNIVERSE:
        for t in get_sp500_tickers():
            if t not in seen:
                seen.add(t)
                merged.append(t)

    if "nasdaq100" in SCAN_UNIVERSE:
        nasdaq_only = 0
        for t in get_nasdaq100_tickers():
            if t not in seen:
                seen.add(t)
                merged.append(t)
                nasdaq_only += 1
        logger.info(f"NASDAQ-100 contributed {nasdaq_only} exclusive tickers.")

    logger.info(f"Combined universe: {len(merged)} unique tickers (config: '{SCAN_UNIVERSE}')")
    return merged


# ---------------------------------------------------------------------------
# Screening pipeline
# ---------------------------------------------------------------------------

def filter_value_universe(tickers: list, max_candidates=150, sleep_seconds=0.05) -> list:
    """
    First pass: cheap fast_info scan across the full universe.
    Sorts by deepest 52-week discount. Index-agnostic.
    """
    candidates = []
    for i, ticker in enumerate(tickers):
        if i % 100 == 0 and i > 0:
            logger.info(f"Filter progress: {i}/{len(tickers)}...")
        try:
            f_info  = yf.Ticker(ticker).fast_info
            high    = getattr(f_info, 'year_high', None) or getattr(f_info, 'yearHigh', None)
            current = getattr(f_info, 'last_price', None) or getattr(f_info, 'lastPrice', None)

            if high and current and high > 0:
                discount = (high - current) / high
                candidates.append({"ticker": ticker, "discount": discount})
        except Exception:
            pass
        time.sleep(sleep_seconds)

    candidates.sort(key=lambda x: x['discount'], reverse=True)
    top_tickers = [c['ticker'] for c in candidates[:max_candidates]]
    logger.info(f"Phase 1: {len(top_tickers)} candidates by 52w discount.")
    return top_tickers


def fast_value_screen(tickers_list: list, max_candidates=20) -> list:
    """Second pass: narrows to the top N from the discount-sorted list."""
    top = tickers_list[:max_candidates]
    logger.info(f"Phase 2 fast-screen: {top}")
    return top


def deep_value_screen(tickers_list: list, max_candidates=15,
                      sleep_seconds=15, pe_threshold=25) -> list:
    """
    Third pass: full .info fetch validating P/E ratio and analyst upside.
    pe_threshold overridable via PE_THRESHOLD env var.
    Returns list of dicts carrying the fetched info so callers don't re-fetch.
    """
    pe_threshold = int(os.environ.get("PE_THRESHOLD", pe_threshold))
    candidates   = []

    for ticker in tickers_list:
        try:
            logger.info(f"Deep scan: {ticker}...")
            info = yf.Ticker(ticker).info

            current     = info.get("currentPrice") or info.get("regularMarketPrice")
            target_mean = info.get("targetMeanPrice")
            pe          = info.get("trailingPE") or info.get("forwardPE")

            if pe is not None and pe > pe_threshold:
                logger.info(f"Rejected {ticker}: P/E {pe:.1f} > {pe_threshold}.")
                continue

            if current and target_mean and current > 0:
                upside = (target_mean - current) / current
                candidates.append({"ticker": ticker, "upside": upside, "info": info})

        except Exception as e:
            logger.warning(f"Deep scan skipped {ticker}: {e}")
        time.sleep(sleep_seconds)

    candidates.sort(key=lambda x: x['upside'], reverse=True)
    top = candidates[:max_candidates]
    logger.info(f"Phase 3 winners: {[c['ticker'] for c in top]}")
    return top


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def generate_target_chart(ticker: str, current_price: float, target_price: float):
    """Generates a dark-themed 1-year price chart with analyst target overlay."""
    try:
        hist = yf.Ticker(ticker).history(period="1y")
        if hist.empty:
            return None

        plt.figure(figsize=(8, 4))
        plt.style.use('dark_background')
        plt.plot(hist.index, hist['Close'], color='cyan', linewidth=1.5, label='Price Action')

        if target_price:
            plt.axhline(
                y=target_price, color='lime', linestyle='--', linewidth=2,
                label=f'Analyst Target: ${target_price:.2f}'
            )

        plt.scatter(hist.index[-1], current_price, color='gold', s=100, zorder=5, label='Current Price')
        plt.title(f"{ticker} — ValueLens Target Horizon", color='white', fontweight='bold')
        plt.grid(color='gray', linestyle=':', linewidth=0.5, alpha=0.5)
        plt.legend(loc="upper left")
        plt.tight_layout()

        chart_path = f"chart_{ticker}.png"
        plt.savefig(chart_path, dpi=150)
        plt.close()
        return chart_path

    except Exception as e:
        logger.error(f"Chart generation failed for {ticker}: {e}")
        return None


# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------

def broadcast_to_channel(text: str, channel_id: str, image_path: str = None) -> bool:
    """
    Dispatches payloads safely. When caption exceeds 1024 chars,
    sends photo first then the full text as a separate message.
    """
    if not BOT_TOKEN or not channel_id:
        return False

    safe_text   = _sanitise_html(text)
    success_all = True

    if image_path and os.path.exists(image_path):
        photo_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

        if len(safe_text) <= 1024:
            try:
                with open(image_path, 'rb') as photo:
                    r = requests.post(
                        photo_url,
                        data={"chat_id": channel_id, "caption": safe_text, "parse_mode": "HTML"},
                        files={"photo": photo},
                        timeout=20
                    )
                    r.raise_for_status()
                os.remove(image_path)
                return True
            except Exception as e:
                logger.error(f"Photo+caption dispatch failed: {e}")
                success_all = False
        else:
            try:
                with open(image_path, 'rb') as photo:
                    requests.post(
                        photo_url,
                        data={"chat_id": channel_id},
                        files={"photo": photo},
                        timeout=20
                    )
            except Exception as e:
                logger.warning(f"Chart-only dispatch failed: {e}")
            finally:
                try:
                    os.remove(image_path)
                except OSError:
                    pass

    msg_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunks  = [safe_text[i:i+4000] for i in range(0, len(safe_text), 4000)]

    for chunk in chunks:
        try:
            requests.post(
                msg_url,
                json={"chat_id": channel_id, "text": chunk, "parse_mode": "HTML"},
                timeout=15
            ).raise_for_status()
            time.sleep(1)
        except Exception as e:
            logger.warning(f"HTML send failed ({e}). Plain-text fallback...")
            plain = chunk.replace("<b>", "").replace("</b>", "")
            plain = plain.replace("<i>", "").replace("</i>", "")
            plain = plain.replace("<code>", "").replace("</code>", "")
            try:
                requests.post(msg_url, json={"chat_id": channel_id, "text": plain}, timeout=15)
            except Exception:
                success_all = False

    return success_all


# ---------------------------------------------------------------------------
# Morning broadcast
# ---------------------------------------------------------------------------

def morning_broadcast():
    """
    Routes pending reports to IT and EN channels.
    Uses prices cached at analysis time — no yfinance re-fetch at 8 AM.
    """
    logger.info("Morning broadcast triggered.")
    conn   = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today  = datetime.datetime.now().strftime("%Y-%m-%d")

    channels = [
        {
            "id": CHANNEL_ID_IT, "lang": "it",
            "header":  "🌅 <b>ValueLens Morning Intelligence</b>\n<i>Target rilevati:</i>\n",
            "summary": "🌅 Inviati {} report in Italiano."
        },
        {
            "id": CHANNEL_ID_EN, "lang": "en",
            "header":  "🌅 <b>ValueLens Morning Intelligence</b>\n<i>Targets detected:</i>\n",
            "summary": "🌅 {} English reports sent."
        },
    ]

    for channel in channels:
        if not channel["id"]:
            continue

        cursor.execute(
            "SELECT ticker, report_text, current_price, target_price "
            "FROM nightly_reports "
            "WHERE date(date_generated) = ? AND status = 'PENDING' AND lang = ?",
            (today, channel["lang"])
        )
        rows = cursor.fetchall()
        if not rows:
            continue

        broadcast_to_channel(channel["header"], channel["id"])

        for ticker, report_text, stored_price, stored_target in rows:
            formatted = f"<b>[ {ticker} ]</b>\n\n{report_text}\n\n〰️〰️〰️"

            c_price = stored_price
            t_price = stored_target

            if not c_price:
                try:
                    c_price = yf.Ticker(ticker).fast_info.last_price
                except Exception:
                    pass

            chart_path = generate_target_chart(ticker, c_price, t_price) if c_price else None
            success    = broadcast_to_channel(formatted, channel["id"], image_path=chart_path)

            if success:
                cursor.execute(
                    "UPDATE nightly_reports SET status = 'SENT' "
                    "WHERE ticker = ? AND date(date_generated) = ? AND lang = ?",
                    (ticker, today, channel["lang"])
                )
            time.sleep(2)

        broadcast_to_channel(channel["summary"].format(len(rows)), channel["id"])

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Nightly routine
# ---------------------------------------------------------------------------

def execute_nightly_routine():
    """
    Screens the combined universe and stores bilingual AI reports.
    Completely index-agnostic — works on whatever get_us_market_universe() returns.
    """
    logger.info("=" * 60)
    logger.info("Starting ValueLens Bilingual Nightly Screening Routine")
    logger.info("=" * 60)

    universe = get_us_market_universe()
    if not universe:
        logger.error("Universe is empty — aborting.")
        return

    value_universe   = filter_value_universe(universe)
    fast_candidates  = fast_value_screen(value_universe)
    total_candidates = deep_value_screen(fast_candidates)

    logger.info("Phase 4: AI Analysis & DB storage...")
    for candidate in total_candidates:
        ticker  = candidate["ticker"]
        info    = candidate.get("info") or {}
        c_price = info.get("currentPrice") or info.get("regularMarketPrice")
        t_price = info.get("targetMeanPrice")

        try:
            logger.info(f"Generating EN report for {ticker}...")
            report_en = analyze_company(ticker, mode="PRO", lang="en", company_info=info)
            save_report_to_db(ticker, report_en, "en", current_price=c_price, target_price=t_price)
            time.sleep(10)
        except Exception as e:
            logger.error(f"EN analysis failed for {ticker}: {e}")

        try:
            logger.info(f"Generating IT report for {ticker}...")
            report_it = analyze_company(ticker, mode="PRO", lang="it", company_info=info)
            save_report_to_db(ticker, report_it, "it", current_price=c_price, target_price=t_price)
            time.sleep(10)
        except Exception as e:
            logger.error(f"IT analysis failed for {ticker}: {e}")

    logger.info("=" * 60)
    logger.info("Nightly pipeline complete.")
    logger.info("=" * 60)