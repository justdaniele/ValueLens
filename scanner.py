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
from database import DB_NAME, init_db, save_report_to_db, open_virtual_position, evaluate_virtual_positions

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
        symbol_col=["Symbol", "Ticker"],
        label="S&P 400"
    )


def get_russell1000_tickers() -> list:
    """Returns the current Russell 1000 Index constituents.

    Sourced from the official iShares Russell 1000 ETF (IWB) holdings file,
    which BlackRock publishes daily and tracks the index almost exactly
    (~1000 holdings). This is the only free, reliable, and complete source —
    Wikipedia does not maintain a full Russell 1000/2000 constituent list.
    Results are cached locally for 7 days.

    NOTE: BlackRock retired the old direct CSV ajax endpoint (the URL used
    to end in "<hash>.ajax?fileType=csv...") — it now returns the product
    page's HTML instead of the file, even though it still claims a
    text/csv Content-Type. The current working source is BlackRock's
    fund-document API, which returns the holdings as an Excel file
    (.xls/.xlsx) rather than CSV. If this breaks again in the future, check
    the "Data Download" link on the fund's page at
    https://www.ishares.com/us/products/239707/ishares-russell-1000-etf
    for whatever the current endpoint/format is.
    """
    cache_file = "russell1000_tickers.txt"
    cache_expiry_days = 7

    if os.path.exists(cache_file):
        file_time = datetime.datetime.fromtimestamp(os.path.getmtime(cache_file))
        if datetime.datetime.now() - file_time < datetime.timedelta(days=cache_expiry_days):
            logger.info("Loading Russell 1000 universe from local cache.")
            with open(cache_file, "r") as f:
                return [line.strip() for line in f if line.strip()]

    logger.info("Cache missing or expired. Downloading Russell 1000 constituents from BlackRock fund-document API...")
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        url = (
            "https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1/get-fund-document"
            "?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=us-ishares&locale=en_US"
            "&portfolioId=239707&component=fundDownload&userType=individual"
        )
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        from io import BytesIO
        excel_bytes = BytesIO(response.content)

        # The holdings table has a few metadata rows above it, same as the
        # old CSV did — read without a header first, find the row that
        # starts with "ticker" (case-insensitive), then re-read using that
        # row as the actual header.
        raw = pd.read_excel(excel_bytes, header=None, engine=None)

        header_idx = None
        for i in range(len(raw)):
            first_cell = str(raw.iloc[i, 0]).strip().lower()
            if first_cell.startswith("ticker"):
                header_idx = i
                break

        if header_idx is None:
            raise ValueError("Could not locate holdings header row in iShares holdings file.")

        excel_bytes.seek(0)
        df = pd.read_excel(excel_bytes, header=header_idx, engine=None)

        # Resolve actual column names case-insensitively (e.g. "ticker" vs
        # "Ticker", "asset_class" vs "Asset Class") instead of assuming one
        # exact casing — BlackRock has changed this before.
        col_map = {str(c).lower().replace("_", " ").strip(): c for c in df.columns}
        ticker_col = col_map.get("ticker")
        asset_class_col = col_map.get("asset class")

        if not ticker_col:
            raise ValueError("Ticker column not found in iShares holdings file.")

        # Drop cash/derivative rows (blank ticker or non-equity asset class)
        df = df[df[ticker_col].notna()]
        if asset_class_col:
            df = df[df[asset_class_col].astype(str).str.contains("Equity", case=False, na=False)]

        tickers = [str(t).strip().replace(".", "-") for t in df[ticker_col].tolist() if str(t).strip()]
        tickers = [t for t in tickers if t and t.upper() not in ("CASH", "USD", "-", "NAN")]

        if len(tickers) < 500:
            raise ValueError(f"Suspiciously few tickers parsed ({len(tickers)}) — possible format change.")

        with open(cache_file, "w") as f:
            for t in tickers:
                f.write(f"{t}\n")

        logger.info(f"Cached {len(tickers)} Russell 1000 tickers from iShares IWB.")
        return tickers

    except Exception as e:
        logger.error(f"Error fetching Russell 1000 list from iShares: {e}")
        if os.path.exists(cache_file):
            logger.warning("Returning expired Russell 1000 cache as fallback.")
            with open(cache_file, "r") as f:
                return [line.strip() for line in f if line.strip()]
        logger.warning("No Russell 1000 cache available — returning empty list for this cycle.")
        return []


