"""
live_stream.py — Persistent Yahoo Finance WebSocket price streamer.

Replaces per-request yfinance.fast_info HTTP polling with a single,
long-lived WebSocket connection to Yahoo Finance's official streaming
endpoint. yfinance ships this as a documented, first-class feature
(yfinance.WebSocket / yfinance.AsyncWebSocket) — it isn't a private hack.

Why this exists:
  The old approach made one HTTP request per ticker per cache-refresh
  cycle (see web_api.py's _fetch_live_quote). With ~25 unique tickers
  across picks + portfolio + insiders, even a 10s frontend poll already
  generated roughly 9,000 requests/hour to Yahoo — well past the
  ~2,000/hour soft limit the yfinance community has observed before
  Yahoo starts returning 429s. Lowering the poll interval would only
  have made that worse.

  This module instead opens ONE persistent WebSocket connection,
  subscribed to the dynamic ticker set, and lets Yahoo push price
  updates as they happen. Every message updates the same in-memory
  cache (_live_price_cache) that /api/live_prices already reads from.
  The frontend's poll frequency no longer touches Yahoo at all — it
  only reads local memory on the Pi — so polling at 3s instead of 10s
  carries zero additional Yahoo rate-limit risk.

Usage from web_api.py:
    from live_stream import start_streamer, update_subscriptions

    start_streamer()                  # called once at startup
    update_subscriptions(ticker_list) # called whenever the relevant
                                       # ticker set changes (e.g. after
                                       # a fresh /api/live_prices auto-mode
                                       # lookup)
"""

import logging
import threading
import time

import yfinance as yf

logger = logging.getLogger("ValueLensLiveStream")

# Shared with web_api.py — imported lazily inside functions to avoid a
# circular import (web_api.py imports this module, not the other way around).
_cache_ref = None  # set via attach_cache()

_ws = None
_ws_lock = threading.Lock()
_current_symbols: set = set()
_thread: threading.Thread = None
_started = False


def attach_cache(cache_dict: dict):
    """Lets web_api.py hand over its existing _live_price_cache dict so this
    module writes into the exact same object the REST endpoint reads from.
    Avoids needing a second cache or any cross-module polling.
    """
    global _cache_ref
    _cache_ref = cache_dict


def _on_message(message: dict):
    """Yahoo pushes one message per ticker update. Maps it onto the same
    {"price": float, "change": float, "ts": epoch} shape _get_live_quotes()
    already expects, so /api/live_prices needs zero changes.
    """
    if _cache_ref is None:
        return
    try:
        symbol = message.get("id")
        price  = message.get("price")
        change_pct = message.get("change_percent")
        if not symbol or price is None:
            return
        _cache_ref[symbol] = {
            "price": round(float(price), 2),
            "change": round(float(change_pct), 2) if change_pct is not None else 0.0,
            "ts": time.time(),
        }
    except Exception as e:
        logger.debug(f"live_stream: failed to process message {message}: {e}")


def _run_forever():
    """Runs in a background thread for the lifetime of the process.
    Reconnects automatically on failure — Yahoo's WebSocket can drop
    connections (network blips, Yahoo-side restarts), and yfinance's
    listen() loop doesn't retry on its own, so we wrap it in a retry loop.
    """
    global _ws
    backoff = 5
    while True:
        try:
            with _ws_lock:
                _ws = yf.WebSocket(verbose=False)
                if _current_symbols:
                    _ws.subscribe(list(_current_symbols))
            logger.info("Live stream: connected to Yahoo Finance WebSocket.")
            backoff = 5  # reset backoff after a successful connection
            _ws.listen(_on_message)  # blocks until the connection drops
        except Exception as e:
            logger.warning(f"Live stream: connection lost ({e}). Reconnecting in {backoff}s...")
        finally:
            with _ws_lock:
                _ws = None
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)  # exponential backoff, capped at 60s


def start_streamer():
    """Starts the background WebSocket thread. Safe to call multiple times —
    only the first call actually starts anything.
    """
    global _thread, _started
    if _started:
        return
    _started = True
    _thread = threading.Thread(target=_run_forever, daemon=True, name="yf-live-stream")
    _thread.start()
    logger.info("Live stream: background thread started.")


def update_subscriptions(symbols: list):
    """Updates the WebSocket subscription set to match the currently
    relevant tickers (picks + insiders + open portfolio positions).
    Called from web_api.py whenever that set is (re)computed — cheap to
    call often since it only sends a diff, not a full resubscribe.
    """
    global _current_symbols
    new_symbols = set(s.strip().upper() for s in symbols if s.strip())
    if new_symbols == _current_symbols:
        return

    to_add    = new_symbols - _current_symbols
    to_remove = _current_symbols - new_symbols
    _current_symbols = new_symbols

    with _ws_lock:
        if _ws is None:
            # Not connected yet (or mid-reconnect) — _run_forever() will
            # pick up _current_symbols on its next connection attempt.
            return
        try:
            if to_add:
                _ws.subscribe(list(to_add))
            if to_remove:
                _ws.unsubscribe(list(to_remove))
        except Exception as e:
            logger.warning(f"Live stream: failed to update subscriptions: {e}")
