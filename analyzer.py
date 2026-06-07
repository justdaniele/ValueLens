import os
import logging
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("ValueLensAnalyzer")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# Initialize the OpenAI client pointing to DeepSeek infrastructure
if DEEPSEEK_API_KEY:
    ai_client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1"
    )
else:
    ai_client = None
    logger.warning("DEEPSEEK_API_KEY missing. AI generation will be unavailable.")

# --- CENTRALIZED SYSTEM PROMPT (ROBUST HTML OUTPUT) ---
ANALYSIS_SYSTEM_PROMPT = """You are ValueLens, an elite quantitative hedge fund analyst writing daily intelligence briefings.

STRICT FORMATTING RULES:
- Use ONLY standard HTML tags for formatting: <b>bold</b>, <i>italic</i>, <code>code</code>.
- NEVER use Markdown syntax like **bold**, __underscores__, or backticks.
- Separate physical sections cleanly using double line breaks.
- Be extremely concise, highly cynical, and purely data-driven. Detect financial smoke and mirrors.
"""

def analyze_company(ticker: str, mode: str = "PRO", lang: str = "en", company_info: dict = None) -> str:
    """
    Generates a high-conviction financial analysis report grounded in real-time market data.
    Communicates via DeepSeek Chat Completion API.
    """
    if not ai_client:
        return f"<b>[ {ticker} ]</b> Analysis aborted: DeepSeek API Client uninitialized."

    # Process and ground real-time quantitative metrics to eliminate AI hallucinations
    financial_context = ""
    if company_info and isinstance(company_info, dict):
        current_price = company_info.get("currentPrice") or company_info.get("regularMarketPrice") or "N/A"
        target_mean = company_info.get("targetMeanPrice") or "N/A"
        trailing_pe = company_info.get("trailingPE") or company_info.get("forwardPE") or "N/A"
        price_to_book = company_info.get("priceToBook") or "N/A"
        market_cap = company_info.get("marketCap") or 0
        
        market_cap_formatted = f"${market_cap:,}" if market_cap else "N/A"
        
        financial_context = f"""
CRITICAL REAL-TIME MARKET DATA FOR CURRENT SESSION (MUST USE THESE EXACT NUMBERS):
- Current Market Price: ${current_price}
- Analyst Target Mean Price: ${target_mean}
- Valuation Multiplier (P/E Ratio): {trailing_pe}
- Price to Book (P/B Value): {price_to_book}
- Market Capitalization Size: {market_cap_formatted}
"""

    mode_instruction = (
        "Perform an advanced institutional-grade deep dive." 
        if mode == "PRO" else 
        "Generate a high-level concise FLASH validation assessment."
    )
    
    language_instruction = (
        "Write the entire report response in Italian." 
        if lang == "it" else 
        "Write the entire report response in English."
    )

    user_prompt = f"""Analyze target asset: {ticker}
Configuration Mode: {mode_instruction}
Output Language: {language_instruction}
{financial_context}

Incorporate these exact analytical dimensions in your final HTML layout:
1. <b>Price Context</b>: Current market price versus calculated intrinsic terminal value. Mention the exact real market data supplied.
2. <b>Reverse DCF Stress-Test</b>: What implied cash flow growth rate is embedded within current valuations? Is it realistic?
3. <b>Zombie Detector</b>: Verify cash conversion efficiency. Does Operating Cash Flow fundamentally back stated Net Income?
4. <b>ValueLens Verdict</b>: Direct, cynical final assessment. Is this an authentic equity discount or a classic value trap?

Structure the response clean and readable using only <b>, <i>, and line breaks. Do not include raw markdown wrappers.
"""

    try:
        response = ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            max_tokens=900
        )
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        logger.error(f"DeepSeek core completion engine failed for asset {ticker}: {e}")
        return f"⚠️ <b>Analysis Engine Timeout</b>: Unable to compile data layers for {ticker} at this time."

def generate_earnings_sentiment_layer(ticker: str, company_name: str) -> int:
    """
    Analyzes systemic sentiment positioning 48h prior to an earnings release.
    Returns a directional score multiplier ranging from -40 to +40.
    """
    if not ai_client:
        return 0

    prompt = f"""Analyze the short-term forward-looking risk profile for {company_name} ({ticker}) ahead of their upcoming earnings release.
Return a single integer score strictly between -40 (extremely bearish expectations, guidance downside risk) and +40 (extremely bullish positioning, high probability of surprise).

CRITICAL: Your response must contain ONLY the raw number. Do not include words, symbols, explanation or punctuation.
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
        logger.warning(f"Could not compute AI sentiment modifier for {ticker}: {e}. Defaulting to neutral (0).")
        return 0