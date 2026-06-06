import os
import logging
from database import get_weekly_summary_stats
from earnings_engine import send_alert_to_channel

# Configure standalone logger for tracking weekly operations
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] WeeklyEngine: %(message)s")
logger = logging.getLogger("WeeklyEngine")

def generate_and_broadcast_weekly_recap():
    """
    Compiles database metrics into dedicated English and Italian HTML briefs,
    broadcasting them asynchronously to target distribution channels.
    """
    logger.info("Initializing institutional Weekly Performance Recap pipeline...")
    
    # Extract calculated performance matrices from database storage layer
    stats = get_weekly_summary_stats()
    
    # --- DETAILED ENGLISH WEEKLY INTELLIGENCE BRIEF ---
    msg_en = (
        f"📊 <b>ValueLens Institutional Weekly Recap</b>\n"
        f"<i>Macro Portfolio Tracking & System Audit</i>\n\n"
        f"⚡ <b>Weekly Activity:</b>\n"
        f"• Earnings Sniper Triggers: <code>{stats['weekly_alerts']} assets</code>\n"
        f"• Top Performing Catalyst: <b>{stats['top_ticker']}</b>\n\n"
        f"🎯 <b>Global System Accuracy Audit:</b>\n"
        f"• Confirmed Wins: <code>{stats['global_wins']}/{stats['global_total']}</code>\n"
        f"• Hit Rate Percentage: <b>{stats['global_pct']}</b>\n\n"
        f"<i>Engine operating under nominal parameters. Database structures optimized for upcoming sessions.</i>"
    )
    
    # --- DETAILED ITALIAN WEEKLY INTELLIGENCE BRIEF ---
    msg_it = (
        f"📊 <b>ValueLens Report Performance Settimanale</b>\n"
        f"<i>Tracciamento Macro Portafoglio e Audit di Sistema</i>\n\n"
        f"⚡ <b>Attività della Settimana:</b>\n"
        f"• Alert Sniper Generati: <code>{stats['weekly_alerts']} titoli</code>\n"
        f"• Miglior Catalyst Tracciato: <b>{stats['top_ticker']}</b>\n\n"
        f"🎯 <b>Audit Accuratezza Globale di Sistema:</b>\n"
        f"• Previsioni Confermate: <code>{stats['global_wins']}/{stats['global_total']}</code>\n"
        f"• Percentuale di Successo: <b>{stats['global_pct']}</b>\n\n"
        f"<i>Il motore opera sotto parametri nominali. Strutture dati ottimizzate per la prossima settimana.</i>"
    )
    
    # Dispatch localized payloads across active pipeline infrastructure
    send_alert_to_channel(msg_en, msg_it)
    logger.info("Bilingual Weekly Performance Recap successfully broadcasted to routing nodes.")

if __name__ == "__main__":
    # Integration script testing execution block
    generate_and_broadcast_weekly_recap()