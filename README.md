# 📡 ValueLens Intelligence Bot

<div align="center">
  <img src="https://img.shields.io/badge/Status-Active_Production-success?style=for-the-badge" alt="Status"/>
  <img src="https://img.shields.io/badge/Architecture-Asynchronous-blue?style=for-the-badge" alt="Architecture"/>
  <img src="https://img.shields.io/badge/AI_Engine-DeepSeek_v4-purple?style=for-the-badge" alt="AI Engine"/>
</div>

An institutional-grade, automated quantitative equity screening and catalyst predictive engine. Powered by **DeepSeek-v4** and **yFinance**, ValueLens autonomously scans major financial universes, calculates structural cash-flow intrinsic values via reverse engineering, generates visual charts, and broadcasts localized risk-aware market intelligence directly to Telegram channels.

---

### 📢 Official Intelligence Channels
Stay updated with real-time autonomous streams directly on Telegram:
* 🇬🇧 **English Intelligence Feed**: [Join Channel](https://t.me/valuelensintelligence)
* 🇮🇹 **Italian Intelligence Feed**: [Join Channel](https://t.me/valuelensintelligenceit)

---

## ⚡ Core Operational Pillars

| Feature | Description |
|---------|-------------|
| 📡 **The Value Radar** | Multi-stage funnel scanning index rosters using high-speed native parameters, validating deep-year discounts against fundamental matrix layers (P/E, P/B, Analyst Upside). |
| 🧮 **Reverse DCF & Zombie Check** | Forces AI to calculate the implied terminal free cash flow growth rate embedded in current prices, and cross-references Net Income against active Operating Cash Flow to detect accounting mirages. |
| 📊 **Visual Chart Generation** | Autonomously plots historical price action overlaid with Analyst Mean Target lines directly inside the Telegram payload. |
| 🎯 **Earnings Sniper** | Tracks corporate calendar matrixes to isolate high-impact earnings drops, synthesizing quantitative momentum with AI macro sentiment to predict short-term directional moves. |
| 🟢 **Insider Tracking** | Monitors SEC compliance data to isolate and broadcast high-conviction C-Suite corporate buying patterns. |

---

## 🛠️ System Architecture

ValueLens operates under a highly defensive, non-blocking asynchronous multi-engine topology running continuously (24/7) on local hardware (e.g., Raspberry Pi).

* `bot.py`: The master daemon orchestrating time-based background loops and an independent asynchronous Long-Polling server for secure command handling.
* `scanner.py`: Executes the native high-speed analytical value pipeline and generates matplotlib target charts.
* `analyzer.py`: Interface connector to the DeepSeek infrastructure; handles grounding matrices and prompt injection context.
* `earnings_engine.py` & `insider_engine.py`: Event-driven catalyst engines tracking earnings momentum and C-Suite insider purchases.
* `database.py`: Local disk persistence SQLite layer managing ledger writes, synchronization states, and systemic accuracy tracking.

---

## ⚙️ Quick Start & Deployment

### 1. Installation
Clone the secure repository and install the production dependencies:
```bash
git clone [https://github.com/justdaniele/valuelens.git](https://github.com/justdaniele/valuelens.git)
cd valuelens
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Secure Configuration
Create a production .env file in the root directory:

```
TELEGRAM_BOT_TOKEN=your_secret_bot_token
DEEPSEEK_API_KEY=your_secret_deepseek_key
TELEGRAM_CHANNEL_ID_IT=-100xxxxxxxxxx
TELEGRAM_CHANNEL_ID_EN=-100xxxxxxxxxx
ADMIN_TELEGRAM_ID=your_numerical_telegram_id
```


3. Execution Daemon
Launch the autonomous master engine in protected background mode:

```
Bash
nohup python bot.py > valuelens_master.log 2>&1 &

```


⚠️ Disclaimer: Developed strictly for educational and systematic research purposes. Algorithmic telemetry outputs do not constitute formal financial, tax, or investment advice.
