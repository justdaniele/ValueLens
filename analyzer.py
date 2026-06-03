import os
import yfinance as yf
from openai import OpenAI
from dotenv import load_dotenv

# Load environmental variables
load_dotenv()

ai_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

def analyze_company(ticker: str, mode: str) -> str:
    """Fetches financial data and routes it to DeepSeek."""
    try:
        yf_ticker = "BTC-USD" if ticker.upper() == "BTC" else ticker.upper()
        stock = yf.Ticker(yf_ticker)
        info = stock.info
        
        # Base formatting rules to prevent Telegram parsing errors and unwanted cashtags
        safety_rules = (
            "CRITICAL FORMATTING RULES:\n"
            "- DO NOT use the '$' symbol before any ticker (e.g. write MSFT, never $MSFT).\n"
            "- DO NOT use underscores (_) for italics. Use asterisks (*) for bold only.\n"
            "- Keep the output clean, without brackets around titles.\n"
        )

        if mode == 'PRO':
            MODEL_NAME = "deepseek-v4-pro"
            system_style = safety_rules + (
                "You are an elite quantitative analyst. Provide a concise, punchy PRO analysis.\n"
                "STRICT TEMPLATE:\n"
                "🔍 **ValueLens PRO | TICKER (Company Name)**\n"
                "💰 **Current Price:** X | 🎯 **Est. Fair Value:** Y (Discount/Premium %)\n\n"
                "📊 **KEY METRICS**\n"
                "• **P/E (Forward):** X.X (Short comment)\n"
                "• **Net Margin:** X% (Short comment)\n"
                "• **Debt/Equity:** X% (Short comment)\n"
                "• **PEG Ratio:** X.X (Short comment)\n\n"
                "🌡️ **SENTIMENT & MARKET**\n"
                "• **Bull Sentiment:** 🟢/🟡/🔴 X% (Wall Street consensus)\n"
                "• **Insider Flow:** (Buying/Selling/Neutral)\n\n"
                "💡 **VALUELENS VERDICT**\n"
                "(Max 4 lines. Clear, cynical insight on pricing errors or risks)."
            )
        else:
            MODEL_NAME = "deepseek-v4-flash"
            system_style = safety_rules + (
                "You are a fast market analyst. Provide an immediate FLASH snapshot.\n"
                "STRICT TEMPLATE:\n"
                "⚡️ **ValueLens FLASH | TICKER (Company Name)**\n"
                "💰 **Current Price:** X | 🔄 **Trend (7d):** X%\n\n"
                "📊 **SNAPSHOT**\n"
                "• **Bull Sentiment:** 🟢/🟡/🔴 X% (Short comment)\n"
                "• **Key Support:** X\n"
                "• **Valuation:** (Core metric) (Short comment)\n\n"
                "💡 **SYNTHESIS**\n"
                "(Max 2 lines. Immediate actionable takeaway)."
            )

        raw_data = (
            f"Current Price: {info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))}\n"
            f"Market Cap: {info.get('marketCap', 'N/A')}\n"
            f"Trailing P/E: {info.get('trailingPE', 'N/A')}\n"
            f"Forward P/E: {info.get('forwardPE', 'N/A')}\n"
            f"PEG Ratio: {info.get('pegRatio', 'N/A')}\n"
            f"Profit Margins: {info.get('profitMargins', 'N/A')}\n"
            f"Debt-to-Equity: {info.get('debtToEquity', 'N/A')}\n"
        )
        
        response = ai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_style},
                {"role": "user", "content": f"Generate {mode} report for {ticker.upper()}.\nData:\n{raw_data}"}
            ]
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        return f"❌ Error analyzing {ticker.upper()}: {str(e)}"

def get_value_radar(target_index: str, mode: str) -> str:
    """Scans an index for undervalued stocks using either FLASH or PRO depth."""
    try:
        model_choice = "deepseek-v4-pro" if mode == 'PRO' else "deepseek-v4-flash"
        
        base_rules = (
            "You are a Value Screener. Find 2 highly capitalized stocks in the requested index "
            "that are undervalued. CRITICAL: DO NOT use the '$' symbol before tickers (e.g. write AAPL). "
            "DO NOT use underscores (_)."
        )
        
        if mode == 'PRO':
            system_style = base_rules + (
                "\nSTRICT TEMPLATE:\n"
                "📡 **Value Radar PRO | Market Anomalies Scan**\n"
                "I found 2 large-cap companies trading below intrinsic value:\n\n"
                "1️⃣ **TICKER (Company Name)**\n"
                "📉 **Est. Discount:** -X% vs Fair Value.\n"
                "💬 **Deep Analysis:** (3-4 lines explaining margins, P/E, and catalysts).\n\n"
                "2️⃣ **TICKER (Company Name)**\n"
                "📉 **Est. Discount:** -X% vs Fair Value.\n"
                "💬 **Deep Analysis:** (Explanation)."
            )
        else:
            system_style = base_rules + (
                "\nSTRICT TEMPLATE:\n"
                "📡 **Value Radar FLASH | Quick Scan**\n"
                "Top 2 undervalued alerts:\n\n"
                "1️⃣ **TICKER (Company Name)**\n"
                "📉 **Discount:** -X%\n"
                "💡 **Trigger:** (1 line summary of why it's cheap).\n\n"
                "2️⃣ **TICKER (Company Name)**\n"
                "📉 **Discount:** -X%\n"
                "💡 **Trigger:** (1 line summary)."
            )

        response = ai_client.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": system_style},
                {"role": "user", "content": f"Scan the {target_index} index and find 2 anomalies."}
            ]
        )
        return response.choices[0].message.content
        
    except Exception as e:
        return f"❌ Error running Value Radar on {target_index}: {str(e)}"