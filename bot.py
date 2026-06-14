import os
import asyncio
import logging
import datetime
import requests
from dotenv import load_dotenv

from scanner import execute_nightly_routine, morning_broadcast
from database import init_db, get_accuracy_metrics, evaluate_historical_accuracy_loop
from earnings_engine import send_alert_to_channel, run_earnings_pipeline
from weekly_engine import generate_and_broadcast_weekly_recap
from insider_engine import run_insider_tracking
from scan_engine import run_full_scan

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ValueLensMaster: %(message)s",
    handlers=[
        logging.FileHandler("valuelens_master.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ValueLensMaster")


async def wait_until(hour: int, minute: int):
    """Calculates remaining seconds until next targeted time occurrence and enters sleep."""
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if target <= now:
        target += datetime.timedelta(days=1)

    sleep_seconds = (target - now).total_seconds()

    logger.info(
        f"Next task scheduled for {target.strftime('%Y-%m-%d %H:%M:%S')}. "
        f"Sleeping {sleep_seconds:.2f}s."
    )

    await asyncio.sleep(sleep_seconds)


async def incoming_commands_polling_loop():
    """Asynchronous Telegram admin listener."""

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_id_str = os.environ.get("ADMIN_TELEGRAM_ID", "")

    if not admin_id_str:
        logger.error("CRITICAL: ADMIN_TELEGRAM_ID missing.")
        while True:
            await asyncio.sleep(60)

    admin_id = int(admin_id_str)
    offset = 0

    updates_url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    while True:
        try:

            def fetch():
                r = requests.get(
                    updates_url,
                    json={"offset": offset, "timeout": 20},
                    timeout=25
                )
                return r.json() if r.status_code == 200 else None

            response_data = await asyncio.to_thread(fetch)

            if not response_data or not response_data.get("ok"):
                await asyncio.sleep(3)
                continue

            for update in response_data.get("result", []):

                offset = update["update_id"] + 1

                message = update.get("message")

                if not message or "text" not in message:
                    continue

                chat_id = message["chat"]["id"]
                user_id = message["from"]["id"]
                text = message["text"].strip()

                if user_id != admin_id:
                    public_msg = (
                        "🤖 <b>ValueLens Terminal</b>\n\n"
                        "Private system."
                    )

                    def _send_public(c=chat_id, m=public_msg):
                        requests.post(send_url, json={"chat_id": c, "text": m, "parse_mode": "HTML"})
                    await asyncio.to_thread(_send_public)
                    continue

                if text.startswith("/"):
                    command = text.split()[0].lower()
                    reply = ""

                    if command == "/accuracy":
                        w, t, p = get_accuracy_metrics()
                        reply = (
                            f"📊 <b>ValueLens Accuracy Ledger</b>\n"
                            f"• Wins: <code>{w}/{t}</code>\n"
                            f"• Ratio: <b>{p}</b>"
                        )

                    elif command == "/status":
                        reply = (
                            "🟢 <b>ValueLens Systems Operational</b>\n"
                            "• Mode: <code>ACTIVE</code>"
                        )

                    elif command == "/scan":
                        # Full on-demand ticker scan — admin only
                        parts = text.split()
                        if len(parts) < 2:
                            reply = "❌ Usage: /scan TICKER (e.g. /scan AAPL)"
                        else:
                            scan_ticker = parts[1].upper().strip()
                            # Run scan in background thread — non-blocking
                            asyncio.create_task(
                                asyncio.to_thread(run_full_scan, scan_ticker, chat_id)
                            )
                            # No reply needed — scan_engine sends its own messages
                            reply = ""

                    if reply:
                        def _send_reply(c=chat_id, r=reply):
                            requests.post(send_url, json={"chat_id": c, "text": r, "parse_mode": "HTML"})
                        await asyncio.to_thread(_send_reply)

        except requests.exceptions.ReadTimeout:
            # Expected long-polling timeout — not an error
            await asyncio.sleep(1)
            continue

        except requests.exceptions.ConnectionError:
            # Network blip — brief backoff and retry
            await asyncio.sleep(10)
            continue

        except Exception as e:
            logger.error(f"Error in polling loop: {e}")
            await asyncio.sleep(5)


async def core_scheduler_loop():
    """Main chronological background lifecycle engine (UK Time Aligned).

    On startup or restart, automatically resumes from the next pending step
    in the daily cycle rather than waiting for 08:00 the following day.
    Post-midnight steps (01:00) are treated as belonging to the same cycle
    as the preceding evening and are scheduled for the next calendar day.
    """

    logger.info("=" * 60)
    logger.info("ValueLens Institutional Chronology Architecture initialized.")
    logger.info("=" * 60)

    async def _nightly_block():
        """Executes nightly scan and accuracy sweep as a single atomic step."""
        await asyncio.to_thread(execute_nightly_routine)
        await asyncio.to_thread(evaluate_historical_accuracy_loop)

    async def _insider_block():
        """Executes overnight insider tracking (01:00 AM cycle)."""
        await asyncio.to_thread(run_insider_tracking)

    # Ordered weekday steps: (hour, minute, log_label, async_factory)
    # Earnings sniper runs 3x/day (silent at 10:00 and 16:30 — DB only, no Telegram)
    # Insider tracking runs 2x/day (14:00 midday + 01:00 overnight)
    # Only insider buy alerts go to Telegram — earnings updates go to dashboard only
    WEEKDAY_STEPS = [
        (8,  0,  "08:00 AM — Morning Broadcast",               lambda: asyncio.to_thread(morning_broadcast)),
        (10, 0,  "10:00 AM — Earnings Sniper (silent)",        lambda: run_earnings_pipeline(silent=True)),
        (12, 30, "12:30 PM — Earnings Sniper",                 lambda: run_earnings_pipeline()),
        (14, 0,  "14:00 PM — Insider Tracking (midday)",       lambda: asyncio.to_thread(run_insider_tracking)),
        (16, 30, "16:30 PM — Earnings Sniper (post-market)",   lambda: run_earnings_pipeline(silent=True)),
        (22, 30, "22:30 PM — Nightly Deep Fundamental",        lambda: _nightly_block()),
        (1,  0,  "01:00 AM — Insider Tracking",                lambda: _insider_block()),
    ]

    while True:
        try:
            now = datetime.datetime.now()

            # --- SATURDAY: weekly recap at 09:00, then idle ---
            if now.weekday() == 5:
                await wait_until(9, 0)
                await asyncio.to_thread(generate_and_broadcast_weekly_recap)
                await asyncio.sleep(3600)
                continue

            # --- SUNDAY: no operations, sleep until Monday 08:00 ---
            if now.weekday() == 6:
                logger.info("Sunday detected — no scheduled operations. Sleeping until Monday 08:00.")
                await wait_until(8, 0)
                continue

            # --- SMART RESUME: build list of steps still in the future ---
            # Snapshot now once to avoid drift between multiple datetime.now() calls
            now_snap = datetime.datetime.now()

            def step_target_dt(h, m):
                """Returns target datetime for h:m relative to now_snap.
                Post-midnight steps (hour < 8) are placed on the next calendar day
                to preserve cycle order: 08:00 -> 12:30 -> 22:30 -> 01:00.
                """
                base = now_snap.replace(hour=h, minute=m, second=0, microsecond=0)
                if h < 8:
                    base += datetime.timedelta(days=1)
                return base

            future_steps = []
            for h, m, label, factory in WEEKDAY_STEPS:
                target = step_target_dt(h, m)
                if target > now_snap:
                    future_steps.append((target, label, factory))

            if not future_steps:
                # All steps for this cycle passed — wait for tomorrow's 08:00
                logger.info("All daily steps completed. Sleeping until tomorrow 08:00.")
                await wait_until(8, 0)
                continue

            # Execute each remaining step in chronological order
            future_steps.sort(key=lambda x: x[0])

            for target_dt, label, factory in future_steps:
                sleep_secs = (target_dt - datetime.datetime.now()).total_seconds()
                if sleep_secs > 0:
                    logger.info(
                        f"Next task scheduled for {target_dt.strftime('%Y-%m-%d %H:%M:%S')}. "
                        f"Sleeping {sleep_secs:.2f}s."
                    )
                    await asyncio.sleep(sleep_secs)
                logger.info(f"⏰ [{label}]")
                await factory()

            # Brief pause before restarting the outer loop
            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Scheduler core loop failure: {e}")
            await asyncio.sleep(60)


async def main():
    await asyncio.gather(
        core_scheduler_loop(),
        incoming_commands_polling_loop()
    )


if __name__ == "__main__":
    init_db()

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Hardware daemon power-down sequence completed.")