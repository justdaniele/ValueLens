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

# --- ULTRACLOSE SYSTEM PROMPT (NO RAW BR TAGS, COLD QUANT DATA) ---
ANALYSIS_SYSTEM_PROMPT = """You are ValueLens, an elite quantitative hedge fund analyst writing ultra-concise daily intelligence briefings for mobile terminals.

STRICT FORMATTING & STYLE RULES:
- Use ONLY <b>bold</b> and <i>italic</i> HTML tags for layout emphasis.
- NEVER write the literal strings "<br>", "<br/>" or "\\n" in text. Use standard clean double line breaks (newlines) for spacing.
- NEVER use Markdown syntax (asterisks **, underscores __, or backticks).
- Bullet points must use exactly the bullet glyph "•".
- Be brutally concise, cynical, and data-driven. Limit each analytical dimension to maximum 1-2 sharp, dense sentences. Zero fluff allowed.
"""

def analyze_company(ticker: str, mode: str = "PRO", lang: str = "en", company_info: dict = None) -> str:
    """
    Generates an institutional-grade, highly-compact financial flash report.
    Grounded strictly in real-time market data to prevent hallucinations.
    """
    if not ai_client:
        return f"<b>[ {ticker} ]</b> Analysis aborted: DeepSeek API Client uninitialized."

    # Extract clean baseline numbers
    current_price = "N/A"
    target_mean = "N/A"
    trailing_pe = "N/A"
    price_to_book = "N/A"
    discount_pct = "0.0%"

    if company_info and isinstance(company_info, dict):
        c_val = company_info.get("currentPrice") or company_info.get("regularMarketPrice")
        t_val = company_info.get("targetMeanPrice")
        pe_val = company_info.get("trailingPE") or company_info.get("forwardPE")
        pb_val = company_info.get("priceToBook")
        
        current_price = f"${c_val:,.2f}" if c_val else "N/A"
        target_mean = f"${t_val:,.2f}" if t_val else "N/A"
        trailing_pe = f"{pe_val:.2f}x" if pe_val else "N/A"
        price_to_book = f"{pb_val:.2f}x" if pb_val else "N/A"
        
        if c_val and t_val and t_val > 0:
            discount_pct = f"{((t_val - c_val) / t_val) * 100:.1f}%"

    mode_instruction = "institutional elite flash dive" if mode == "PRO" else "concise summary briefing"
    language_instruction = "Write the response entirely in Italian." if lang == "it" else "Write the response entirely in English."

    user_prompt = f"""Target Ticker: {ticker}
Configuration: {mode_instruction}
Language: {language_instruction}

REAL-TIME FINANCIAL METRICS:
- Price: {current_price}
- Target: {target_mean} (Discount Room: {discount_pct})
- P/E Multiplier: {trailing_pe}
- P/B Value: {price_to_book}

Generate the brief following this EXACT structure template. Replace bracketed guidelines with maximum 1-2 brutal sentences:

📊 <b>Price Context</b>: [1-2 sentences verifying the {current_price} price relative to the {target_mean} target and {trailing_pe} multiplier. State if the discount room of {discount_pct} is a real opportunity or a trap.]

📉 <b>Reverse DCF Stress-Test</b>: [1-2 sentences maximum detailing what growth rate the current valuation embeds and if it is realistic.]

🛡️ <b>Zombie Detector</b>: [1-2 sentences checking cash conversion quality and verifying if operating cash flow supports reported net income.]

🚨 <b>ValueLens Verdict</b>: [1 single high-impact, cynical sentence stating if this asset is an authentic equity discount or a deadly value trap.]

Strict constraint: Keep it short, bulleted, and heavily punchy. Do not output raw markdown code blocks.
"""

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        logger.error(f"DeepSeek core completion engine failed for asset {ticker}: {e}")
        return f"⚠️ <b>Analysis Engine Timeout</b>: Unable to compile data layers for {ticker} at this time."

def generate_earnings_sentiment_layer(ticker: str, company_name: str) -> int:
    """Analyzes short-term sentiment risk profile 48h prior to earnings."""
    if not ai_client:
        return 0

    prompt = f"""Analyze the forward-looking risk profile for {company_name} ({ticker}) ahead of earnings.
Return a single integer score strictly between -40 (bearish) and +40 (bullish).
CRITICAL: Your response must contain ONLY the raw number. No words, punctuation or markdown.
"""
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