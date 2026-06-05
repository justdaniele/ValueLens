import os
import asyncio
import logging
import datetime
from dotenv import load_dotenv

# Import autonomous tasks and database persistence
from scanner import execute_nightly_routine
from database import init_db, get_accuracy_metrics, evaluate_historical_accuracy_loop
from earnings_engine import send_alert_to_channel

load_dotenv()

# Centralized Logging Configuration (Console + File)
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
            # Schedule execution for 02:00 AM nightly
            await wait_until(2, 0)
            
            # Skip operational pipeline during weekends when markets are closed
            if datetime.datetime.now().weekday() >= 5:
                logger.info("Weekend detected. Skipping operational market jobs.")
                continue
                
            logger.info("⏰ [02:00 AM] Triggering Nightly Quantitative Funnel...")
            
            # Execute market scanner inside a separate asynchronous thread to avoid blocking the main loop
            await asyncio.to_thread(execute_nightly_routine)
            
            # Evaluate historical prediction accuracy and broadcast metrics
            logger.info("Evaluating historical accuracy...")
            await asyncio.to_thread(evaluate_historical_accuracy_loop)
            wins, total, pct = get_accuracy_metrics()
            msg = f"📊 Accuracy Report: {wins}/{total} ({pct})"
            send_alert_to_channel(msg)
            logger.info(msg)
            
            logger.info("✅ Nightly routine complete. Returning to time-monitoring mode.")
            
        except Exception as e:
            logger.error(f"Critical error caught inside Master Scheduler loop: {e}")
            await asyncio.sleep(60)  # Safety delay to prevent rapid infinite crash loops

if __name__ == "__main__":
    # Initialize SQLite schema if tables do not exist
    init_db()
    
    # Launch main infinite asynchronous scheduler
    try:
        asyncio.run(core_scheduler_loop())
    except KeyboardInterrupt:
        logger.info("Controlled shutdown of Master Engine requested by user.")
