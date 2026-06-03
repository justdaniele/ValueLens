import os
import re
import sqlite3
from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from analyzer import analyze_company

# Load environmental variables from .env file
load_dotenv()

# Mapping the exact keys from your .env file
API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Safeguard check to ensure variables are correctly loaded
if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("One or more Telegram environment variables are missing from your .env file")

# Initialize the Pyrogram Client as a Bot
app = Client(
    "valuelens_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

def register_user(user_id: int, username: str):
    """
    Registers a new user into the SQLite database.
    Initial promotional strategy sets user_level = 1 (PRO tier) for everyone for free.
    """
    conn = sqlite3.connect("valuelens.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, username, user_level, Scans_count)
        VALUES (?, ?, 1, 0)
    """, (user_id, username))
    conn.commit()
    conn.close()

def increment_scan_count(user_id: int):
    """Increments the total count of financial scans performed by the user."""
    conn = sqlite3.connect("valuelens.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET Scans_count = Scans_count + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

@app.on_message(filters.command(["start", "help"]) & filters.private)
async def send_welcome(client: Client, message: Message):
    """Handles /start and /help commands asynchronously."""
    user_id = message.from_user.id
    username = message.from_user.username or "Anonymous"
    
    register_user(user_id, username)
    
    welcome_text = (
        "📊 *Welcome to ValueLens Bot!*\n\n"
        "Your asynchronous quantitative analyst for NASDAQ & S&P 500 stocks.\n"
        "Powered by DeepSeek V4 infrastructure.\n\n"
        "⚡ *PRO features have been automatically activated on your account for FREE!*\n\n"
        "**How to use:** Simply send me any stock ticker (e.g., `AAPL`, `MSFT`, `TSLA`) to trigger a deep financial stress-test analysis."
    )
    await message.reply_text(welcome_text, parse_mode=enums.ParseMode.MARKDOWN)

@app.on_message(filters.text & filters.private)
async def handle_ticker_analysis(client: Client, message: Message):
    """Intercepts text messages asynchronously and checks if they are valid stock tickers."""
    user_id = message.from_user.id
    username = message.from_user.username or "Anonymous"
    
    # Ensure the user is registered in the DB
    register_user(user_id, username)
    
    # Sanitize and extract the ticker symbol
    ticker = message.text.strip().upper()
    
    # Regex validation for standard market tickers (1 to 5 alphabetic characters)
    if not re.match(r"^[A-Z]{1,5}$", ticker):
        await message.reply_text("❌ Invalid format. Please send a valid stock ticker symbol (e.g., AAPL or NVDA).")
        return
    
    # Send a non-blocking placeholder while DeepSeek is processing
    waiting_msg = await message.reply_text(f"🔍 Fetching market data and running quantitative models for **{ticker}**... Please wait.")
    
    try:
        # Execute the DeepSeek financial analysis logic
        analysis_result = analyze_company(ticker, user_id)
        
        # Track metric inside the database
        increment_scan_count(user_id)
        
        # Delete placeholder and return the final report
        await waiting_msg.delete()
        await message.reply_text(analysis_result, parse_mode=enums.ParseMode.MARKDOWN)
        
    except Exception as e:
        # Handle cases where waiting_msg might fail or need safe cleanup
        try:
            await waiting_msg.delete()
        except Exception:
            pass
        await message.reply_text(f"❌ An unexpected system error occurred: {str(e)}")

if __name__ == "__main__":
    print("ValueLens Telegram Bot is successfully running and listening for market tickers...")
    app.run()