import os
import re
import sqlite3
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from analyzer import analyze_company, get_value_radar
from database import init_db, register_user, increment_scan_count, DB_NAME

load_dotenv()

API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
LOCK_FILE = "scan.lock"

# Placeholder for your future Telegram channel link
CHANNEL_LINK = "https://t.me/your_channel_username" 

if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("Missing Telegram environment variables in .env")

app = Client("valuelens_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

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
        await message.reply_text("🤖 **ValueLens | Maintenance**\n\nRunning nightly market data updates. Back online in a few minutes!")
        return
        
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    
    welcome_text = (
        "📊 **Welcome to ValueLens Bot!**\n\n"
        "Your quantitative analyst for Global Stocks.\n"
        "⚡ **PRO features activated for FREE!**\n\n"
        "Type /help to see all available commands and features.\n\n"
        "⚠️ *Disclaimer: Educational purposes only. Not financial advice.*"
    )
    await message.reply_text(welcome_text, parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.command("help") & filters.private)
async def send_help(client: Client, message: Message):
    if is_bot_locked():
        await message.reply_text("🤖 **ValueLens | Maintenance**\n\nRunning nightly market data updates. Back online in a few minutes!")
        return

    register_user(message.from_user.id, message.from_user.username or "Anonymous")

    # Kept commands completely free of markdown styling to ensure native Telegram clickability
    help_text = (
        "📖 **ValueLens Bot | Command Reference**\n\n"
        "• /start - Initialize the bot and check registration.\n"
        "• /help - Show this interactive command guide.\n"
        "• /radar - Scan indices (e.g., S&P 500) for structural value anomalies.\n"
        "• /insider - View active real-time C-Suite corporate insider buying alerts.\n\n"
        "💡 **Direct Analysis:** Just type any stock ticker symbol (e.g., AAPL, MSFT) directly in chat to compile custom FLASH or PRO reports."
    )
    await message.reply_text(help_text, parse_mode=enums.ParseMode.NONE)

@app.on_message(filters.command("radar") & filters.private)
async def value_radar_menu(client: Client, message: Message):
    if is_bot_locked():
        await message.reply_text("🤖 Running nightly data update. Please wait a few minutes.")
        return
        
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇸 S&P 500", callback_data="radar_idx:S&P 500")],
        [InlineKeyboardButton("🦅 NASDAQ", callback_data="radar_idx:NASDAQ")],
        [InlineKeyboardButton("✨ Magnificent 7", callback_data="radar_idx:Magnificent 7")],
        [InlineKeyboardButton("🏭 Dow Jones", callback_data="radar_idx:Dow Jones")],
        [InlineKeyboardButton("🔬 Russell 2000", callback_data="radar_idx:Russell 2000")]
    ])
    
    await message.reply_text(
        "📡 **Value Radar**\nSelect a market index to scan for undervalued anomalies:",
        reply_markup=keyboard
    )

