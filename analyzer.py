import os
import logging
import yfinance as yf
from openai import OpenAI
from dotenv import load_dotenv
import prompts

load_dotenv()
logger = logging.getLogger("ValueLensAnalyzer")

ai_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

def analyze_company(ticker: str, mode: str, lang: str = "en") -> str:
    """Compiles single equity evaluations with highly scannable paragraph spaces and clean Markdown."""
    try:
        logger.info(f"Launching {mode} analysis routine for ticker asset: {ticker.upper()}")
        yf_ticker = "BTC-USD" if ticker.upper() == "BTC" else ticker.upper()
        stock = yf.Ticker(yf_ticker)
        info = stock.info or {}
        is_crypto = yf_ticker.endswith("-USD") or yf_ticker == "BTC-USD"
        
        ocf_val, ni_val = "N/A", "N/A"
        if not is_crypto:
            try:
                cf = stock.cashflow
                fin = stock.financials
                if cf is not None and not cf.empty:
                    ocf_keys = ['Operating Cash Flow', 'OperatingCashFlow', 'Total Cash From Operating Activities']
                    for key in ocf_keys:
                        if key in cf.index:
                            ocf_val = cf.loc[key].iloc[0]
                            break
                if fin is not None and not fin.empty:
                    ni_keys = ['Net Income', 'NetIncome', 'Net Income Common Stockholders']
                    for key in ni_keys:
                        if key in fin.index:
                            ni_val = fin.loc[key].iloc[0]
                            break
            except Exception as fe:
                logger.warning(f"Financial statement extraction skipped for {ticker.upper()}: {fe}")

        system_style = (
            prompts.SAFETY_RULES + 
            prompts.LANGUAGE_RULES.get(lang, prompts.LANGUAGE_RULES["en"]) + 
            prompts.ANALYZE_TEMPLATES[mode][lang]
        )
        
        MODEL_NAME = "deepseek-v4-pro" if mode == 'PRO' else "deepseek-v4-flash"
        
        custom_params = {}
        if mode == 'PRO':
            custom_params = {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high"
            }
        
        raw_data = (
            f"Current Price: {info.get('currentPrice', 'N/A')}\n"
            f"Market Cap: {info.get('marketCap', 'N/A')}\n"
            f"Trailing P/E: {info.get('trailingPE', 'N/A')}\n"
            f"Forward P/E: {info.get('forwardPE', 'N/A')}\n"
            f"PEG Ratio: {info.get('pegRatio', 'N/A')}\n"
            f"Profit Margins: {info.get('profitMargins', 'N/A')}\n"
            f"Debt-to-Equity: {info.get('debtToEquity', 'N/A')}\n"
            f"Operating Cash Flow (OCF): {ocf_val}\n"
            f"Net Income: {ni_val}\n"
            f"Is Crypto: {is_crypto}\n"
        )
        
        logger.info(f"Dispatching payload context to DeepSeek endpoint model: {MODEL_NAME}")
        response = ai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_style.format(TICKER=ticker.upper())},
                {"role": "user", "content": f"Generate {mode} report for {ticker.upper()}.\nData:\n{raw_data}"}
            ],
            extra_body=custom_params if custom_params else None
        )
        
        final_output = response.choices[0].message.content
        final_output = final_output.replace("__", "**")
        final_output = final_output.replace("<u>", "").replace("</u>", "")
        
        return final_output
    except Exception as e:
        logger.error(f"Critical execution failure during stock analysis for {ticker.upper()}: {e}")
        return f"❌ Error analyzing {ticker.upper()}: {str(e)}"

def get_value_radar(target_index: str, mode: str, lang: str = "en") -> str:
    """Scans systematic indices and outputs beautifully spaced, non-congested asset reports."""
    try:
        logger.info(f"Initializing systematic Index Radar scan sequence for target: {target_index} ({mode})")
        model_choice = "deepseek-v4-pro" if mode == 'PRO' else "deepseek-v4-flash"
        
        system_style = (
            prompts.SAFETY_RULES + 
            prompts.LANGUAGE_RULES.get(lang, prompts.LANGUAGE_RULES["en"]) + 
            prompts.RADAR_TEMPLATES[mode][lang]
        )

        custom_params = {}
        if mode == 'PRO':
            custom_params = {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high"
            }

        logger.info(f"Executing index analysis completion using model framework: {model_choice}")
        response = ai_client.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": system_style.format(INDEX_NAME=target_index, TICKER_1="INTC", TICKER_2="F")},
                {"role": "user", "content": f"Scan the {target_index} index, extract 2 undervalued corporate stocks, and run structural stress-tests."}
            ],
            extra_body=custom_params if custom_params else None
        )
        
        final_output = response.choices[0].message.content
        final_output = final_output.replace("__", "**")
        final_output = final_output.replace("<u>", "").replace("</u>", "")
        
        return final_output
    except Exception as e:
        logger.error(f"Error caught running Value Radar on financial index {target_index}: {e}")
        return f"❌ Error running Value Radar on {target_index}: {str(e)}"