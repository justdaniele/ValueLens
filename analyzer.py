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

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = """You are ValueLens, an elite institutional financial analyst writing objective, balanced, and risk-aware daily intelligence briefings for mobile terminals.

STRICT FORMATTING & STYLE RULES:
- Use ONLY <b>bold</b> and <i>italic</i> HTML tags for layout emphasis.
- NEVER write the literal strings "<br>", "<br/>" or "\\n" in text. Use standard clean double line breaks (newlines) for spacing.
- NEVER use Markdown syntax (asterisks **, underscores __, or backticks).
- Bullet points must use exactly the bullet glyph "•".
- Be extremely concise, objective, and data-driven. Weigh both the structural risks and the competitive advantages or margins of safety fairly based strictly on data. Limit each analytical dimension to maximum 1-2 sharp sentences.
"""


# ---------------------------------------------------------------------------
# Company analysis
# ---------------------------------------------------------------------------

def analyze_company(ticker: str, mode: str = "PRO", lang: str = "en",
                    company_info: dict = None) -> str:
    """
    Generates an institutional-grade, balanced financial flash report.
    Grounded strictly in real-time market data to minimise hallucination risk.
    """
    if not ai_client:
        return f"<b>[ {ticker} ]</b> Analysis aborted: DeepSeek API client uninitialized."

    current_price = "N/A"
    target_mean   = "N/A"
    trailing_pe   = "N/A"
    price_to_book = "N/A"
    discount_pct  = "0.0%"

    if company_info and isinstance(company_info, dict):
        c_val  = company_info.get("currentPrice") or company_info.get("regularMarketPrice")
        t_val  = company_info.get("targetMeanPrice")
        pe_val = company_info.get("trailingPE") or company_info.get("forwardPE")
        pb_val = company_info.get("priceToBook")

        current_price = f"${c_val:,.2f}" if c_val else "N/A"
        target_mean   = f"${t_val:,.2f}" if t_val else "N/A"
        trailing_pe   = f"{pe_val:.2f}x" if pe_val else "N/A"
        price_to_book = f"{pb_val:.2f}x" if pb_val else "N/A"

        if c_val and t_val and t_val > 0:
            discount_pct = f"{((t_val - c_val) / t_val) * 100:.1f}%"

    mode_instruction     = "institutional elite flash dive" if mode == "PRO" else "concise summary briefing"
    language_instruction = "Write the response entirely in Italian." if lang == "it" else "Write the response entirely in English."

    user_prompt = f"""Target Ticker: {ticker}
Configuration: {mode_instruction}
Language: {language_instruction}

REAL-TIME FINANCIAL METRICS:
- Price: {current_price}
- Target: {target_mean} (Discount Room: {discount_pct})
- P/E Multiplier: {trailing_pe}
- P/B Value: {price_to_book}

Generate the brief following this EXACT structure template. Replace bracketed guidelines with maximum 1-2 balanced sentences:

📊 <b>Context Price</b>: [1-2 sentences weighing the current price of {current_price} against the analyst target of {target_mean}. Evaluate if the discount of {discount_pct} genuinely reflects a margin of safety or if the low/high multiple of {trailing_pe} carries specific structural sector doubts.]

📉 <b>Reverse DCF Stress-Test</b>: [1-2 sentences maximum analyzing what future growth rate the current market price embeds. State if this implied hurdle rate is reasonably achievable for the company or if it assumes an overly pessimistic/optimistic scenario.]

🛡️ <b>Zombie Detector</b>: [1-2 sentences assessing the quality of earnings and cash conversion. Verify if the operating cash flow fundamentally supports the reported net income, checking if the balance sheet layout is stable or overly capital-heavy.]

🚨 <b>ValueLens Verdict</b>: [1 single high-impact, balanced sentence concluding if this asset represents an authentic equity discount with a margin of safety, or if the underlying operational risks lean toward a value trap.]

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
        logger.error(f"DeepSeek completion failed for {ticker}: {e}")
        return f"⚠️ <b>Analysis Engine Timeout</b>: Unable to compile data layers for {ticker} at this time."


# ---------------------------------------------------------------------------
# Earnings sentiment layer
# ---------------------------------------------------------------------------

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