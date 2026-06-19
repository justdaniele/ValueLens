# 📡 ValueLens: Automated Equity Intelligence

<div align="center">
  <img src="https://img.shields.io/badge/Status-Active_Production-success?style=for-the-badge" alt="Status"/>
  <img src="https://img.shields.io/badge/Architecture-Asynchronous-blue?style=for-the-badge" alt="Architecture"/>
  <img src="https://img.shields.io/badge/AI_Engine-DeepSeek_v4-purple?style=for-the-badge" alt="AI Engine"/>
</div>

<div align="center">
  <h3><a href="https://valuelens.uk">🌐 valuelens.uk</a></h3>
</div>

ValueLens is an institutional-grade equity intelligence website. Every night it scans the S&P 500, Nasdaq 100, S&P 400, and Russell 1000, runs each candidate through an AI fundamental analysis pipeline (reverse DCF, balance-sheet "zombie" detection, short-interest/momentum context), and surfaces ranked opportunities before the US market opens. It also tracks live insider buys, predicts earnings catalysts, and runs a $100k virtual portfolio that auto-trades every AI pick so the system's calls can be tracked transparently over time.

The whole pipeline runs autonomously, 24/7, on a single Raspberry Pi.

---

### 🌐 Live Site

**[valuelens.uk](https://valuelens.uk)**: top picks, insider buy signals, earnings sniper predictions, golden combo alerts, and the live virtual portfolio.

### 📢 Telegram Feeds

The same intelligence is also pushed to Telegram as a secondary, real-time channel, useful for push alerts (insider buys, earnings predictions, portfolio open/close events) without needing to check the site:
* 🇬🇧 **English**: [Join Channel](https://t.me/valuelensintelligence)
* 🇮🇹 **Italiano**: [Join Channel](https://t.me/valuelensintelligenceit)

---

## ⚡ Core Features

| Feature | Description |
|---------|-------------|
| 📡 **The Value Radar** | Multi-stage screening funnel across four indices (S&P 500, Nasdaq 100, S&P 400, Russell 1000). Filters on 52-week discount, P/E, and analyst-consensus upside (scaled to the portfolio's 90-day holding window) before any AI analysis runs. |
| 🧮 **Reverse DCF & Zombie Check** | AI calculates the implied terminal growth rate baked into the current price, and cross-references net income against operating cash flow to flag accounting red flags. |
| 📊 **Live Charts & Pricing** | 30-day price/RSI/MA20 charts per pick, plus live price streaming via a persistent Yahoo Finance WebSocket connection (not polling) for real-time updates across the site. |
| 🎯 **Earnings Sniper** | Tracks the earnings calendar 48h ahead, combining quantitative momentum with AI sentiment to predict short-term directional moves around earnings releases. |
| 🟢 **Insider Tracking** | Monitors SEC Form 4 filings for C-suite open-market buys. Activity per ticker accumulates over time instead of resetting on each detection, with a sortable table and a treemap view of the largest buys, plus full transaction detail (insider name, role, shares, value) on demand. |
| 💼 **$100k Virtual Portfolio** | Every AI pick automatically opens a simulated $1,000 position (1% of capital). Exits on target hit, 20% stop loss, or a 90-day hold. Fully transparent, trackable P&L with no survivorship bias. |
| 🏆 **Golden Combo Alerts** | Flags tickers where an AI fundamental pick and an insider buy signal align on the same name. The system's highest-conviction setup. |

---

## 🛠️ System Architecture

ValueLens runs as a defensive, non-blocking asynchronous multi-engine system, continuously (24/7) on local hardware (e.g. a Raspberry Pi), with a Flask API serving the public website.

**Website**
* `website/web_api.py`: Flask API. Serves `/api/*` endpoints (picks, insiders, earnings, portfolio, live prices) and the static frontend.
* `website/live_stream.py`: Persistent Yahoo Finance WebSocket connection, keeping the live-price cache fresh without per-request HTTP polling.
* `website/index.html`, `website/portfolio.html`: The public frontend.

**Engines**
* `bot.py`: Master daemon. Orchestrates the time-based scheduler and the Telegram admin command listener.
* `scanner.py`: The core screening and deep-value pipeline, target-price scaling, and Russell 1000/index universe sourcing.
* `analyzer.py`: DeepSeek interface. Generates the bilingual (EN/IT) fundamental reports.
* `earnings_engine.py` & `insider_engine.py`: Event-driven catalyst engines for earnings momentum and insider purchases.
* `database.py`: SQLite persistence layer. Reports, insider signals, earnings predictions, virtual portfolio, accuracy tracking.

---

## ⚙️ Quick Start & Deployment

### 1. Installation

```bash
git clone https://github.com/justdaniele/valuelens.git
cd valuelens
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file in the root directory:

```
TELEGRAM_BOT_TOKEN=your_secret_bot_token
DEEPSEEK_API_KEY=your_secret_deepseek_key
TELEGRAM_CHANNEL_ID_IT=-100xxxxxxxxxx
TELEGRAM_CHANNEL_ID_EN=-100xxxxxxxxxx
ADMIN_TELEGRAM_ID=your_numerical_telegram_id
```

### 3. Run

Launch all services with a single command:

```bash
chmod +x start.sh stop.sh
./start.sh
```

Stop everything:

```bash
./stop.sh
```

**Manual launch (alternative):**

```bash
nohup python3 -u bot.py > valuelens_master.log 2>&1 &
cd website && nohup python web_api.py &> web_api.log &
sudo tailscale funnel --bg 5000
```

### 4. Public domain

The site is exposed via [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (`cloudflared`), which connects outbound from the Pi to Cloudflare. No open ports on the home router, and a real certificate for the custom domain. [Tailscale Funnel](https://tailscale.com/kb/1223/funnel) was tried first, but it only issues HTTPS certificates for `*.ts.net` hostnames, so a custom domain CNAME fails the TLS handshake. Cloudflare Tunnel doesn't have that limitation.

---

⚠️ **Disclaimer**: ValueLens is a fully automated informational and educational system. Nothing it publishes (picks, insider data, AI-generated reports, scores, or virtual portfolio performance) constitutes financial, tax, or investment advice. Past or simulated performance is not indicative of future results.
