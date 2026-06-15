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
from database import DB_NAME, init_db, save_report_to_db, was_recently_alerted, record_alert_sent, open_virtual_position, evaluate_virtual_positions

load_dotenv()

logger = logging.getLogger("ValueLensScanner")

BOT_TOKEN     = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID_IT = os.environ.get("TELEGRAM_CHANNEL_ID_IT", "")
CHANNEL_ID_EN = os.environ.get("TELEGRAM_CHANNEL_ID_EN", "")

# Which universes to scan — change via .env: SCAN_UNIVERSE=sp500,nasdaq100,sp400,russell1000
SCAN_UNIVERSE = os.environ.get("SCAN_UNIVERSE", "sp500,nasdaq100,sp400,russell1000").lower()


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


def get_sp400_tickers() -> list:
    """Retrieves S&P 400 Mid-Cap tickers from local cache, refreshing from Wikipedia every 7 days."""
    return _get_tickers_cached(
        cache_file="sp400_tickers.txt",
        url="https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
        symbol_col="Ticker",
        label="S&P 400"
    )


def get_russell1000_tickers() -> list:
    """Returns the top 1000 Russell 2000 tickers by market cap.

    Fetches the full Russell 2000 list from Wikipedia, then sorts by market cap
    using yfinance fast_info and returns the top 1000. Results are cached for 7 days.
    Falls back to the raw Wikipedia list (up to 1000) if market cap fetch fails.
    """
    cache_file = "russell1000_tickers.txt"
    cache_expiry_days = 7

    if os.path.exists(cache_file):
        file_time = datetime.datetime.fromtimestamp(os.path.getmtime(cache_file))
        if datetime.datetime.now() - file_time < datetime.timedelta(days=cache_expiry_days):
            logger.info("Loading Russell 1000 universe from local cache.")
            with open(cache_file, "r") as f:
                return [line.strip() for line in f if line.strip()]

    logger.info("Cache missing or expired. Building Russell 1000 by market cap from Wikipedia Russell 2000...")
    try:
        headers  = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(
            "https://en.wikipedia.org/wiki/Russell_2000_Index",
            headers=headers, timeout=15
        )
        response.raise_for_status()

        tables = pd.read_html(response.text)
        raw_tickers = None
        for table in tables:
            for col in ("Ticker", "Symbol", "ticker", "symbol"):
                if col in table.columns:
                    raw_tickers = [t.replace(".", "-") for t in table[col].dropna().tolist()]
                    break
            if raw_tickers:
                break

        if not raw_tickers:
            raise ValueError("No ticker column found in Russell 2000 Wikipedia tables.")

        logger.info(f"Fetched {len(raw_tickers)} raw Russell 2000 tickers. Sorting top 1000 by market cap...")

        scored = []
        for ticker in raw_tickers:
            try:
                mcap = yf.Ticker(ticker).fast_info.market_cap
                if mcap and mcap > 0:
                    scored.append((ticker, mcap))
            except Exception:
                pass
            time.sleep(0.05)

        # Sort descending by market cap and take top 1000
        scored.sort(key=lambda x: x[1], reverse=True)
        top1000 = [t for t, _ in scored[:1000]]

        # Fallback: if market cap fetch retrieved fewer than 200 valid results, use raw list
        if len(top1000) < 200:
            logger.warning("Market cap sort yielded too few results — falling back to raw Wikipedia list (top 1000).")
            top1000 = raw_tickers[:1000]

        with open(cache_file, "w") as f:
            for t in top1000:
                f.write(f"{t}\n")

        logger.info(f"Cached {len(top1000)} Russell 1000 tickers.")
        return top1000

    except Exception as e:
        logger.error(f"Error building Russell 1000 list: {e}")
        if os.path.exists(cache_file):
            logger.warning("Returning expired Russell 1000 cache as fallback.")
            with open(cache_file, "r") as f:
                return [line.strip() for line in f if line.strip()]
        return []


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
    Returns a deduplicated list of tickers from all configured universes.
    Each element is a dict: {"ticker": str, "universe_source": str}.
    First-seen index wins deduplication (sp500 > nasdaq100 > sp400 > russell1000).
    Earnings sniper and insider tracking only use sp500/nasdaq100 tickers.
    Controlled by SCAN_UNIVERSE env var (default: sp500,nasdaq100,sp400,russell1000).
    """
    seen   = set()
    merged = []

    index_map = [
        ("sp500",       get_sp500_tickers),
        ("nasdaq100",   get_nasdaq100_tickers),
        ("sp400",       get_sp400_tickers),
        ("russell1000", get_russell1000_tickers),
    ]

    for source, fetcher in index_map:
        if source not in SCAN_UNIVERSE:
            continue
        tickers = fetcher()
        added = 0
        for t in tickers:
            if t not in seen:
                seen.add(t)
                merged.append({"ticker": t, "universe_source": source})
                added += 1
        logger.info(f"{source.upper()} contributed {added} unique tickers.")

    logger.info(f"Combined universe: {len(merged)} unique tickers (config: '{SCAN_UNIVERSE}')")
    return merged


def get_core_universe_tickers() -> list:
    """Returns a flat deduplicated list of ticker strings for sp500 and nasdaq100 only.

    Used by earnings_engine and insider_engine, which are intentionally restricted
    to the core large-cap universe regardless of the SCAN_UNIVERSE setting.
    """
    seen   = set()
    result = []
    for t in get_sp500_tickers() + get_nasdaq100_tickers():
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


# ---------------------------------------------------------------------------
# Screening pipeline
# ---------------------------------------------------------------------------

def filter_value_universe(tickers: list, max_candidates=150, sleep_seconds=0.05) -> list:
    """
    First pass: cheap fast_info scan across the full universe.
    Sorts by deepest 52-week discount. Index-agnostic.

    Args:
        tickers: List of dicts {"ticker": str, "universe_source": str}
                 or plain strings (backwards compatibility).
    Returns:
        List of dicts {"ticker": str, "universe_source": str, "discount": float}.
    """
    candidates = []
    for i, item in enumerate(tickers):
        # Support both dict format (new) and plain string (legacy)
        if isinstance(item, dict):
            ticker = item["ticker"]
            universe_source = item.get("universe_source", "sp500")
        else:
            ticker = item
            universe_source = "sp500"

        if i % 100 == 0 and i > 0:
            logger.info(f"Filter progress: {i}/{len(tickers)}...")
        try:
            f_info  = yf.Ticker(ticker).fast_info
            high    = getattr(f_info, 'year_high', None) or getattr(f_info, 'yearHigh', None)
            current = getattr(f_info, 'last_price', None) or getattr(f_info, 'lastPrice', None)

            if high and current and high > 0:
                discount = (high - current) / high
                candidates.append({"ticker": ticker, "universe_source": universe_source, "discount": discount})
        except Exception:
            pass
        time.sleep(sleep_seconds)

    candidates.sort(key=lambda x: x['discount'], reverse=True)
    top = candidates[:max_candidates]
    logger.info(f"Phase 1: {len(top)} candidates by 52w discount.")
    return top


def fast_value_screen(tickers_list: list, max_candidates=20) -> list:
    """Second pass: narrows to the top N from the discount-sorted list.

    Args:
        tickers_list: List of dicts from filter_value_universe.
    Returns:
        Top N dicts, universe_source preserved.
    """
    top = tickers_list[:max_candidates]
    logger.info(f"Phase 2 fast-screen: {[c['ticker'] for c in top]}")
    return top


def deep_value_screen(tickers_list: list, max_candidates=15,
                      sleep_seconds=15, pe_threshold=25) -> list:
    """
    Third pass: full .info fetch validating P/E ratio and analyst upside.
    pe_threshold overridable via PE_THRESHOLD env var.
    Returns list of dicts carrying the fetched info so callers don't re-fetch.
    universe_source is preserved from the input list.
    """
    pe_threshold = int(os.environ.get("PE_THRESHOLD", pe_threshold))
    candidates   = []

    for item in tickers_list:
        ticker          = item["ticker"]
        universe_source = item.get("universe_source", "sp500")
        try:
            logger.info(f"Deep scan: {ticker}...")
            info = yf.Ticker(ticker).info

            current     = info.get("currentPrice") or info.get("regularMarketPrice")
            target_mean = info.get("targetMeanPrice")
            pe          = info.get("trailingPE") or info.get("forwardPE")

            if pe is not None and pe > pe_threshold:
                logger.info(f"Rejected {ticker}: P/E {pe} > {pe_threshold}.")
                continue

            if current and target_mean and current > 0:
                upside = (target_mean - current) / current
                candidates.append({
                    "ticker": ticker,
                    "universe_source": universe_source,
                    "upside": upside,
                    "info": info,
                })

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
# Nightly winners cache — shared between scanner and insider_engine
# ---------------------------------------------------------------------------

_WINNERS_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nightly_winners.json")


def _write_nightly_winners(tickers: list):
    """Persists tonight's fundamental winners to a temp file for the insider engine."""
    import json as _json
    try:
        with open(_WINNERS_CACHE_PATH, "w") as f:
            _json.dump({"tickers": tickers, "date": str(datetime.datetime.now().date())}, f)
    except Exception as e:
        logger.warning(f"Could not write nightly winners cache: {e}")


