import os
import logging
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ValueLensAnalyzer")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

if DEEPSEEK_API_KEY:
    ai_client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1"
    )
else:
    ai_client = None
    logger.warning("DEEPSEEK_API_KEY missing. AI generation will be unavailable.")

# --- SYSTEM PROMPT: CONCISE MOBILE-FIRST FORMAT WITH OPPORTUNITY SCORE ---
ANALYSIS_SYSTEM_PROMPT = """You are ValueLens, an institutional financial analyst writing sharp, mobile-first equity briefs.

STRICT FORMATTING RULES:
- Use ONLY <b>bold</b> and <i>italic</i> HTML tags. Never use Markdown (**, __, backticks).
- NEVER write literal "<br>", "<br/>" or "\\n". Use real newlines only.
- Each of the 3 sections: header emoji + bold label, then 2-3 lines max of tight analysis.
- End with a divider line then the Opportunity Score block.
- Opportunity Score: integer 0-100 derived from fundamentals. Be ruthlessly honest.
- Verdict: 1 sentence — genuine opportunity or value trap, and why in one clause.
- No filler words. No repetition. Every sentence must add new information.
"""

def analyze_company(ticker: str, mode: str = "PRO", lang: str = "en", company_info: dict = None) -> str:
    if not ai_client:
        logger.warning("DeepSeek client missing. Bypassing generative analysis.")
        return "⚠️ <b>AI Analysis Unavailable</b>"

    info = company_info or {}

    # Extract short interest percentage of float safely
    short_float = info.get("shortPercentOfFloat")
    short_interest_str = f"{short_float * 100:.2f}%" if short_float is not None else "N/A"

    if lang == "it":
        user_content = (
            f"Genera un brief per <b>{ticker}</b> ({info.get('shortName', ticker)}) usando questi dati reali:\n"
            f"- P/E: {info.get('trailingPE', 'N/A')} | P/B: {info.get('priceToBook', 'N/A')}\n"
            f"- Target Analisti: {info.get('targetMeanPrice', 'N/A')} | Short Float: {short_interest_str}\n\n"
            f"Struttura esattamente cosi':\n\n"
            f"📉 <b>Reverse DCF</b>\n"
            f"[2-3 righe: tasso di crescita implicito nel prezzo attuale, e' realistico?]\n\n"
            f"🧟 <b>Zombie Detector</b>\n"
            f"[2-3 righe: salute del bilancio, qualita' cash flow, rischio insolvenza]\n\n"
            f"🎯 <b>Short Interest & Sentiment</b>\n"
            f"[2-3 righe: {short_interest_str} — pressione short, potenziale squeeze]\n\n"
            f"━━━━━━━━━━━━\n"
            f"💎 <b>Opportunity Score: X/100</b>\n"
            f"<i>Verdict: [opportunita' reale o trappola di valore, motivo principale in una frase]</i>"
        )
    else:
        user_content = (
            f"Generate a brief for <b>{ticker}</b> ({info.get('shortName', ticker)}) using this real data:\n"
            f"- P/E: {info.get('trailingPE', 'N/A')} | P/B: {info.get('priceToBook', 'N/A')}\n"
            f"- Analyst Target: {info.get('targetMeanPrice', 'N/A')} | Short Float: {short_interest_str}\n\n"
            f"Structure exactly as follows:\n\n"
            f"📉 <b>Reverse DCF</b>\n"
            f"[2-3 lines: implied growth rate in current price, is it realistic?]\n\n"
            f"🧟 <b>Zombie Detector</b>\n"
            f"[2-3 lines: balance sheet health, cash flow quality, insolvency risk]\n\n"
            f"🎯 <b>Short Interest & Sentiment</b>\n"
            f"[2-3 lines: {short_interest_str} — short pressure level, squeeze potential]\n\n"
            f"━━━━━━━━━━━━\n"
            f"💎 <b>Opportunity Score: X/100</b>\n"
            f"<i>Verdict: [genuine opportunity or value trap, main reason in one sentence]</i>"
        )

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2,
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        logger.error(f"DeepSeek core completion engine failed for asset {ticker}: {e}")
        return f"⚠️ <b>Analysis Engine Timeout</b>: Unable to compile data layers for {ticker} at this time."

def generate_earnings_sentiment_layer(ticker: str, company_name: str) -> int:
    """Analyses short-term sentiment risk profile 48h prior to earnings."""
    if not ai_client:
        return 0

    prompt = (
        f"Analyze the forward-looking risk profile for {company_name} ({ticker}) ahead of earnings.\n"
        f"Return a single integer score strictly between -40 (bearish) and +40 (bullish).\n"
        f"CRITICAL: Your response must contain ONLY the raw number. No words, punctuation or markdown."
    )

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are a quantitative data endpoint. Output only raw integers."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=10
        )
        raw_result = response.choices[0].message.content.strip()
        score = int(''.join(c for c in raw_result if c.isdigit() or c == '-'))
        return min(max(score, -40), 40)

    except Exception as e:
        logger.warning(f"Could not compute AI sentiment modifier for {ticker}: {e}. Defaulting to 0.")
        return 0