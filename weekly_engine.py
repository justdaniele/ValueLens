import logging
from database import get_weekly_summary_stats
from earnings_engine import send_alert_to_channel

# Use the logger directly — global logging config is handled exclusively by bot.py
logger = logging.getLogger("WeeklyEngine")


def generate_and_broadcast_weekly_recap():
    """
    Compiles database metrics into dedicated English and Italian HTML briefs
    and broadcasts them to both distribution channels.

    FIX: duplicate function definition removed. The file previously defined this
    function twice — Python silently kept only the second one, making the first
    dead code. Now there is a single authoritative definition.
    """
    logger.info("Initializing institutional Weekly Performance Recap pipeline...")

    # Extract calculated performance matrices from database storage layer
    stats = get_weekly_summary_stats()

    # --- ENGLISH WEEKLY BRIEF ---
    msg_en = (
        f"📊 <b>ValueLens Institutional Weekly Recap</b>\n"
        f"<i>Macro Portfolio Tracking & System Audit</i>\n\n"
        f"⚡ <b>Weekly Activity:</b>\n"
        f"• Earnings Sniper Triggers: <code>{stats['weekly_alerts']} assets</code>\n"
        f"• Top Performing Catalyst: <b>{stats['top_ticker']}</b>\n\n"
        f"🎯 <b>Global System Accuracy Audit:</b>\n"
        f"• Confirmed Wins: <code>{stats['global_wins']}/{stats['global_total']}</code>\n"
        f"• Hit Rate: <b>{stats['global_pct']}</b>\n\n"
        f"<i>Engine operating under nominal parameters. "
        f"Database structures optimized for upcoming sessions.</i>"
    )

    # --- ITALIAN WEEKLY BRIEF ---
    msg_it = (
        f"📊 <b>ValueLens Report Performance Settimanale</b>\n"
        f"<i>Tracciamento Macro Portafoglio e Audit di Sistema</i>\n\n"
        f"⚡ <b>Attività della Settimana:</b>\n"
        f"• Alert Sniper Generati: <code>{stats['weekly_alerts']} titoli</code>\n"
        f"• Miglior Catalyst Tracciato: <b>{stats['top_ticker']}</b>\n\n"
        f"🎯 <b>Audit Accuratezza Globale di Sistema:</b>\n"
        f"• Previsioni Confermate: <code>{stats['global_wins']}/{stats['global_total']}</code>\n"
        f"• Percentuale di Successo: <b>{stats['global_pct']}</b>\n\n"
        f"<i>Il motore opera sotto parametri nominali. "
        f"Strutture dati ottimizzate per la prossima settimana.</i>"
    )

    send_alert_to_channel(msg_en, msg_it)
    logger.info("Bilingual Weekly Performance Recap successfully broadcasted.")


if __name__ == "__main__":
    generate_and_broadcast_weekly_recap()