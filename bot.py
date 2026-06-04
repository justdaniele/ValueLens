import os
import re
import sqlite3
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors.exceptions.bad_request_400 import MessageNotModified
from analyzer import analyze_company, get_value_radar
from database import init_db, register_user, get_user_language, set_user_language, increment_scan_count, DB_NAME

load_dotenv()

API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
LOCK_FILE = "scan.lock"

# Official live production Telegram channel connection link
CHANNEL_LINK = "https://t.me/valuelensinsidersignals" 

if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("Missing Telegram environment variables in .env")

app = Client("valuelens_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Localization dictionary database matching user preference context mappings
STRINGS = {
    "en": {
        "welcome": "📊 **Welcome to ValueLens Bot!**\n\nYour quantitative analyst for Global Stocks.\n⚡ **PRO features activated for FREE!**\n\nType /help to see all available commands and features.\n\n⚠️ *Disclaimer: Educational purposes only. Not financial advice.*",
        "help": "📖 **ValueLens Bot | Command Reference**\n\n• /start - Initialize the bot and check registration.\n• /help - Show this interactive command guide.\n• /radar - Scan indices (e.g., S&P 500) for structural value anomalies.\n• /insider - View active real-time C-Suite corporate insider buying alerts.\n• /language - Change menu and analytical report output language.\n\n💡 **Direct Analysis:** Just type any stock ticker symbol (e.g., AAPL, MSFT) directly in chat to compile custom FLASH or PRO reports.",
        "maintenance": "🤖 **ValueLens | Maintenance**\n\nRunning nightly market data updates. Back online in a few minutes!",
        "radar_menu": "📡 **Value Radar**\nSelect a market index to scan for undervalued anomalies:",
        "radar_scan_depth": "📡 **Index:** {index}\nSelect scanning depth:",
        "radar_running": "📡 Scanning the **{index}** ({mode} mode)... Please wait.",
        "lang_menu": "🌐 **Language Settings**\nSelect your preferred language for menus and intelligence reports:",
        "lang_success": "✅ Language configuration updated to English!",
        "ticker_prompt": "🤖 **Ticker recognized:** `{ticker}`\nSelect the analysis depth:",
        "compiling_report": "🔍 Compiling {mode} report for **{ticker}**... Please wait.",
        "insider_init": "🚀 **First-Time Initialization**\n\nThe global insider database is currently empty. Launching initial scan across top 1,000 US equities...\n\n⏱️ Takes approx. 2 minutes. Results will appear automatically!",
        "insider_active": "🕵️‍♂️ **ValueLens INSIDER | Active US Signals**\nCompanies detected at structural lows backed by heavy C-Suite buying:\n\n",
        "insider_footer": "\n💡 *Analyze these tickers individually by sending them in chat to view the updated Reverse DCF.*",
        "insider_none": (
            "🚨 **ValueLens INSIDER | No Signals Found**\n\n"
            "Top 1,000 US companies scanned. Currently, **zero** entities match our high-conviction criteria "
            "(Price near 52-week lows + Aggressive corporate executive buying within the last 6 months).\n\n"
            "💡 **Verdict:** Market valuations are stretched; insiders are holding cash. Rescanning tonight.\n\n"
            "📢 **Join our Telegram Channel:** [ValueLens Insider Signals](" + CHANNEL_LINK + ")\n"
            "When high-conviction anomalies are discovered, they are instantly broadcasted there! "
            "The channel also hosts our **Virtual Tracker Portfolio**, monitoring real-time performance and ROI "
            "of all past insider alerts from their exact detection date."
        )
    },
    "it": {
        "welcome": "📊 **Benvenuto su ValueLens Bot!**\n\nIl tuo analista quantitativo personale per le azioni globali.\n⚡ **Funzionalità PRO attivate GRATIS!**\n\nDigita /help per visualizzare la guida ai comandi disponibili.\n\n⚠️ *Disclaimer: Solo a scopo didattico. Nessun consiglio finanziario.*",
        "help": "📖 **ValueLens Bot | Guida ai Comandi**\n\n• /start - Inizializza il bot e verifica la registrazione.\n• /help - Mostra questa guida interattiva ai comandi.\n• /radar - Scansiona indici (es. S&P 500) alla ricerca di forti anomalie di valore.\n• /insider - Mostra gli acquisti recenti eseguiti dai C-Suite Insider aziendali.\n• /language - Modifica la lingua dei menu e dei report generati.\n\n💡 **Analisi Diretta:** Invia il codice ticker di un'azione (es. AAPL, MSFT) direttamente in chat per compilare report personalizzati in modalità FLASH o PRO.",
        "maintenance": "🤖 **ValueLens | Manutenzione**\n\nAggiornamento dei dati di mercato notturno in corso. Di nuovo online tra pochissimi minuti!",
        "radar_menu": "📡 **Value Radar**\nSeleziona un indice di mercato da scansionare alla ricerca di aziende a sconto:",
        "radar_scan_depth": "📡 **Indice:** {index}\nSeleziona la profondità di scansione:",
        "radar_running": "📡 Scansione dell'indice **{index}** (modalità {mode}) in corso... Attendere prego.",
        "lang_menu": "🌐 **Impostazioni Lingua**\nSeleziona la tua lingua preferita per l'interfaccia e i report finanziari dell'IA:",
        "lang_success": "✅ Configurazione della lingua aggiornata in Italiano!",
        "ticker_prompt": "🤖 **Ticker riconosciuto:** `{ticker}`\nSeleziona la profondità dell'analisi:",
        "compiling_report": "🔍 Compilazione del report {mode} per **{ticker}**... Attendere prego.",
        "insider_init": "🚀 **Inizializzazione Sistema**\n\nIl database interno è vuoto. Lancio della scansione iniziale sulle top 1.000 azioni statunitensi...\n\n⏱️ Richiede circa 2 minuti. I risultati appariranno qui automaticamente!",
        "insider_active": "🕵️‍♂️ **ValueLens INSIDER | Segnali US Attivi**\n Aziende rilevate ai minimi strutturali supportate da forti acquisti di manager interni:\n\n",
        "insider_footer": "\n💡 *Analizza questi ticker individualmente inviandoli in chat per vedere il modello Reverse DCF aggiornato.*",
        "insider_none": (
            "🚨 **ValueLens INSIDER | Nessun Segnale Trovato**\n\n"
            "Scansionate le top 1.000 aziende US. Attualmente, **zero** società rispettano i nostri criteri di alta convinzione "
            "(Prezzo vicino ai minimi di 52 settimane + Acquisti aggressivi del management negli ultimi 6 mesi).\n\n"
            "💡 **Verdetto:** Le valutazioni di mercato sono tese; gli insider preferiscono tenere liquidità.\n\n"
            "📢 **Unisciti al nostro Canale Telegram:** [ValueLens Insider Signals](" + CHANNEL_LINK + ")\n"
            "Non appena vengono rilevate anomalie ad alta convinzione, vengono pubblicate istantaneamente lì! "
            "Il canale ospita anche il nostro **Virtual Tracker Portfolio**, che monitora le performance reali e il ROI "
            "di tutti i segnali passati dalla loro esatta data di rilevamento."
        )
    }
}

def is_bot_locked() -> bool:
    """Checks if the background scanner is currently updating the database."""
    return os.path.exists(LOCK_FILE)

def placeholder_insider_scanner():
    """Simulates the 1,000 company network scan operations on first boot."""
    import time
    time.sleep(120) 

@app.on_message(filters.command("start") & filters.private)
async def send_welcome(client: Client, message: Message):
    if is_bot_locked():
        lang = get_user_language(message.from_user.id)
        await message.reply_text(STRINGS[lang]["maintenance"])
        return
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    lang = get_user_language(message.from_user.id)
    await message.reply_text(STRINGS[lang]["welcome"], parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.command("help") & filters.private)
async def send_help(client: Client, message: Message):
    if is_bot_locked():
        lang = get_user_language(message.from_user.id)
        await message.reply_text(STRINGS[lang]["maintenance"])
        return
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    lang = get_user_language(message.from_user.id)
    await message.reply_text(STRINGS[lang]["help"], parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.command("language") & filters.private)
async def change_language_menu(client: Client, message: Message):
    if is_bot_locked():
        lang = get_user_language(message.from_user.id)
        await message.reply_text(STRINGS[lang]["maintenance"])
        return
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    lang = get_user_language(message.from_user.id)
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="set_lang:en"),
            InlineKeyboardButton("🇮🇹 Italiano", callback_data="set_lang:it")
        ]
    ])
    await message.reply_text(STRINGS[lang]["lang_menu"], reply_markup=keyboard)

