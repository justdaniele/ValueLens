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
    """
    Fetches financial data and routes it to DeepSeek.
    mode can be 'PRO' or 'FLASH'.
    """
    try:
        # Handle crypto routing for yfinance
        yf_ticker = "BTC-USD" if ticker.upper() == "BTC" else ticker.upper()
        
        stock = yf.Ticker(yf_ticker)
        info = stock.info
        
        # Determine model and prompt based on user selection
        if mode == 'PRO':
            MODEL_NAME = "deepseek-v4-pro"
            system_style = (
                "You are an elite quantitative analyst. Provide a concise, punchy PRO analysis. "
                "STRICT FORMATTING REQUIRED:\n"
                "🔍 **[ValueLens PRO] | $TICKER (Company Name)**\n"
                "💰 **Current Price:** $X | 🎯 **Est. Fair Value:** $Y (Discount/Premium %)\n\n"
                "📊 **KEY METRICS**\n"
                "• **P/E (Forward):** X.X (Short comment)\n"
                "• **Net Margin:** X% (Short comment)\n"
                "• **Debt/Equity:** X% (Short comment)\n"
                "• **PEG Ratio:** X.X (Short comment)\n\n"
                "🌡️ **SENTIMENT & MARKET**\n"
                "• **Bull Sentiment:** 🟢/🟡/🔴 X% (Wall Street consensus)\n"
                "• **Insider Flow:** (Buying/Selling/Neutral)\n\n"
                "💡 **VALUELENS VERDICT**\n"
                "(Max 4 lines. Clear, cynical, actionable insight on the pricing error or risk)."
            )
        else:
            MODEL_NAME = "deepseek-v4-flash"
            system_style = (
                "You are a fast market analyst. Provide an immediate, snapshot-style FLASH analysis. "
                "STRICT FORMATTING REQUIRED:\n"
                "⚡️ **[ValueLens FLASH] | $TICKER (Company Name)**\n"
                "💰 **Current Price:** $X | 🔄 **Trend (7d):** X%\n\n"
                "📊 **SNAPSHOT**\n"
                "• **Bull Sentiment:** 🟢/🟡/🔴 X% (Short comment)\n"
                "• **Key Support:** $X\n"
                "• **Valuation Metric:** (e.g. MVRV for BTC, or P/E for stocks) (Short comment)\n\n"
                "💡 **SYNTHESIS**\n"
                "(Max 2 lines. Immediate trend takeaway)."
            )

        # Retrieve raw market metrics
        raw_data = (
            f"Current Price: {info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))}\n"
            f"Market Cap: {info.get('marketCap', 'N/A')}\n"
            f"Trailing P/E: {info.get('trailingPE', 'N/A')}\n"
            f"Forward P/E: {info.get('forwardPE', 'N/A')}\n"
            f"PEG Ratio: {info.get('pegRatio', 'N/A')}\n"
            f"Profit Margins: {info.get('profitMargins', 'N/A')}\n"
            f"Debt-to-Equity: {info.get('debtToEquity', 'N/A')}\n"
            f"52 Week High: {info.get('fiftyTwoWeekHigh', 'N/A')}\n"
            f"52 Week Low: {info.get('fiftyTwoWeekLow', 'N/A')}\n"
        )
        
        response = ai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_style},
                {"role": "user", "content": f"Generate the {mode} report for ticker: {ticker.upper()}.\nData:\n{raw_data}"}
            ]
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        return f"❌ Error analyzing {ticker.upper()}: {str(e)}"

def get_value_radar(target_index: str) -> str:
    """
    Uses DeepSeek to act as a screener and identify undervalued anomalies in a specific index.
    """
    try:
        system_style = (
            "You are a Value Investing Screener. Your job is to identify 2 large-cap stocks "
            "within the user's requested index that are currently fundamentally undervalued or mispriced by the market. "
            "Do not use generic disclaimers. STRICT FORMATTING REQUIRED:\n"
            "📡 **[Value Radar] | Market Anomalies Scan**\n"
            "_I found 2 highly capitalized companies currently trading below their estimated intrinsic value:_\n\n"
            "1️⃣ **$TICKER (Company Name)**\n"
            "📉 **Est. Discount:** -X% vs Fair Value.\n"
            "💬 *Why:* (Concise, cynical explanation of why the market is wrong, focusing on margins, P/E, and catalysts).\n\n"
            "2️⃣ **$TICKER (Company Name)**\n"
            "📉 **Est. Discount:** -X% vs Fair Value.\n"
            "💬 *Why:* (Explanation)."
        )
        
        response = ai_client.chat.completions.create(
            model="deepseek-v4-pro", # Always use PRO for the radar scanner
            messages=[
                {"role": "system", "content": system_style},
                {"role": "user", "content": f"Scan the {target_index} index and find 2 undervalued anomalies."}
            ]
        )
        return response.choices[0].message.content
        
    except Exception as e:
        return f"❌ Error running Value Radar on {target_index}: {str(e)}"