import os
import sqlite3
from dotenv import load_dotenv
from pyrogram import Client, filters

# 1. CARICAMENTO VARIABILI D'AMBIENTE
load_dotenv()
API_ID = int(os.environ.get("TELEGRAM_API_ID", 0))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# 2. INIZIALIZZAZIONE DATABASE (SQLite)
DB_NAME = "utenti_bot.db"

def init_db():
    """Crea il file e la tabella se non esistono, con le protezioni anti-crash."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;") # Protezione per letture/scritture multiple
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                ruolo TEXT DEFAULT 'free',
                data_iscrizione TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

def aggiungi_utente(user_id):
    """Salva l'ID dell'utente. Se esiste già, lo ignora senza dare errori."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()

# 3. CONFIGURAZIONE BOT TELEGRAM
app = Client("financial_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
async def start_command(client, message):
    user_id = message.from_user.id
    
    # Salvataggio silenzioso nel DB appena l'utente preme Start
    aggiungi_utente(user_id)
    
    await message.reply_text(
        f"👋 Ciao {message.from_user.first_name}!\n\n"
        "Sono online e il tuo profilo è stato salvato nel mio database in modo sicuro. 🚀\n"
        "Presto potrai chiedermi di analizzare il mercato."
    )

if __name__ == "__main__":
    print("🔧 Inizializzazione Database in corso...")
    init_db()
    print("✅ Database pronto. Avvio del bot Telegram...")
    app.run()
