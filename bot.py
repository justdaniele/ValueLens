import os
import re
import sqlite3
from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from analyzer import analyze_company, get_value_radar

load_dotenv()

API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("Missing Telegram environment variables in .env")

app = Client("valuelens_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def init_db():
    conn = sqlite3.connect("valuelens.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            user_level INTEGER DEFAULT 1,
            Scans_count INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def register_user(user_id: int, username: str):
    conn = sqlite3.connect("valuelens.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, username, user_level, Scans_count)
        VALUES (?, ?, 1, 0)
    """, (user_id, username))
    conn.commit()
    conn.close()

def increment_scan_count(user_id: int):
    conn = sqlite3.connect("valuelens.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET Scans_count = Scans_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

@app.on_message(filters.command(["start", "help"]) & filters.private)
async def send_welcome(client: Client, message: Message):
    register_user(message.from_user.id, message.from_user.username or "Anonymous")
    
    welcome_text = (
        "📊 **Welcome to ValueLens Bot!**\n\n"
        "Your quantitative analyst for Global Stocks.\n"
        "⚡ **PRO features activated for FREE!**\n\n"
        "**Commands:**\n"
        "• Send any ticker (e.g., `AAPL`, `MSFT`) to analyze it.\n"
        "• Use /radar to find undervalued market anomalies.\n\n"
        "⚠️ *Disclaimer: Educational purposes only. Not financial advice.*"
    )
    await message.reply_text(welcome_text, parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.command("radar") & filters.private)
async def value_radar_menu(client: Client, message: Message):
    """Triggers the Value Radar menu with inline index selection."""
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

@app.on_message(filters.text & filters.private & ~filters.command(["start", "help", "radar"]))
async def prompt_analysis_mode(client: Client, message: Message):
    """Intercepts ticker and asks user for depth preference."""
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
    """Handles all button clicks."""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    # 1. Ticker Analysis Execution
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

    # 2. Radar Index Selected -> Ask for Mode
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

    # 3. Radar Execution
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