def get_nightly_winners() -> list:
    """Returns tonight's fundamental winners. Empty list if stale or missing."""
    import json as _json
    try:
        with open(_WINNERS_CACHE_PATH) as f:
            data = _json.load(f)
        file_date = datetime.date.fromisoformat(data.get("date", "2000-01-01"))
        if (datetime.date.today() - file_date).days <= 1:
            return data.get("tickers", [])
    except Exception:
        pass
    return []

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

    channels = [
        {
            "id": CHANNEL_ID_IT, "lang": "it",
            "header": "🌅 <b>ValueLens Morning Intelligence</b>\n<i>Target rilevati:</i>\n",
        },
        {
            "id": CHANNEL_ID_EN, "lang": "en",
            "header": "🌅 <b>ValueLens Morning Intelligence</b>\n<i>Targets detected:</i>\n",
        },
    ]

    for channel in channels:
        if not channel["id"]:
            continue

        # Search PENDING reports from the last 2 days to survive restarts and date boundaries
        cursor.execute(
            "SELECT ticker, report_text, current_price, target_price "
            "FROM nightly_reports "
            "WHERE date(date_generated) >= date('now', '-2 days') AND status = 'PENDING' AND lang = ?",
            (channel["lang"],)
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
                    "WHERE ticker = ? AND status = 'PENDING' AND lang = ?",
                    (ticker, channel["lang"])
                )
            time.sleep(2)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Nightly routine