def _get_tickers_cached(cache_file: str, url: str, symbol_col, label: str) -> list:
    """Generic cached ticker fetcher shared by S&P 500, NASDAQ-100, and S&P 400.

    symbol_col can be a single column name (str) or a list of candidate names
    to try in order — Wikipedia occasionally renames the ticker column
    (e.g. 'Ticker' -> 'Symbol'), so trying a couple of candidates makes this
    resilient to that kind of drift without needing a code change each time.
    """
    cache_expiry_days = 7
    candidates = [symbol_col] if isinstance(symbol_col, str) else list(symbol_col)

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

        from io import StringIO
        tables  = pd.read_html(StringIO(response.text))
        tickers = None

        for table in tables:
            for col in candidates:
                if col in table.columns:
                    tickers = [t.replace('.', '-') for t in table[col].dropna().tolist()]
                    break
            if tickers:
                break

        if not tickers:
            raise ValueError(f"None of {candidates} found as a column in any Wikipedia table.")

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

    Analyst target scaling — Wall Street's targetMeanPrice is a 12-month
    forecast (sometimes 6 or 18), not a 90-day one. The virtual portfolio
    holds positions for 90 days, so treating the full 12-month target as
    achievable in that window systematically overstates near-term upside
    (e.g. INTU's +74% 12-month consensus isn't a +74%-in-90-days call).
    Instead of discarding genuinely strong picks just because their annual
    upside looks large, we scale the upside linearly to the 90-day window
    (upside_90d = upside_12m * 90/365) and rescale target_mean to match —
    so a pick with +74% annual upside becomes roughly +18% over 90 days,
    which is what the virtual portfolio's target/stop/time exit logic
    actually uses. HOLDING_DAYS is overridable via env var to stay in sync
    with whatever holding period the virtual portfolio uses elsewhere.

    MIN_UPSIDE_PCT (default 0, overridable via env var) still rejects
    tickers whose target is at or below the current price — a pick with
    negative or zero upside is a bug, not a recommendation, and would
    otherwise cause the virtual portfolio to open and immediately close
    the position (current price already at/above the target).

    Returns list of dicts carrying the fetched info so callers don't re-fetch.
    universe_source is preserved from the input list. The returned info dict
    has targetMeanPrice replaced with the 90-day-scaled value, so downstream
    code (DB save, virtual portfolio open) automatically uses the realistic
    target without needing any further changes.
    """
    pe_threshold  = int(os.environ.get("PE_THRESHOLD", pe_threshold))
    min_upside    = float(os.environ.get("MIN_UPSIDE_PCT", 0)) / 100
    holding_days  = float(os.environ.get("HOLDING_DAYS", 90))
    scale_factor  = holding_days / 365
    candidates    = []

    for item in tickers_list:
        ticker          = item["ticker"]
        universe_source = item.get("universe_source", "sp500")
        try:
            logger.info(f"Deep scan: {ticker}...")
            info = yf.Ticker(ticker).info

            current        = info.get("currentPrice") or info.get("regularMarketPrice")
            target_mean_1y = info.get("targetMeanPrice")
            pe             = info.get("trailingPE") or info.get("forwardPE")

            if pe is not None and pe > pe_threshold:
                logger.info(f"Rejected {ticker}: P/E {pe} > {pe_threshold}.")
                continue

            if not (current and target_mean_1y and current > 0):
                continue

            upside_1y = (target_mean_1y - current) / current

            if upside_1y <= min_upside:
                logger.info(f"Rejected {ticker}: 12-month upside {upside_1y*100:.1f}% <= {min_upside*100:.0f}% (target ${target_mean_1y:.2f} vs current ${current:.2f}).")
                continue

            # Scale the 12-month consensus upside down to the 90-day holding
            # window, then rescale target_mean to match. This is what makes
            # the +74%-in-12-months INTU case become a realistic +18% target
            # for the actual holding period, instead of either an absurd
            # 90-day target or a discarded pick.
            upside_90d        = upside_1y * scale_factor
            target_mean_90d   = current * (1 + upside_90d)
            info["targetMeanPrice"] = target_mean_90d

            logger.info(f"{ticker}: 12mo upside {upside_1y*100:.1f}% scaled to {holding_days:.0f}d upside {upside_90d*100:.1f}% (target ${target_mean_1y:.2f} -> ${target_mean_90d:.2f}).")

            candidates.append({
                "ticker": ticker,
                "universe_source": universe_source,
                "upside": upside_90d,
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
# NOTE: morning_broadcast() was removed — Top Picks no longer go to Telegram.
# They recalculate fresh every night on the website with no cooldown.
# broadcast_to_channel() above is kept as a shared helper, now used by the
# virtual portfolio Telegram notifications (see notify_portfolio_event below).
# ---------------------------------------------------------------------------

def notify_portfolio_event(event: str, ticker: str, price: float, extra: dict = None):
    """Sends a bilingual Telegram alert for a virtual portfolio event.

    event: "OPEN", "TARGET", "STOP", or "TIME".
    extra: optional dict with event-specific fields (e.g. pnl_pct, target_price).
    Called by database.py's open_virtual_position() and evaluate_virtual_positions()
    so every buy, sell, stop-loss, and time-exit is reported on Telegram.
    """
    extra = extra or {}

    if event == "OPEN":
        msg_en = (f"🟢 <b>Virtual Portfolio: Opened {ticker}</b>\n\n"
                  f"Entry price: <code>${price:.2f}</code>\n"
                  f"Target: <code>${extra.get('target_price', 0):.2f}</code>" if extra.get("target_price")
                  else f"🟢 <b>Virtual Portfolio: Opened {ticker}</b>\n\nEntry price: <code>${price:.2f}</code>")
        msg_it = (f"🟢 <b>Portafoglio Virtuale: Apertura {ticker}</b>\n\n"
                  f"Prezzo di entrata: <code>${price:.2f}</code>\n"
                  f"Target: <code>${extra.get('target_price', 0):.2f}</code>" if extra.get("target_price")
                  else f"🟢 <b>Portafoglio Virtuale: Apertura {ticker}</b>\n\nPrezzo di entrata: <code>${price:.2f}</code>")

    elif event in ("TARGET", "STOP", "TIME"):
        pnl_pct = extra.get("pnl_pct", 0.0)
        sign    = "+" if pnl_pct >= 0 else ""
        icon    = "🎯" if event == "TARGET" else "🔴" if event == "STOP" else "⏱️"
        label_en = {"TARGET": "Target reached", "STOP": "Stop-loss hit", "TIME": "Time exit (90 days)"}[event]
        label_it = {"TARGET": "Target raggiunto", "STOP": "Stop-loss attivato", "TIME": "Uscita per tempo (90 giorni)"}[event]

        msg_en = (f"{icon} <b>Virtual Portfolio: Closed {ticker}</b>\n\n"
                  f"Reason: <b>{label_en}</b>\n"
                  f"Exit price: <code>${price:.2f}</code>\n"
                  f"P&amp;L: <b>{sign}{pnl_pct:.1f}%</b>")
        msg_it = (f"{icon} <b>Portafoglio Virtuale: Chiusura {ticker}</b>\n\n"
                  f"Motivo: <b>{label_it}</b>\n"
                  f"Prezzo di uscita: <code>${price:.2f}</code>\n"
                  f"P&amp;L: <b>{sign}{pnl_pct:.1f}%</b>")
    else:
        return

    if CHANNEL_ID_EN:
        broadcast_to_channel(msg_en, CHANNEL_ID_EN)
    if CHANNEL_ID_IT:
        broadcast_to_channel(msg_it, CHANNEL_ID_IT)


# ---------------------------------------------------------------------------
# Nightly routine
# ---------------------------------------------------------------------------

def execute_nightly_routine():
    """
    Screens the combined universe and stores bilingual AI reports.
    Completely index-agnostic — works on whatever get_us_market_universe() returns.
    Each pick is tagged with its universe_source and saved to the database.
    Earnings sniper and insider tracking remain restricted to sp500/nasdaq100.

    Top Picks are recalculated from scratch every night with no cooldown —
    a genuinely undervalued ticker should keep showing up for as long as it
    remains a top candidate, rather than disappearing for a fixed window.
    The only deduplication left is at the virtual-portfolio level: opening a
    new position is skipped if one is already OPEN for that ticker.
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

    # Tonight's winners — written to cache for insider_engine Golden Combo check
    nightly_winners = []

    for candidate in total_candidates:
        ticker          = candidate["ticker"]
        universe_source = candidate.get("universe_source", "sp500")
        info            = candidate.get("info") or {}
        c_price         = info.get("currentPrice") or info.get("regularMarketPrice")
        t_price         = info.get("targetMeanPrice")

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

        # Open virtual portfolio position for this pick.
        # open_virtual_position() already no-ops if a position for this
        # ticker is already OPEN, so re-appearing picks won't be re-bought.
        if c_price:
            open_virtual_position(ticker, entry_price=c_price, target_price=t_price)

    # Persist tonight's winners list for the insider engine
    _write_nightly_winners(nightly_winners)

    # Evaluate existing virtual positions for exit conditions
    evaluate_virtual_positions()

    logger.info("=" * 60)
    logger.info(f"Nightly pipeline complete. New reports: {len(nightly_winners)}")
    logger.info("=" * 60)