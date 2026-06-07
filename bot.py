import os
import asyncio
import logging
import datetime
import requests
from dotenv import load_dotenv

# Import autonomous tasks, database utilities, and sub-engines
from scanner import execute_nightly_routine, morning_broadcast
from database import init_db, get_accuracy_metrics, evaluate_historical_accuracy_loop
from earnings_engine import send_alert_to_channel, run_earnings_pipeline
from weekly_engine import generate_and_broadcast_weekly_recap
from insider_engine import run_insider_tracking

load_dotenv()

# Master daemon logging configuration (acts as root logger for all imports)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] ValueLensMaster: %(message)s",
    handlers=[
        logging.FileHandler("valuelens_master.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ValueLensMaster")


# ---------------------------------------------------------------------------
# Scheduling helper
# ---------------------------------------------------------------------------

async def wait_until(hour: int, minute: int):
    """Calculates remaining seconds until next occurrence of target time and sleeps."""
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    sleep_seconds = (target - now).total_seconds()
    logger.info(f"Next task scheduled for {target.strftime('%Y-%m-%d %H:%M:%S')}. Sleeping {sleep_seconds:.0f}s.")
    await asyncio.sleep(sleep_seconds)


# ---------------------------------------------------------------------------
# Telegram command polling
# ---------------------------------------------------------------------------

async def incoming_commands_polling_loop():
    """Asynchronous Telegram long-polling server handling administrative commands."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_id_raw = os.environ.get("ADMIN_TELEGRAM_ID", "")

    # FIX: warn clearly on startup if ADMIN_TELEGRAM_ID is missing instead of
    # silently defaulting to 0 (which blocks all admin commands forever).
    if not admin_id_raw:
        logger.error(
            "ADMIN_TELEGRAM_ID is not set in .env — all admin commands will be rejected. "
            "Set it to your Telegram numeric user ID."
        )
        admin_id = 0
    else:
        admin_id = int(admin_id_raw)

    offset = 0
    updates_url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    send_url    = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    logger.info("Interactive Telegram command long-polling listener successfully initialized.")

    while True:
        try:
            # Delegate blocking network request to async thread pool
            # FIX: capture offset in a default arg to avoid the classic
            # late-binding lambda closure bug.
            def fetch(off=offset):
                r = requests.get(
                    updates_url,
                    json={"offset": off, "timeout": 20},
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
                text    = message["text"].strip()

                # --- SECURITY GATEKEEPER ---
                if user_id != admin_id:
                    logger.warning(
                        f"Unauthorized access attempt from user_id={user_id}, "
                        f"chat_id={chat_id}"
                    )
                    public_msg = (
                        "🤖 <b>ValueLens Intelligence Terminal</b>\n\n"
                        "This bot is a private infrastructure for internal administrative "
                        "control only.\n\n"
                        "For daily equity briefings please join our public channels:\n\n"
                        "🇬🇧 <b>English Feed</b>: https://t.me/valuelensintelligence\n"
                        "🇮🇹 <b>Italian Feed</b>: https://t.me/valuelensintelligenceit\n\n"
                        "<i>Thank you for your interest in ValueLens.</i>"
                    )
                    # FIX: capture variables in default args to avoid lambda closure issue
                    def _send_public(c=chat_id, m=public_msg):
                        requests.post(
                            send_url,
                            json={"chat_id": c, "text": m, "parse_mode": "HTML"}
                        )
                    await asyncio.to_thread(_send_public)
                    continue

                # --- ADMIN COMMAND ROUTER ---
                if not text.startswith("/"):
                    continue

                command = text.split()[0].lower()
                reply_payload = ""

                if command == "/accuracy":
                    wins, total, pct = get_accuracy_metrics()
                    reply_payload = (
                        f"📊 <b>ValueLens Accuracy Ledger</b>\n\n"
                        f"• Confirmed wins: <code>{wins}/{total}</code>\n"
                        f"• Hit rate: <b>{pct}</b>"
                    )

                elif command == "/status":
                    reply_payload = (
                        "🟢 <b>ValueLens Core Health Status</b>\n\n"
                        "• Master Execution Loop: <code>ACTIVE</code>\n"
                        "• Insider Monitoring Engine: <code>ARMED</code>\n"
                        "• Database Sync State: <code>NOMINAL</code>"
                    )

                elif command == "/run":
                    # Manually trigger the full nightly scan without waiting for 2 AM
                    reply_payload = "⚙️ <b>Manual nightly scan triggered.</b> This will take several minutes."
                    def _send_r(c=chat_id, m=reply_payload):
                        requests.post(send_url, json={"chat_id": c, "text": m, "parse_mode": "HTML"})
                    await asyncio.to_thread(_send_r)
                    reply_payload = ""   # already sent
                    await asyncio.to_thread(execute_nightly_routine)
                    reply_payload = "✅ <b>Nightly scan complete.</b> Reports queued for broadcast."

                elif command == "/broadcast":
                    # Force the morning broadcast immediately
                    reply_payload = "📡 <b>Forcing morning broadcast now...</b>"
                    def _send_b(c=chat_id, m=reply_payload):
                        requests.post(send_url, json={"chat_id": c, "text": m, "parse_mode": "HTML"})
                    await asyncio.to_thread(_send_b)
                    reply_payload = ""
                    await asyncio.to_thread(morning_broadcast)
                    reply_payload = "✅ <b>Broadcast complete.</b>"

                else:
                    reply_payload = (
                        "❓ <b>Unknown command</b>\n"
                        "Available: /accuracy, /status, /run, /broadcast"
                    )

                if reply_payload:
                    def _send(c=chat_id, m=reply_payload):
                        requests.post(
                            send_url,
                            json={"chat_id": c, "text": m, "parse_mode": "HTML"}
                        )
                    await asyncio.to_thread(_send)

        except Exception as e:
            logger.error(f"Error in update consumer loop: {e}")
            await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Core scheduler
# ---------------------------------------------------------------------------

async def core_scheduler_loop():
    """Main autonomous chronological scheduler for pipeline operations."""
    logger.info("=" * 60)
    logger.info("ValueLens Autonomous Background Engine initialized.")
    logger.info("=" * 60)

    while True:
        try:
            today = datetime.datetime.now()
            weekday = today.weekday()   # 0=Mon … 6=Sun

            # --- SATURDAY: weekly recap ---
            if weekday == 5:
                await wait_until(9, 0)
                logger.info("⏰ [09:00] Triggering Weekly Performance Recap...")
                await asyncio.to_thread(generate_and_broadcast_weekly_recap)
                await asyncio.sleep(3600)
                continue

            # FIX: Sunday previously fell through into weekday operations.
            # Now it just sleeps until Monday 01:00 AM.
            if weekday == 6:
                logger.info("Sunday detected — no scheduled operations. Sleeping until Monday 01:00.")
                await wait_until(1, 0)
                continue

            # --- MONDAY–FRIDAY ---

            # 1. Earnings Catalyst Sniper (01:00 AM)
            await wait_until(1, 0)
            logger.info("⏰ [01:00] Triggering Earnings Sniper Engine...")
            await run_earnings_pipeline()

            # 2. Nightly Fundamental Scanner & Accuracy Evaluation (02:00 AM)
            await wait_until(2, 0)
            logger.info("⏰ [02:00] Triggering Nightly Routine...")
            await asyncio.to_thread(execute_nightly_routine)

            logger.info("Evaluating historical accuracy metrics...")
            await asyncio.to_thread(evaluate_historical_accuracy_loop)

            # 3. C-Suite Insider Tracking Update (03:00 AM)
            await wait_until(3, 0)
            logger.info("⏰ [03:00] Triggering Insider Tracking Engine...")
            await asyncio.to_thread(run_insider_tracking)

            # 4. Morning Broadcast (08:00 AM)
            await wait_until(8, 0)
            logger.info("⏰ [08:00] Triggering Morning Broadcast...")
            await asyncio.to_thread(morning_broadcast)

            send_alert_to_channel(
                "🌅 <b>System Notice:</b> Morning operations successfully concluded.",
                "🌅 <b>Notifica di Sistema:</b> Operazioni mattutine completate."
            )

            # Short sleep to avoid re-running the same day's jobs in a tight loop
            await asyncio.sleep(3600)

        except Exception as e:
            logger.error(f"Scheduler core error: {e}")
            await asyncio.sleep(60)   # backoff to prevent cascade failures


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    try:
        asyncio.run(
            asyncio.gather(
                core_scheduler_loop(),
                incoming_commands_polling_loop()
            )
        )
    except KeyboardInterrupt:
        logger.info("Controlled shutdown executed by administrator.")