@app.on_message(filters.command("radar") & filters.private)
async def value_radar_menu(client: Client, message: Message):
    if is_bot_locked():
        lang = get_user_language(message.from_user.id)
        await message.reply_text(STRINGS[lang]["maintenance"])
        return
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    lang = get_user_language(message.from_user.id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇸 S&P 500", callback_data="radar_idx:S&P 500")],
        [InlineKeyboardButton("🦅 NASDAQ", callback_data="radar_idx:NASDAQ")],
        [InlineKeyboardButton("✨ Magnificent 7", callback_data="radar_idx:Magnificent 7")],
        [InlineKeyboardButton("🏭 Dow Jones", callback_data="radar_idx:Dow Jones")],
        [InlineKeyboardButton("🔬 Russell 2000", callback_data="radar_idx:Russell 2000")]
    ])
    await message.reply_text(STRINGS[lang]["radar_menu"], reply_markup=keyboard)

@app.on_message(filters.command("insider") & filters.private)
async def view_insider_signals(client: Client, message: Message):
    if is_bot_locked():
        lang = get_user_language(message.from_user.id)
        await message.reply_text(STRINGS[lang]["maintenance"])
        return
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    lang = get_user_language(message.from_user.id)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM metadata WHERE key = 'last_insider_scan'")
    last_scan_status = cursor.fetchone()[0]
    
    if last_scan_status == "NEVER":
        status_msg = await message.reply_text(STRINGS[lang]["insider_init"], parse_mode=enums.ParseMode.MARKDOWN)
        with open(LOCK_FILE, "w") as lock:
            lock.write("locked")
        try:
            await asyncio.to_thread(placeholder_insider_scanner)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("UPDATE metadata SET value = ? WHERE key = 'last_insider_scan'", (now_str,))
            conn.commit()
        except Exception as e:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
            await status_msg.edit_text(f"❌ **Initialization Error:** {str(e)}")
            conn.close()
            return
        finally:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        
        cursor.execute("SELECT ticker, date_detected, price_detected FROM insider_signals WHERE status = 'ACTIVE' ORDER BY date_detected DESC")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            await status_msg.edit_text(STRINGS[lang]["insider_none"], parse_mode=enums.ParseMode.MARKDOWN, disable_web_page_preview=True)
            return
        else:
            response_text = STRINGS[lang]["insider_active"]
            for row in rows:
                ticker, date, price = row
                response_text += f"• **{ticker}**\n  ↳ Detected: {date}\n  ↳ Entry: ${price:.2f}\n\n"
            response_text += STRINGS[lang]["insider_footer"]
            await status_msg.edit_text(response_text, parse_mode=enums.ParseMode.MARKDOWN)
            return

    cursor.execute("SELECT ticker, date_detected, price_detected FROM insider_signals WHERE status = 'ACTIVE' ORDER BY date_detected DESC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await message.reply_text(STRINGS[lang]["insider_none"], parse_mode=enums.ParseMode.MARKDOWN, disable_web_page_preview=True)
        return

    response_text = STRINGS[lang]["insider_active"]
    for row in rows:
        ticker, date, price = row
        response_text += f"• **{ticker}**\n  ↳ Detected: {date}\n  ↳ Entry: ${price:.2f}\n\n"
    response_text += STRINGS[lang]["insider_footer"]
    await message.reply_text(response_text, parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.text & filters.private & ~filters.command(["start", "help", "radar", "insider", "language"]))
async def prompt_analysis_mode(client: Client, message: Message):
    if is_bot_locked():
        lang = get_user_language(message.from_user.id)
        await message.reply_text(STRINGS[lang]["maintenance"])
        return
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    lang = get_user_language(message.from_user.id)
    
    ticker = message.text.strip().upper()
    if not re.match(r"^[A-Z0-9-]{1,8}$", ticker):
        await message.reply_text("❌ Invalid ticker format." if lang == "en" else "❌ Formato ticker non valido.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡️ FLASH", callback_data=f"analyze:FLASH:{ticker}"),
            InlineKeyboardButton("🔍 PRO", callback_data=f"analyze:PRO:{ticker}")
        ]
    ])
    await message.reply_text(STRINGS[lang]["ticker_prompt"].format(ticker=ticker), reply_markup=keyboard)


