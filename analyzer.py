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

# --- BALANCED & OBJECTIVE SYSTEM PROMPT (NO RAW BR TAGS, BALANCED RISK/REWARD) ---
ANALYSIS_SYSTEM_PROMPT = """You are ValueLens, an elite institutional financial analyst writing objective, balanced, and risk-aware daily intelligence briefings for mobile terminals.

STRICT FORMATTING & STYLE RULES:
- Use ONLY <b>bold</b> and <i>italic</i> HTML tags for layout emphasis.
- NEVER write the literal strings "<br>", "<br/>" or "\\n" in text. Use standard clean double line breaks (newlines) for spacing.
- NEVER use Markdown syntax (asterisks **, underscores __, or backticks).
- Bullet points must use exactly the bullet glyph "•".
- Be extremely concise, objective, and data-driven. Weigh both the structural risks and the competitive advantages or margins of safety fairly based strictly on data. Limit each analytical dimension to maximum 1-2 sharp sentences.
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
            f"Genera un'analisi concisa per <b>{ticker}</b> ({info.get('shortName', ticker)}).\n"
            f"Usa questi dati reali per ancorare i calcoli:\n"
            f"- P/E Ratio: {info.get('trailingPE', 'N/A')}\n"
            f"- Price to Book: {info.get('priceToBook', 'N/A')}\n"
            f"- Analyst Target Mean: {info.get('targetMeanPrice', 'N/A')}\n"
            f"- Short Interest del Flottante: {short_interest_str}\n\n"
            f"Struttura il report esattamente in 3 punti elenco usando il glyph '•':\n"
            f"1. <b>Reverse DCF:</b> Calcola la crescita dei flussi di cassa implicita nel prezzo attuale.\n"
            f"2. <b>Zombie Detector:</b> Valuta la salute del bilancio e la qualità dei flussi di cassa.\n"
            f"3. <b>Short Interest & Sentiment:</b> Sintetizza il dato reale ({short_interest_str}) in una sola frase, indicando se la pressione dei venditori allo scoperto è alta, moderata o trascurabile, e se esiste rischio/opportunità di Short Squeeze."
        )
    else:
        user_content = (
            f"Generate a concise investment brief for <b>{ticker}</b> ({info.get('shortName', ticker)}).\n"
            f"Ground your analysis with this real data:\n"
            f"- P/E Ratio: {info.get('trailingPE', 'N/A')}\n"
            f"- Price to Book: {info.get('priceToBook', 'N/A')}\n"
            f"- Analyst Target Mean: {info.get('targetMeanPrice', 'N/A')}\n"
            f"- Short Interest % of Float: {short_interest_str}\n\n"
            f"Structure the report into exactly 3 bullet points using the '•' glyph:\n"
            f"1. <b>Reverse DCF:</b> Analyze the implied growth rate embedded in the current stock price.\n"
            f"2. <b>Zombie Detector:</b> Stress-test balance sheet health and cash-flow generation quality.\n"
            f"3. <b>Short Interest & Sentiment:</b> Synthesize the short interest data ({short_interest_str}) in a single sentence, indicating whether short-seller pressure is high, moderate, or negligible, and if there is any short-squeeze potential."
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
                {"role": "system", "content": "You are a quantitative data endpoint. Output only raw integers."},\n                {"role": "user", "content": prompt}
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