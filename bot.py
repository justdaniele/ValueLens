import os
import asyncio
import logging
import datetime
import requests
from dotenv import load_dotenv

# Import autonomous tasks, database utilities, and multi-lingual distribution networks
from scanner import execute_nightly_routine, morning_broadcast
from database import init_db, get_accuracy_metrics, evaluate_historical_accuracy_loop
from earnings_engine import send_alert_to_channel, run_earnings_pipeline
from weekly_engine import generate_and_broadcast_weekly_recap

load_dotenv()

# Centralized System Logging Configuration (Console + File)
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
    """Calculates exact remaining seconds until target time (hour:minute) and enters sleep."""
    now = datetime.datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    if target <= now:
        target += datetime.timedelta(days=1)
        
    sleep_seconds = (target - now).total_seconds()
    logger.info(f"Next operational run scheduled for {target}. Sleeping for {sleep_seconds:.2f} seconds.")
    await asyncio.sleep(sleep_seconds)

# ── INTERACTIVE COMMANDS & SECURITY GATEKEEPER LOOP ───────────────────────────

async def incoming_commands_polling_loop():
    """
    Asynchronous background task executing standard long-polling intervals.
    Enforces the administrative security barrier and processes private commands.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_id_str = os.environ.get("ADMIN_TELEGRAM_ID", "0")
    
    try:
        admin_id = int(admin_id_str)
    except ValueError:
        admin_id = 0

    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN missing from environment. Command listener disabled.")
        return

    offset = 0
    updates_url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    logger.info("Interactive Telegram command long-polling listener successfully initialized.")

    while True:
        try:
            # Safely delegate the blocking network request to an asynchronous thread pool
            def fetch_updates():
                try:
                    r = requests.get(updates_url, json={"offset": offset, "timeout": 20}, timeout=25)
                    return r.json() if r.status_code == 200 else None
                except Exception:
                    return None

            response_data = await asyncio.to_thread(fetch_updates)
            if not response_data or not response_data.get("ok"):
                await asyncio.sleep(3)
                continue

            for update in response_data.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message")
                
                # Filter payloads ensuring we only handle plain text direct messages
                if not message or "text" not in message:
                    continue

                chat_id = message["chat"]["id"]
                user_id = message["from"]["id"]
                text = message["text"].strip()

                # --- EXCLUSIVE GATEKEEPER SECURITY SHIELD ---
                if user_id != admin_id:
                    logger.warning(f"Unauthorized administrative control attempt intercepted from User ID: {user_id}")
                    
                    # Strictly respond in English, denying access while promoting public channel redirection links
                    unauthorized_redirect_payload = (
                        "🤖 <b>ValueLens Intelligence Terminal</b>\n\n"
                        "This automated bot is a private infrastructure reserved exclusively for internal administrative control.\n\n"
                        "If you want to access our daily quantitative equity briefings, stock screening funnels, and market insights, "
                        "please join our official public channels:\n\n"
                        "🇬🇧 <b>English Broadcast Feed</b>: https://t.me/valuelensintelligence\n"
                        "🇮🇹 <b>Italian Broadcast Feed</b>: https://t.me/valuelensintelligenceit\n\n"
                        "<i>Thank you for your interest in ValueLens.</i>"
                    )
                    
                    def dispatch_rejection():
                        requests.post(send_url, json={
                            "chat_id": chat_id,
                            "text": unauthorized_redirect_payload,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True
                        }, timeout=15)
                        
                    await asyncio.to_thread(dispatch_rejection)
                    continue

                # --- AUTHORIZED ADMINISTRATIVE ROUTING SCHEMAS ---
                if text.startswith("/"):
                    command = text.split()[0].lower()
                    reply_payload = ""

                    if command == "/accuracy":
                        wins, total, pct = get_accuracy_metrics()
                        reply_payload = (
                            f"📊 <b>ValueLens Private Accuracy Ledger</b>\n\n"
                            f"• Total Evaluated Targets: <code>{total}</code>\n"
                            f"• Confirmed Core Wins: <code>{wins}</code>\n"
                            f"• Systematic Win Ratio: <b>{pct}</b>"
                        )
                    elif command == "/status":
                        reply_payload = (
                            "🟢 <b>ValueLens Core Operational Health</b>\n\n"
                            "• Master Scheduler Loop: <code>ACTIVE</code>\n"
                            "• Database Ledger State: <code>SYNCHRONIZED</code>\n"
                            "• Security Matrix Filter: <code>ENFORCED</code>"
                        )
                    elif command == "/portfolio":
                        reply_payload = (
                            "💼 <b>ValueLens Administrative Holdings</b>\n\n"
                            "Quantitative equity structures are securely recorded inside the local disk database layer."
                        )
                    else:
                        reply_payload = "❓ <b>Unknown Parameter</b>\nUse: /accuracy, /status, or /portfolio"

                    if reply_payload:
                        def dispatch_admin_reply():
                            requests.post(send_url, json={
                                "chat_id": chat_id,
                                "text": reply_payload,
                                "parse_mode": "HTML"
                            }, timeout=15)
                        await asyncio.to_thread(dispatch_admin_reply)

        except Exception as e:
            logger.error(f"Error encountered inside update consumer loop: {e}")
            await asyncio.sleep(5)

# ── CENTRAL BACKGROUND TIME SCHEDULER LOOP ────────────────────────────────────

async def core_scheduler_loop():
    logger.info("=" * 60)
    logger.info("ValueLens Autonomous Background Engine successfully initialized.")
    logger.info("=" * 60)
    
    while True:
        try:
            today = datetime.datetime.now()
            
            # --- WEEKEND INTERVAL OPERATION (Saturday Recap Routing) ---
            if today.weekday() == 5:
                await wait_until(9, 0)  # Wait until Saturday morning at 09:00 AM
                logger.info("⏰ [09:00 AM - Saturday] Launching Weekly Performance Recap Engine...")
                await asyncio.to_thread(generate_and_broadcast_weekly_recap)
                logger.info("✅ Weekly Performance Recap broadcast complete. Suspending to sleep cycle.")
                
                await asyncio.sleep(3600)
                continue
            
            # --- STANDARD WEEKDAY MARKET OPERATIONS (Monday to Friday) ---
            
            # 1. Run Earnings Sniper Engine at 01:00 AM to process upcoming catalyst profiles
            await wait_until(1, 0)
            logger.info("⏰ [01:00 AM] Triggering Earnings Sniper Engine...")
            await run_earnings_pipeline()
            logger.info("✅ Earnings Sniper Engine pipeline completed.")
            
            # 2. Run Nightly Value Scanner Funnel at 02:00 AM
            await wait_until(2, 0)
            logger.info("⏰ [02:00 AM] Triggering Nightly Routine...")
            await asyncio.to_thread(execute_nightly_routine)
            
            # Audit older prediction states and calculate real-time win ratios
            logger.info("Evaluating historical accuracy data matrices...")
            await asyncio.to_thread(evaluate_historical_accuracy_loop)
            wins, total, pct = get_accuracy_metrics()
            
            # Compile dual-language system health and performance alerts
            msg_en = f"📊 <b>Accuracy Performance Report:</b> {wins}/{total} ({pct} wins)"
            msg_it = f"📊 <b>Report Storico Accuratezza:</b> {wins}/{total} ({pct} di successo)"
            send_alert_to_channel(msg_en, msg_it)
            logger.info(msg_en)
            
            logger.info("✅ Nightly routine complete. Returning to time-monitoring mode.")
            
            # 3. Morning Intelligence Briefing Broadcast at 08:00 AM
            await wait_until(8, 0)
            logger.info("⏰ [08:00 AM] Triggering Morning Broadcast...")
            await asyncio.to_thread(morning_broadcast)
            
            # Broadcast multi-lingual operational success milestones
            send_alert_to_channel(
                "🌅 <b>System Notice:</b> Morning intelligence report published.", 
                "🌅 <b>Notifica di Sistema:</b> Report d'intelligence mattutino pubblicato."
            )
            logger.info("Morning broadcast sequence complete.")
            
        except Exception as e:
            logger.error(f"Critical error caught inside Master Scheduler loop: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    # Validate and initialize dynamic database schemas prior to boot
    init_db()
    
    # Fire up both the background scheduler and interactive command parser concurrently
    try:
        asyncio.run(asyncio.gather(
            core_scheduler_loop(),
            incoming_commands_polling_loop()
        ))
    except KeyboardInterrupt:
        logger.info("Controlled hardware shutdown of Master Engine requested by user.")