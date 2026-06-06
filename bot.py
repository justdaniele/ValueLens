import os
import asyncio
import logging
import datetime
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

async def core_scheduler_loop():
    logger.info("=" * 60)
    logger.info("ValueLens Autonomous Background Engine successfully initialized.")
    logger.info("=" * 60)
    
    while True:
        try:
            # Capture real-time hardware calendar state
            today = datetime.datetime.now()
            
            # --- WEEKEND INTERVAL OPERATION (Saturday Recap Routing) ---
            if today.weekday() == 5:
                await wait_until(9, 0)  # Wait until Saturday morning at 09:00 AM
                logger.info("⏰ [09:00 AM - Saturday] Launching Weekly Performance Recap Engine...")
                await asyncio.to_thread(generate_and_broadcast_weekly_recap)
                logger.info("✅ Weekly Performance Recap broadcast complete. Suspending to sleep cycle.")
                
                # Cooldown period buffer to avoid rapid double-triggering inside the execution minute
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
            await asyncio.sleep(60)  # Standard circuit-breaker safety delay to prevent loop panics

if __name__ == "__main__":
    # Validate and initialize dynamic database schemas
    init_db()
    
    # Initialize main infinite background core engine loop
    try:
        asyncio.run(core_scheduler_loop())
    except KeyboardInterrupt:
        logger.info("Controlled hardware shutdown of Master Engine requested by user.")