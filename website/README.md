# ValueLens Web — Setup Guide

## What's in this package

| File | Purpose |
|------|---------|
| `index.html` | Public website — serves directly from the Pi |
| `web_api.py`  | Flask backend — reads your existing `valuelens.db` |

---

## 1. Install Python dependencies on the Pi

```bash
pip install flask flask-cors yfinance sib-api-v3-sdk --break-system-packages
```

---

## 2. Run the Flask API

The API must run **alongside** your existing `bot.py`. They share the same
`valuelens.db` SQLite file.

```bash
# From the same directory as bot.py and valuelens.db:
python web_api.py
```

For production (keeps running after SSH disconnect):

```bash
# Install gunicorn
pip install gunicorn --break-system-packages

# Run as background service
nohup gunicorn -w 2 -b 0.0.0.0:5000 web_api:app &> web_api.log &
```

Or add it to a systemd service alongside the bot.

---

## 3. Serve the website

Option A — Python's built-in server (simplest):
```bash
cd /path/to/valuelens-web
python -m http.server 8080
```
Then visit `http://<pi-ip>:8080` in your browser.

Option B — Nginx (recommended for public access):
```bash
sudo apt install nginx
sudo cp index.html /var/www/html/valuelens/index.html
```

---

## 4. Expose to the internet (Tailscale — already set up)

Since you're already using Tailscale, the simplest path is:

```bash
# On the Pi, enable Tailscale Funnel (public HTTPS URL, no port-forwarding)
tailscale funnel 8080
```

Tailscale will give you a public `https://your-machine.ts.net` URL.
Update `API_BASE` in `index.html` to point to `http://localhost:5000`
(since both the site and API are on the same machine).

---

## 5. Email collection — Brevo setup

1. Sign up free at https://app.brevo.com (300 emails/day free)
2. Go to **SMTP & API → API Keys → Create API key**
3. Add to your `.env` file:

```env
BREVO_API_KEY=xkeysib-xxxxxxxxxxxxxxxx
BREVO_SENDER_EMAIL=your@email.com
```
> The sender email must be verified in Brevo (takes 2 minutes).

### How emails are stored

Every email submitted on the site is saved in `subscribers.db`
(created automatically in the same folder as `web_api.py`).

To view your list at any time:
```bash
sqlite3 subscribers.db "SELECT email, subscribed_at FROM subscribers;"
```

---

## 6. Auto-send morning digest to subscribers

Add this line to `bot.py` inside `core_scheduler_loop()`,
right after the `morning_broadcast()` call at 08:00:

```python
import requests as _requests
try:
    _requests.post("http://localhost:5000/api/send_digest", timeout=30)
    logger.info("Morning digest dispatched to subscribers.")
except Exception as _e:
    logger.warning(f"Digest send failed: {_e}")
```

This calls the `/api/send_digest` endpoint which:
- Reads today's top picks from `valuelens.db`
- Builds an HTML email
- Sends it to every active subscriber via Brevo

---

## 7. Environment variables summary

Add these to your `.env` file:

```env
# Existing bot vars (already set)
DEEPSEEK_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHANNEL_ID_EN=...
TELEGRAM_CHANNEL_ID_IT=...
ADMIN_TELEGRAM_ID=...

# New web vars
BREVO_API_KEY=xkeysib-xxxxxxxxxxxxxxxx
BREVO_SENDER_EMAIL=valuelens@yourdomain.com
VALUELENS_DB=valuelens.db        # path to your SQLite DB (default: same folder)
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/meta` | GET | Hero stats (scanned count, accuracy, last scan time) |
| `/api/picks` | GET | Top picks from last night's scan (EN + IT reports) |
| `/api/price_history/<ticker>` | GET | 30-day closing prices for chart |
| `/api/insiders` | GET | Active insider buy signals |
| `/api/golden_combos` | GET | AI pick + insider buy overlaps |
| `/api/subscribe` | POST | Save subscriber email |
| `/api/subscribers` | GET | List all subscribers (admin use) |
| `/api/send_digest` | POST | Send morning email to all subscribers |

---

## Notes

- The website shows a friendly error message if the API is unreachable,
  so it degrades gracefully if the Pi is rebooting.
- `CORS` is set to `"*"` by default. In production, restrict this to
  your actual domain URL.
- The `/api/subscribers` endpoint has no auth — only expose it on
  your local network or Tailscale, not publicly.
