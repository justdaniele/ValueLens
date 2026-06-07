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

# Master daemon logging configuration (This acts as the root logger for all imports)
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
    """Calculates remaining seconds until target 24h time and enters async sleep."""
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    sleep_seconds = (target - now).total_seconds()
    logger.info(f"Next task scheduled for {target}. Sleeping {sleep_seconds:.2f}s.")
    await asyncio.sleep(sleep_seconds)

async def incoming_commands_polling_loop():
    """Asynchronous Telegram long-polling server handling administrative commands."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_id = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
    offset = 0
    updates_url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    logger.info("Interactive Telegram command long-polling listener successfully initialized.")

    while True:
        try:
            # Delegate blocking network request to async thread pool
            def fetch():
                r = requests.get(updates_url, json={"offset": offset, "timeout": 20}, timeout=25)
                return r.json() if r.status_code == 200 else None
                
            response_data = await asyncio.to_thread(fetch)
            if not response_data or not response_data.get("ok"):
                await asyncio.sleep(3)
                continue

            for update in response_data.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message")
                
                # Filter payloads ensuring we only handle valid direct texts
                if not message or "text" not in message: 
                    continue

                chat_id = message["chat"]["id"]
                user_id = message["from"]["id"]
                text = message["text"].strip()

                # --- EXCLUSIVE GATEKEEPER SECURITY SHIELD ---
                if user_id != admin_id:
                    logger.warning(f"Unauthorized administrative control attempt intercepted from User ID: {user_id}")
                    
                    # Strictly respond in English, denying access and redirecting to public channels
                    public_msg = (
                        "🤖 <b>ValueLens Intelligence Terminal</b>\n\n"
                        "This automated bot is a private infrastructure reserved exclusively for internal administrative control.\n\n"
                        "If you wish to access our daily equity briefings and market insights, please join our official public channels:\n\n"
                        "🇬🇧 <b>English Feed</b>: https://t.me/valuelensintelligence\n"
                        "🇮🇹 <b>Italian Feed</b>: https://t.me/valuelensintelligenceit\n\n"
                        "<i>Thank you for your interest in ValueLens.</i>"
                    )
                    await asyncio.to_thread(lambda: requests.post(send_url, json={"chat_id": chat_id, "text": public_msg, "parse_mode": "HTML"}))
                    continue

                # --- AUTHORIZED ADMINISTRATIVE ROUTING ---
                if text.startswith("/"):
                    command = text.split()[0].lower()
                    reply_payload = ""

                    if command == "/accuracy":
                        wins, total, pct = get_accuracy_metrics()
                        reply_payload = (
                            f"📊 <b>ValueLens Private Accuracy Ledger</b>\n\n"
                            f"• Confirmed Target Wins: <code>{wins}/{total}</code>\n"
                            f"• Global Hit Rate Ratio: <b>{pct}</b>"
                        )
                    elif command == "/status":
                        reply_payload = (
                            "🟢 <b>ValueLens Core Health Status</b>\n\n"
                            "• Master Execution Loop: <code>ACTIVE</code>\n"
                            "• Insider Monitoring Engine: <code>ARMED</code>\n"
                            "• Database Sync State: <code>NOMINAL</code>"
                        )
                    else:
                        reply_payload = "❓ <b>Unknown Parameter</b>\nAvailable: /accuracy, /status"

                    if reply_payload:
                        await asyncio.to_thread(lambda: requests.post(send_url, json={"chat_id": chat_id, "text": reply_payload, "parse_mode": "HTML"}))

        except Exception as e:
            logger.error(f"Error encountered inside update consumer loop: {e}")
            await asyncio.sleep(5)

async def core_scheduler_loop():
    """Main autonomous chronological scheduler for pipeline operations."""
    logger.info("=" * 60)
    logger.info("ValueLens Autonomous Background Engine successfully initialized.")
    logger.info("=" * 60)
    
    while True:
        try:
            today = datetime.datetime.now()
            
            # --- WEEKEND OPERATION (Saturday Recap) ---
            if today.weekday() == 5:
                await wait_until(9, 0)
                logger.info("⏰ [09:00 AM] Triggering Weekly Performance Recap...")
                await asyncio.to_thread(generate_and_broadcast_weekly_recap)
                await asyncio.sleep(3600)
                continue
            
            # --- WEEKDAY OPERATIONS (Monday to Friday) ---
            
            # 1. Earnings Catalyst Sniper (01:00 AM)
            await wait_until(1, 0)
            logger.info("⏰ [01:00 AM] Triggering Earnings Sniper Engine...")
            await run_earnings_pipeline()
            
            # 2. Nightly Fundamental Scanner & Accuracy Evaluation (02:00 AM)
            await wait_until(2, 0)
            logger.info("⏰ [02:00 AM] Triggering Nightly Routine...")
            await asyncio.to_thread(execute_nightly_routine)
            
            logger.info("Evaluating historical accuracy metrics...")
            await asyncio.to_thread(evaluate_historical_accuracy_loop)
            
            # 3. C-Suite Insider Tracking Update (03:00 AM)
            await wait_until(3, 0)
            logger.info("⏰ [03:00 AM] Triggering Insider Tracking Engine...")
            await asyncio.to_thread(run_insider_tracking)
            
            # 4. Morning Broadcast Execution (08:00 AM)
            await wait_until(8, 0)
            logger.info("⏰ [08:00 AM] Triggering Morning Broadcast...")
            await asyncio.to_thread(morning_broadcast)
            
            # Confirm completion via Telegram
            send_alert_to_channel(
                "🌅 <b>System Notice:</b> Morning operations successfully concluded.", 
                "🌅 <b>Notifica di Sistema:</b> Operazioni mattutine completate."
            )
            
        except Exception as e:
            logger.error(f"Scheduler core error: {e}")
            await asyncio.sleep(60) # Backoff to prevent cascade failures

if __name__ == "__main__":
    init_db()
    try:
        # Spin up concurrent asyncio event loops for both tracking and interaction
        asyncio.run(asyncio.gather(core_scheduler_loop(), incoming_commands_polling_loop()))
    except KeyboardInterrupt:
        logger.info("Controlled hardware shutdown executed by the administrator.")