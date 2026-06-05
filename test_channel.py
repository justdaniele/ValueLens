"""
test_channel.py
Testa se il bot riesce a postare nel canale Telegram.
Esegui con: python3 test_channel.py
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

if not BOT_TOKEN or not CHANNEL_ID:
    print("❌ TELEGRAM_BOT_TOKEN o TELEGRAM_CHANNEL_ID mancanti nel .env")
    exit(1)

print(f"BOT_TOKEN: {BOT_TOKEN[:10]}...")
print(f"CHANNEL_ID: {CHANNEL_ID}")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
payload = {
    "chat_id":    CHANNEL_ID,
    "text":       "✅ *ValueLens* — test di connessione riuscito. Il bot può postare nel canale.",
    "parse_mode": "Markdown",
}

r = requests.post(url, json=payload, timeout=15)
print(f"\nHTTP Status: {r.status_code}")
print(f"Response: {r.text}")

if r.status_code == 200:
    print("\n✅ Funziona! Il bot ha postato nel canale.")
else:
    print("\n❌ Errore. Controlla che il bot sia admin del canale con permesso di postare.")
