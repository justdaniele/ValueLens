import logging
import sys
from scanner import execute_nightly_routine, morning_broadcast

# Configure standalone console logging for this one-time live test
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] LiveTest: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LiveTest")


def run_one_time_live_test():
    logger.info("=" * 60)
    logger.info("LAUNCHING VALUELENS ONE-TIME LIVE SCANNER TEST")   # FIX: was "VALUELESS"
    logger.info("=" * 60)

    # Step 1: Run the full nightly scanning routine over the S&P 500 universe
    logger.info("Phase 1: Executing live market quantitative funnel...")
    execute_nightly_routine()
    logger.info("Live market scanner execution complete.")

    # Step 2: Immediately trigger the broadcast to push reports to Telegram
    logger.info("Phase 2: Forcing immediate broadcast to Telegram channels...")
    morning_broadcast()

    logger.info("=" * 60)
    logger.info("LIVE RUN COMPLETED. CHECK YOUR TELEGRAM CHANNELS.")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_one_time_live_test()