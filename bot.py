import os
import re
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta
from scanner import execute_nightly_routine
from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors.exceptions.bad_request_400 import MessageNotModified
from analyzer import analyze_company, get_value_radar
import prompts  
from database import (
    init_db, 
    register_user, 
    get_user_language, 
    set_user_language, 
    increment_scan_count, 
    evaluate_historical_accuracy_loop, 
    DB_NAME
)

load_dotenv()

API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
LOCK_FILE = "scan.lock"
CHANNEL_LINK = "https://t.me/valuelensinsidersignals" 

if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("Missing Telegram environment variables in .env")

app = Client("valuelens_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
logger = logging.getLogger("ValueLensBot")

def is_bot_locked() -> bool:
    return os.path.exists(LOCK_FILE)

def placeholder_insider_scanner():
    import time
    time.sleep(120) 

async def wait_until(hour: int, minute: int):
    """Sleeps until the specified absolute hour and minute."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    if target <= now:
        target += timedelta(days=1)
        
    sleep_seconds = (target - now).total_seconds()
    await asyncio.sleep(sleep_seconds)

async def background_scheduler(client: Client):
    scheduler_logger = logging.getLogger("ValueLensScheduler")
    scheduler_logger.info("Persistent background engine execution thread started.")
    
    try:
        scheduler_logger.info("Executing immediate startup historical accuracy validation...")
        await asyncio.to_thread(evaluate_historical_accuracy_loop)
    except Exception as e:
        scheduler_logger.error(f"Initial accuracy check failed: {e}")

    while True:
        try:
            scheduler_logger.info("Scheduler entering deep sleep until 02:00 AM.")
            await wait_until(2, 0)
            
            scheduler_logger.info("Clock struck 02:00 AM. Launching nightly quantitative funnel...")
            await asyncio.to_thread(execute_nightly_routine)
            
            scheduler_logger.info("Nightly routine complete. Triggering daily historical accuracy validation...")
            await asyncio.to_thread(evaluate_historical_accuracy_loop)
            
        except Exception as e:
            scheduler_logger.error(f"Error detected in scheduler task execution: {e}")
            await asyncio.sleep(60)

# --- MIDDLEWARE UTILITIES ---
def get_ui_text(user_id: int, key: str) -> str:
    """Helper to safely fetch localized strings with dynamic fallback."""
    lang = get_user_language(user_id)
    return prompts.UI_STRINGS.get(lang, prompts.UI_STRINGS["en"]).get(key, "")

@app.on_message(filters.command("start") & filters.private)
async def send_welcome(client: Client, message: Message):
    uid = message.from_user.id
    if is_bot_locked():
        await message.reply_text(get_ui_text(uid, "maintenance"))
        return
    register_user(uid, message.from_user.username or "Anonymous")
    await message.reply_text(get_ui_text(uid, "welcome"), parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.command("help") & filters.private)
async def send_help(client: Client, message: Message):
    uid = message.from_user.id
    if is_bot_locked():
        await message.reply_text(get_ui_text(uid, "maintenance"))
        return
    register_user(uid, message.from_user.username or "Anonymous")
    await message.reply_text(get_ui_text(uid, "help"), parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.command("language") & filters.private)
async def change_language_menu(client: Client, message: Message):
    uid = message.from_user.id
    if is_bot_locked():
        await message.reply_text(get_ui_text(uid, "maintenance"))
        return
    register_user(uid, message.from_user.username or "Anonymous")
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English", callback_data="set_lang:en"),
         InlineKeyboardButton("🇮🇹 Italiano", callback_data="set_lang:it")]
    ])
    await message.reply_text(get_ui_text(uid, "lang_menu"), reply_markup=keyboard)

@app.on_message(filters.command("radar") & filters.private)
async def value_radar_menu(client: Client, message: Message):
    uid = message.from_user.id
    if is_bot_locked():
        await message.reply_text(get_ui_text(uid, "maintenance"))
        return
    register_user(uid, message.from_user.username or "Anonymous")
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇸 S&P 500", callback_data="radar_idx:S&P 500")],
        [InlineKeyboardButton("🦅 NASDAQ", callback_data="radar_idx:NASDAQ")],
        [InlineKeyboardButton("✨ Magnificent 7", callback_data="radar_idx:Magnificent 7")],
        [InlineKeyboardButton("🏭 Dow Jones", callback_data="radar_idx:Dow Jones")],
        [InlineKeyboardButton("🔬 Russell 2000", callback_data="radar_idx:Russell 2000")]
    ])
    await message.reply_text(get_ui_text(uid, "radar_menu"), reply_markup=keyboard)

@app.on_message(filters.command("insider") & filters.private)
async def view_insider_signals(client: Client, message: Message):
    uid = message.from_user.id
    if is_bot_locked():
        await message.reply_text(get_ui_text(uid, "maintenance"))
        return
    register_user(uid, message.from_user.username or "Anonymous")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM metadata WHERE key = 'last_insider_scan'")
    last_scan_status = cursor.fetchone()[0]
    
    if last_scan_status == "NEVER":
        status_msg = await message.reply_text(get_ui_text(uid, "insider_init"), parse_mode=enums.ParseMode.MARKDOWN)
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
            await status_msg.edit_text(get_ui_text(uid, "system_error").format(error=str(e)))
            conn.close()
            return
        finally:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        
        cursor.execute("SELECT ticker, date_detected, price_detected FROM insider_signals WHERE status = 'ACTIVE' ORDER BY date_detected DESC")
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            await status_msg.edit_text(get_ui_text(uid, "insider_none").format(channel_link=CHANNEL_LINK), parse_mode=enums.ParseMode.MARKDOWN, disable_web_page_preview=True)
            return
        else:
            response_text = get_ui_text(uid, "insider_active")
            for row in rows:
                ticker, date, price = row
                response_text += f"• **{ticker}**\n  ↳ Detected: {date}\n  ↳ Entry: ${price:.2f}\n\n"
            response_text += get_ui_text(uid, "insider_footer")
            await status_msg.edit_text(response_text, parse_mode=enums.ParseMode.MARKDOWN)
            return

    cursor.execute("SELECT ticker, date_detected, price_detected FROM insider_signals WHERE status = 'ACTIVE' ORDER BY date_detected DESC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await message.reply_text(get_ui_text(uid, "insider_none").format(channel_link=CHANNEL_LINK), parse_mode=enums.ParseMode.MARKDOWN, disable_web_page_preview=True)
        return

    response_text = get_ui_text(uid, "insider_active")
    for row in rows:
        ticker, date, price = row
        response_text += f"• **{ticker}**\n  ↳ Detected: {date}\n  ↳ Entry: ${price:.2f}\n\n"
    response_text += get_ui_text(uid, "insider_footer")
    await message.reply_text(response_text, parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.text & filters.private & ~filters.command(["start", "help", "radar", "insider", "language"]))
async def prompt_analysis_mode(client: Client, message: Message):
    uid = message.from_user.id
    if is_bot_locked():
        await message.reply_text(get_ui_text(uid, "maintenance"))
        return
    register_user(uid, message.from_user.username or "Anonymous")
    
    ticker = message.text.strip().upper()
    if not re.match(r"^[A-Z0-9-]{1,8}$", ticker):
        await message.reply_text(get_ui_text(uid, "invalid_ticker"))
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡️ FLASH", callback_data=f"analyze:FLASH:{ticker}"),
         InlineKeyboardButton("🔍 PRO", callback_data=f"analyze:PRO:{ticker}")]
    ])
    await message.reply_text(get_ui_text(uid, "ticker_prompt").format(ticker=ticker), reply_markup=keyboard)

@app.on_callback_query()
async def handle_callbacks(client: Client, callback_query: CallbackQuery):
    uid = callback_query.from_user.id
    data = callback_query.data
    lang = get_user_language(uid)
    
    if is_bot_locked():
        await callback_query.answer(get_ui_text(uid, "system_updating"), show_alert=True)
        return
    
    if data.startswith("set_lang:"):
        _, selected_lang = data.split(":")
        set_user_language(uid, selected_lang)
        await callback_query.answer()
        try:
            await callback_query.message.edit_text(prompts.UI_STRINGS[selected_lang]["lang_success"])
        except MessageNotModified:
            pass

    elif data.startswith("analyze:"):
        _, mode, ticker = data.split(":")
        await callback_query.answer()
        try:
            await callback_query.message.edit_text(get_ui_text(uid, "compiling_report").format(mode=mode, ticker=ticker))
        except MessageNotModified:
            pass
            
        try:
            analysis_result = analyze_company(ticker, mode, lang)
            increment_scan_count(uid)
            # Stripped parse_mode to avoid tag structural conflicts
            await callback_query.message.edit_text(analysis_result)
        except MessageNotModified:
            pass
        except Exception as e:
            await callback_query.message.edit_text(get_ui_text(uid, "system_error").format(error=str(e)))

    elif data.startswith("radar_idx:"):
        _, index_name = data.split(":")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡️ FLASH", callback_data=f"radar_run:FLASH:{index_name}"),
             InlineKeyboardButton("🔍 PRO", callback_data=f"radar_run:PRO:{index_name}")]
        ])
        try:
            await callback_query.message.edit_text(get_ui_text(uid, "radar_scan_depth").format(index=index_name), reply_markup=keyboard)
        except MessageNotModified:
            pass

    elif data.startswith("radar_run:"):
        _, mode, index_name = data.split(":")
        await callback_query.answer()
        try:
            await callback_query.message.edit_text(get_ui_text(uid, "radar_running").format(index=index_name, mode=mode))
        except MessageNotModified:
            pass
            
        try:
            radar_result = get_value_radar(index_name, mode, lang)
            # Stripped parse_mode to avoid tag structural conflicts
            await callback_query.message.edit_text(radar_result)
        except MessageNotModified:
            pass
        except Exception as e:
            await callback_query.message.edit_text(get_ui_text(uid, "radar_error").format(error=str(e)))

            
if __name__ == "__main__":
    from pyrogram import idle
    init_db()
    print("ValueLens Telegram Bot UI is running...")
    app.start()
    asyncio.get_event_loop().create_task(background_scheduler(app))
    idle()
    app.stop()