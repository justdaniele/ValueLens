import os
import asyncio
import time
import logging
import requests
import html
import datetime
import pandas as pd
import yfinance as yf
from analyzer import generate_earnings_sentiment_layer
from database import save_earnings_prediction
from scanner import get_core_universe_tickers, _sanitise_html

logger = logging.getLogger("EarningsEngine")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID_IT = os.environ.get("TELEGRAM_CHANNEL_ID_IT", "")
CHANNEL_ID_EN = os.environ.get("TELEGRAM_CHANNEL_ID_EN", "")
EES_FIRE_THRESHOLD = int(os.environ.get("EES_FIRE_THRESHOLD", "50"))

def send_alert_to_channel(text_en: str, text_it: str = None):
    """Broadcasts localized alerts applying structural safety HTML escape utilities."""
    if not BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    def dispatch(channel: str, text: str):
        safe_text = _sanitise_html(text)
        try:
            requests.post(url, json={"chat_id": channel, "text": safe_text, "parse_mode": "HTML"}, timeout=15)
        except Exception as e:
            logger.error(f"Failed sending alert: {e}")

    if CHANNEL_ID_EN and text_en:
        dispatch(CHANNEL_ID_EN, text_en)
    if CHANNEL_ID_IT and (text_it or text_en):
        dispatch(CHANNEL_ID_IT, text_it if text_it else text_en)

def _get_earnings_in_window(universe: list, lookahead_hours: int = 48) -> list:
    """Scans the universe and returns tickers with earnings in the lookahead window."""
    upcoming = []
    cutoff = datetime.datetime.now() + datetime.timedelta(hours=lookahead_hours)

    for ticker in universe:
        try:
            stock = yf.Ticker(ticker)
            earnings_dt = None

            cal = stock.calendar
            if cal and isinstance(cal, dict):
                dates = cal.get("Earnings Date")
                if dates:
                    for d in (dates if isinstance(dates, list) else [dates]):
                        try:
                            dt = pd.Timestamp(d).to_pydatetime().replace(tzinfo=None)
                            if datetime.datetime.now() <= dt <= cutoff:
                                earnings_dt = dt
                                break
                        except Exception:
                            pass

            if earnings_dt is None:
                info = stock.info
                for key in ("earningsTimestamp", "earningsTimestampStart"):
                    ts = info.get(key)
                    if ts:
                        try:
                            dt = datetime.datetime.utcfromtimestamp(ts)
                            if datetime.datetime.now() <= dt <= cutoff:
                                earnings_dt = dt
                                break
                        except Exception:
                            pass

            if earnings_dt:
                logger.info(f"Earnings detected for {ticker} at {earnings_dt}")
                upcoming.append(ticker)

        except Exception as e:
            logger.debug(f"Calendar lookup failed for {ticker}: {e}")
        
        time.sleep(0.3)  # Standard courtesy pacing delay to prevent IP bans
    return upcoming

def _compute_quant_score(stock: yf.Ticker) -> float:
    """Pre-earnings momentum score [-30, +30].

    Momentum: near 52w HIGH = institutional conviction, tends to beat.
    Earnings/Revenue growth: positive = bullish setup.
    Analyst consensus: strong buy cluster = conviction.
    Short interest: high short = bearish expectation from smart money.
    """
    score = 0.0
    try:
        f    = stock.fast_info
        info = stock.info

        high_52 = getattr(f, "year_high", None) or getattr(f, "yearHigh", None)
        low_52  = getattr(f, "year_low",  None) or getattr(f, "yearLow",  None)
        price   = getattr(f, "last_price", None) or getattr(f, "lastPrice", None)

        # Momentum (±12 pts) — near 52w high = beat probability higher
        if high_52 and low_52 and price and (high_52 - low_52) > 0:
            range_pct = (price - low_52) / (high_52 - low_52)
            score += (range_pct - 0.5) * 24.0

        # Earnings growth (±10 pts)
        eq_growth = info.get("earningsQuarterlyGrowth")
        if eq_growth is not None:
            if eq_growth > 0.20:    score += 10.0
            elif eq_growth > 0.05:  score += 5.0
            elif eq_growth < -0.20: score -= 10.0
            elif eq_growth < 0:     score -= 5.0

        # Revenue growth (±5 pts)
        rev_growth = info.get("revenueQuarterlyGrowth") or info.get("revenueGrowth")
        if rev_growth is not None:
            if rev_growth > 0.10:   score += 5.0
            elif rev_growth > 0:    score += 2.0
            elif rev_growth < -0.05: score -= 5.0

        # Analyst consensus (±5 pts) — 1=Strong Buy 3=Hold 5=Strong Sell
        rec = info.get("recommendationMean")
        if rec:
            score += (3.0 - rec) * 2.5

        # Short interest (±3 pts)
        short_pct = info.get("shortPercentOfFloat") or 0.0
        if short_pct > 0.25:    score -= 3.0
        elif short_pct > 0.15:  score -= 1.5
        elif short_pct < 0.03:  score += 3.0

    except Exception as e:
        logger.debug(f"Quant score error: {e}")
    return max(-30.0, min(30.0, score))


async def run_earnings_pipeline(silent: bool = False):
    """Triggers the predictive earnings analysis on genuine upcoming earnings catalysts.

    When silent=True, skips Telegram alerts and only saves predictions to the database.
    Used for midday/additional runs to keep the dashboard fresh without spamming Telegram.
    """
    logger.info("Initiating Earnings Catalyst Sniper Engine...")
    # Earnings sniper is restricted to sp500 + nasdaq100 (core large-cap universe)
    universe = get_core_universe_tickers()
    if not universe:
        logger.warning("Universe is empty — skipping earnings pipeline.")
        return

    logger.info(f"Scanning {len(universe)} tickers for earnings in the next 48h...")
    upcoming = await asyncio.to_thread(_get_earnings_in_window, universe)

    if not upcoming:
        logger.info("No earnings events detected in the next 48h. Sniper standing by.")
        return

    for ticker in upcoming:
        try:
            stock = yf.Ticker(ticker)
            curr_price = stock.fast_info.last_price
            company_name = stock.info.get("shortName", ticker)

            quant_score = _compute_quant_score(stock)
            ai_score    = generate_earnings_sentiment_layer(ticker, company_name)
            final_ees   = round(quant_score + ai_score)

            direction    = "BULLISH" if final_ees >= 0 else "BEARISH"
            direction_it = "RIALZISTA" if final_ees >= 0 else "RIBASSISTA"

            save_earnings_prediction(ticker, curr_price, direction, ees_score=final_ees)

            if abs(final_ees) >= EES_FIRE_THRESHOLD:
                msg_en = (f"🎯 <b>Sniper Alert: {ticker}</b>\n\n"
                          f"Score: <b>{final_ees}</b>\n"
                          f"Quant: {round(quant_score)} | AI Sentiment: {ai_score}\n"
                          f"Prediction: <b>{direction}</b>\n"
                          f"Price at signal: <code>${curr_price:.2f}</code>")
                          
                msg_it = (f"🎯 <b>Sniper Alert: {ticker}</b>\n\n"
                          f"Punteggio: <b>{final_ees}</b>\n"
                          f"Quant: {round(quant_score)} | Sentiment AI: {ai_score}\n"
                          f"Previsione: <b>{direction_it}</b>\n"
                          f"Prezzo al segnale: <code>${curr_price:.2f}</code>")
                
                if not silent:
                    send_alert_to_channel(msg_en, msg_it)
                    time.sleep(2)
        except Exception as e:
            logger.error(f"Error processing {ticker}: {e}")