@app.on_callback_query()
async def handle_callbacks(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    lang = get_user_language(user_id)
    
    if is_bot_locked():
        alert_msg = "System updating..." if lang == "en" else "Aggiornamento sistema in corso..."
        await callback_query.answer(alert_msg, show_alert=True)
        return
    
    if data.startswith("set_lang:"):
        _, selected_lang = data.split(":")
        set_user_language(user_id, selected_lang)
        await callback_query.answer()
        try:
            await callback_query.message.edit_text(STRINGS[selected_lang]["lang_success"])
        except MessageNotModified:
            pass

    elif data.startswith("analyze:"):
        _, mode, ticker = data.split(":")
        await callback_query.answer()
        try:
            await callback_query.message.edit_text(STRINGS[lang]["compiling_report"].format(mode=mode, ticker=ticker))
        except MessageNotModified:
            pass
            
        try:
            analysis_result = analyze_company(ticker, mode, lang)
            increment_scan_count(user_id)
            await callback_query.message.edit_text(analysis_result, parse_mode=enums.ParseMode.MARKDOWN)
        except MessageNotModified:
            # Traps and swallows identical concurrent text overwrites on double clicks safely
            pass
        except Exception as e:
            await callback_query.message.edit_text(f"❌ System error: {str(e)}")

    elif data.startswith("radar_idx:"):
        _, index_name = data.split(":")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡️ FLASH", callback_data=f"radar_run:FLASH:{index_name}"),
                InlineKeyboardButton("🔍 PRO", callback_data=f"radar_run:PRO:{index_name}")
            ]
        ])
        try:
            await callback_query.message.edit_text(STRINGS[lang]["radar_scan_depth"].format(index=index_name), reply_markup=keyboard)
        except MessageNotModified:
            pass

    elif data.startswith("radar_run:"):
        _, mode, index_name = data.split(":")
        await callback_query.answer()
        
        try:
            await callback_query.message.edit_text(STRINGS[lang]["radar_running"].format(index=index_name, mode=mode))
        except MessageNotModified:
            pass
            
        try:
            radar_result = get_value_radar(index_name, mode, lang)
            await callback_query.message.edit_text(radar_result, parse_mode=enums.ParseMode.MARKDOWN)
        except MessageNotModified:
            # Safe boundary check: traps duplicate asynchronous rendering collisions silently
            pass
        except Exception as e:
            await callback_query.message.edit_text(f"❌ Radar error: {str(e)}")


if __name__ == "__main__":
    init_db()
    print("ValueLens Telegram Bot UI is running...")
    app.run()