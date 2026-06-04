# ValueLens Bot 📡

A lightweight, high-performance Telegram bot powered by **Pyrogram** and **DeepSeek-v4**, engineered to deliver institutional-grade equity valuations and corporate insider tracking directly to your mobile screen.

---

## ✨ Core Features

* 📡 **Value Radar:** Scans major market indices (e.g., S&P 500) for structural discounts.
* 🧮 **Advanced Stress-Tests:** Computes 10-year Reverse DCF implied growth rates and triggers "Zombie Detector" cash-flow quality checks.
* 🟢 **Insider Tracking:** Monitors high-conviction C-Suite corporate buying patterns.
* 🇬🇧/🇮🇹 **Dual Language:** Native localized support for both English and Italian analytical outputs.

---

## 🛠️ Quick Start

### 1. Installation
```bash
git clone [https://github.com/yourusername/valuelens-bot.git](https://github.com/justdaniele/valuelens-bot.git)
cd valuelens-bot
pip install pyrogram tgcrypto yfinance openai python-dotenv
2. Environment Configuration
Create a secure .env file in the root directory:

Ini, TOML
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=your_bot_token
DEEPSEEK_API_KEY=your_deepseek_key


3. Execution
Bash
python bot.py




⚠️ Disclaimer
This software is developed strictly for educational and research purposes. Algorithmic outputs do not constitute formal financial or investment advice.
