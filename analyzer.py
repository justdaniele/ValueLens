import os
import logging
from openai import OpenAI
from dotenv import load_dotenv
import yfinance as yf

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
- Each of the 3 sections: header emoji + bold label, then MAXIMUM 1-2 lines of tight analysis. Never exceed 2 lines per section.
- End with a divider line then the score block.
- Opportunity Score: integer 0-100. Be ruthlessly honest.
- SCORES line (machine-readable, always include): SCORES: DCF=X | ZOMBIE=X | SHORT=X where each X is -10 (max bearish) to +10 (max bullish).
- Reference the RSI value in the Short Interest section (momentum context).
- Verdict: exactly 1 sentence.
- No filler words. No repetition. Every sentence must add new information.
"""

def _compute_rsi(ticker: str, period: int = 14) -> float:
    """Computes RSI(14) for a ticker using last 60 days of price data."""
    try:
        hist   = yf.Ticker(ticker).history(period="60d")["Close"]
        delta  = hist.diff()
        gain   = delta.clip(lower=0).rolling(period).mean()
        loss   = (-delta.clip(upper=0)).rolling(period).mean()
        rs     = gain / loss.replace(0, float("inf"))
        rsi    = 100 - (100 / (1 + rs))
        val    = rsi.dropna().iloc[-1]
        return round(float(val), 1)
    except Exception:
        return None


def analyze_company(ticker: str, mode: str = "PRO", lang: str = "en", company_info: dict = None) -> str:
    if not ai_client:
        logger.warning("DeepSeek client missing. Bypassing generative analysis.")
        return "⚠️ <b>AI Analysis Unavailable</b>"

    info = company_info or {}

    # Extract short interest percentage of float safely
    short_float = info.get("shortPercentOfFloat")
    short_interest_str = f"{short_float * 100:.2f}%" if short_float is not None else "N/A"

    # RSI must be computed once, before the lang branch — it used to live
    # only inside the `else` (English) branch, so the Italian branch tried
    # to read rsi_str before it was ever assigned (UnboundLocalError on
    # every IT report generation).
    rsi_val = _compute_rsi(ticker)
    rsi_str = f"{rsi_val} ({'⚠️ overbought' if rsi_val and rsi_val >= 70 else '🟢 oversold' if rsi_val and rsi_val <= 30 else 'neutral'})" if rsi_val else "N/A"

    if lang == "it":
        user_content = (
            f"Genera un brief per <b>{ticker}</b> ({info.get('shortName', ticker)}) usando questi dati reali:\n"
            f"- P/E: {info.get('trailingPE', 'N/A')} | P/B: {info.get('priceToBook', 'N/A')}\n"
            f"- Target Analisti: {info.get('targetMeanPrice', 'N/A')} | Short Float: {short_interest_str}\n"
            f"- RSI(14): {rsi_str}\n\n"
            f"Struttura ESATTAMENTE cosi' (nessuna deviazione):\n\n"
            f"📉 <b>Reverse DCF</b>\n"
            f"[1-2 righe MAX: tasso di crescita implicito nel prezzo attuale, e' realistico?]\n\n"
            f"🧟 <b>Zombie Detector</b>\n"
            f"[1-2 righe MAX: salute del bilancio, qualita' cash flow, rischio insolvenza]\n\n"
            f"🎯 <b>Short Interest & Sentiment</b>\n"
            f"[1-2 righe MAX: {short_interest_str} — pressione short e potenziale squeeze]\n\n"
            f"━━━━━━━━━━━━\n"
            f"💎 <b>Opportunity Score: X/100</b>\n"
            f"SCORES: DCF=X | ZOMBIE=X | SHORT=X\n"
            f"<i>Verdict: [opportunita' reale o trappola di valore, una frase]</i>\n"
            f"(Linea SCORES: ogni X e' un intero da -10 ribassista a +10 rialzista per quella sezione)"
        )
    else:
        user_content = (
            f"Generate a brief for <b>{ticker}</b> ({info.get('shortName', ticker)}) using this real data:\n"
            f"- P/E: {info.get('trailingPE', 'N/A')} | P/B: {info.get('priceToBook', 'N/A')}\n"
            f"- Analyst Target: {info.get('targetMeanPrice', 'N/A')} | Short Float: {short_interest_str}\n"
            f"- RSI(14): {rsi_str}\n\n"
            f"Structure EXACTLY as follows (no deviations):\n\n"
            f"📉 <b>Reverse DCF</b>\n"
            f"[1-2 lines MAX: implied growth rate in current price, is it realistic?]\n\n"
            f"🧟 <b>Zombie Detector</b>\n"
            f"[1-2 lines MAX: balance sheet health, cash flow quality, insolvency risk]\n\n"
            f"🎯 <b>Short Interest & Sentiment</b>\n"
            f"[1-2 lines MAX: {short_interest_str} — short pressure and squeeze potential]\n\n"
            f"━━━━━━━━━━━━\n"
            f"💎 <b>Opportunity Score: X/100</b>\n"
            f"SCORES: DCF=X | ZOMBIE=X | SHORT=X\n"
            f"<i>Verdict: [genuine opportunity or value trap, one sentence]</i>\n"
            f"(SCORES line: each X is an integer from -10 bearish to +10 bullish for that section)"
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