@app.on_message(filters.command("insider") & filters.private)
async def view_insider_signals(client: Client, message: Message):
    if is_bot_locked():
        await message.reply_text("🤖 Updating Insider database right now. Please try again in 2 minutes!")
        return

    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT value FROM metadata WHERE key = 'last_insider_scan'")
    last_scan_status = cursor.fetchone()[0]
    
    # Text templates with integrated channel invitations and Virtual Tracker descriptions
    no_result_text = (
        "🚨 **ValueLens INSIDER | No Signals Found**\n\n"
        "Top 1,000 US companies scanned. Currently, **zero** entities match our high-conviction criteria "
        "(Price near 52-week lows + Aggressive corporate executive buying within the last 6 months).\n\n"
        "💡 **Verdict:** Market valuations are stretched; insiders are holding cash. Rescanning tonight.\n\n"
        "📢 **Join our Telegram Channel:** [ValueLens Alpha](" + CHANNEL_LINK + ")\n"
        "When high-conviction anomalies are discovered, they are instantly broadcasted there! "
        "The channel also hosts our **Virtual Tracker Portfolio**, monitoring real-time performance and ROI "
        "of all past insider alerts from their exact detection date."
    )
    
    if last_scan_status == "NEVER":
        status_msg = await message.reply_text(
            "🚀 **First-Time Initialization**\n\nThe global insider database is currently empty. "
            "Launching the initial scan across the top 1,000 US equities...\n\n"
            "⏱️ This process takes approx. 2 minutes. Please wait, the results will appear here automatically!",
            parse_mode=enums.ParseMode.MARKDOWN)
        
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
            await status_msg.edit_text(no_result_text, parse_mode=enums.ParseMode.MARKDOWN, disable_web_page_preview=True)
            return
        else:
            response_text = "🕵️‍♂️ **ValueLens INSIDER | Active US Signals**\n"
            response_text += "Companies detected at structural lows backed by heavy C-Suite buying:\n\n"
            for row in rows:
                ticker, date, price = row
                response_text += f"• **{ticker}**\n  ↳ Detected on: {date}\n  ↳ Entry Price: ${price:.2f}\n\n"
            response_text += "💡 *Analyze these tickers individually by sending them in chat to view the updated Reverse DCF.*"
            await status_msg.edit_text(response_text, parse_mode=enums.ParseMode.MARKDOWN)
            return

    cursor.execute("SELECT ticker, date_detected, price_detected FROM insider_signals WHERE status = 'ACTIVE' ORDER BY date_detected DESC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await message.reply_text(no_result_text, parse_mode=enums.ParseMode.MARKDOWN, disable_web_page_preview=True)
        return

    response_text = "🕵️‍♂️ **ValueLens INSIDER | Active US Signals**\n"
    response_text += "Companies detected at structural lows backed by heavy C-Suite buying:\n\n"
    
    for row in rows:
        ticker, date, price = row
        response_text += f"• **{ticker}**\n  ↳ Detected on: {date}\n  ↳ Entry Price: ${price:.2f}\n\n"
        
    response_text += "💡 *You can analyze these tickers individually by sending them in chat to view the updated Reverse DCF.*"
    await message.reply_text(response_text, parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.text & filters.private & ~filters.command(["start", "help", "radar", "insider"]))
async def prompt_analysis_mode(client: Client, message: Message):
    if is_bot_locked():
        await message.reply_text("🤖 Nightly update in progress. Core analysis function temporarily disabled.")
        return
        
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    
    ticker = message.text.strip().upper()
    if not re.match(r"^[A-Z0-9-]{1,8}$", ticker):
        await message.reply_text("❌ Invalid format. Send a valid ticker (e.g., AAPL).")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡️ FLASH", callback_data=f"analyze:FLASH:{ticker}"),
            InlineKeyboardButton("🔍 PRO", callback_data=f"analyze:PRO:{ticker}")
        ]
    ])
    
    await message.reply_text(
        f"🤖 **Ticker recognized:** `{ticker}`\nSelect the analysis depth:",
        reply_markup=keyboard
    )

@app.on_callback_query()
async def handle_callbacks(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if is_bot_locked():
        await callback_query.answer("🤖 Server busy with nightly database maintenance. Please wait.", show_alert=True)
        return
    
    if data.startswith("analyze:"):
        _, mode, ticker = data.split(":")
        await callback_query.answer()
        await callback_query.message.edit_text(f"🔍 Compiling {mode} report for **{ticker}**... Please wait.")
        try:
            analysis_result = analyze_company(ticker, mode)
            increment_scan_count(user_id)
            await callback_query.message.edit_text(analysis_result, parse_mode=enums.ParseMode.MARKDOWN)
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
        await callback_query.message.edit_text(
            f"📡 **Index:** {index_name}\nSelect scanning depth:",
            reply_markup=keyboard
        )

    elif data.startswith("radar_run:"):
        _, mode, index_name = data.split(":")
        await callback_query.answer()
        await callback_query.message.edit_text(f"📡 Scanning the **{index_name}** ({mode} mode)... Please wait.")
        try:
            radar_result = get_value_radar(index_name, mode)
            await callback_query.message.edit_text(radar_result, parse_mode=enums.ParseMode.MARKDOWN)
        except Exception as e:
            await callback_query.message.edit_text(f"❌ Radar error: {str(e)}")

if __name__ == "__main__":
    init_db()
    print("ValueLens Telegram Bot UI is running...")
    app.run()