# ---------------------------------------------------------------------------

def execute_nightly_routine():
    """
    Screens the combined universe and stores bilingual AI reports.
    Completely index-agnostic — works on whatever get_us_market_universe() returns.
    Each pick is tagged with its universe_source and saved to the database.
    Earnings sniper and insider tracking remain restricted to sp500/nasdaq100.
    """
    logger.info("=" * 60)
    logger.info("Starting ValueLens Bilingual Nightly Screening Routine")
    logger.info("=" * 60)

    universe = get_us_market_universe()
    if not universe:
        logger.error("Universe is empty — aborting.")
        return

    # Pre-filter universe — remove tickers alerted in the last 14 days.
    # universe is a list of dicts {"ticker": str, "universe_source": str}.
    pre_filtered = [
        item for item in universe
        if not was_recently_alerted(item["ticker"], cooldown_days=14)
    ]
    logger.info(f"Pre-filter: {len(universe)} → {len(pre_filtered)} tickers after 14-day cooldown.")

    value_universe   = filter_value_universe(pre_filtered)
    fast_candidates  = fast_value_screen(value_universe)
    total_candidates = deep_value_screen(fast_candidates)

    logger.info("Phase 4: AI Analysis & DB storage...")

    # Tonight's winners — written to cache for insider_engine Golden Combo check
    nightly_winners = []

    for candidate in total_candidates:
        ticker          = candidate["ticker"]
        universe_source = candidate.get("universe_source", "sp500")
        info            = candidate.get("info") or {}
        c_price         = info.get("currentPrice") or info.get("regularMarketPrice")
        t_price         = info.get("targetMeanPrice")

        # Deduplication: skip tickers alerted in the last 14 days
        if was_recently_alerted(ticker, cooldown_days=14):
            logger.info(f"Skipping {ticker} — alerted within cooldown window.")
            continue

        nightly_winners.append(ticker)

        try:
            logger.info(f"Generating EN report for {ticker} [{universe_source}]...")
            report_en = analyze_company(ticker, mode="PRO", lang="en", company_info=info)
            save_report_to_db(ticker, report_en, "en", current_price=c_price, target_price=t_price, universe_source=universe_source)
            time.sleep(10)
        except Exception as e:
            logger.error(f"EN analysis failed for {ticker}: {e}")

        try:
            logger.info(f"Generating IT report for {ticker} [{universe_source}]...")
            report_it = analyze_company(ticker, mode="PRO", lang="it", company_info=info)
            save_report_to_db(ticker, report_it, "it", current_price=c_price, target_price=t_price, universe_source=universe_source)
            time.sleep(10)
        except Exception as e:
            logger.error(f"IT analysis failed for {ticker}: {e}")

        # Mark ticker as alerted in unified deduplication table
        record_alert_sent(ticker, alert_type="fundamental")

        # Open virtual portfolio position for this pick
        if c_price:
            open_virtual_position(ticker, entry_price=c_price, target_price=t_price)

    # Persist tonight's winners list for the insider engine
    _write_nightly_winners(nightly_winners)

    # Evaluate existing virtual positions for exit conditions
    evaluate_virtual_positions()

    logger.info("=" * 60)
    logger.info(f"Nightly pipeline complete. New reports: {len(nightly_winners)}")
    logger.info("=" * 60)