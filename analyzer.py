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
    """Fetches financial data and routes it to DeepSeek with Advanced Stress-Tests."""
    try:
        yf_ticker = "BTC-USD" if ticker.upper() == "BTC" else ticker.upper()
        stock = yf.Ticker(yf_ticker)
        info = stock.info or {}
        
        # Check if the asset is a cryptocurrency to exclude it from corporate stress-tests
        is_crypto = yf_ticker.endswith("-USD") or yf_ticker == "BTC-USD"
        
        # Defensive fetch for Operating Cash Flow and Net Income (Corporate only)
        ocf_val = "N/A"
        ni_val = "N/A"
        
        if not is_crypto:
            try:
                cf = stock.cashflow
                fin = stock.financials
                if cf is not None and not cf.empty and 'Operating Cash Flow' in cf.index:
                    ocf_val = cf.loc['Operating Cash Flow'].iloc[0]
                if fin is not None and not fin.empty and 'Net Income' in fin.index:
                    ni_val = fin.loc['Net Income'].iloc[0]
            except Exception:
                pass

        # Base formatting rules to prevent Telegram parsing errors and unwanted cashtags
        safety_rules = (
            "CRITICAL FORMATTING RULES:\n"
            "- DO NOT use the '$' symbol before any ticker (e.g. write MSFT, never $MSFT).\n"
            "- DO NOT use underscores (_) for italics. Use asterisks (*) for bold only.\n"
            "- Keep the output clean, without brackets around titles.\n"
        )

        if mode == 'PRO':
            MODEL_NAME = "deepseek-v4-pro"  # Replace with "deepseek-chat" if using standard official API endpoints
            system_style = safety_rules + (
                "You are an elite quantitative analyst. Provide a concise, punchy PRO analysis.\n"
                "If 'Is Crypto' is True, write 'N/A (Crypto Asset)' under the ADVANCED STRESS-TESTS block.\n"
                "STRICT TEMPLATE:\n"
                "🔍 **ValueLens PRO | TICKER (Company Name)**\n"
                "💰 **Current Price:** X | 🎯 **Est. Fair Value:** Y (Discount/Premium %)\n\n"
                "📊 **KEY METRICS**\n"
                "• **P/E (Forward):** X.X (Short comment)\n"
                "• **Net Margin:** X% (Short comment)\n"
                "• **Debt/Equity:** X% (Short comment)\n"
                "• **PEG Ratio:** X.X (Short comment)\n\n"
                "🧮 **ADVANCED STRESS-TESTS**\n"
                "• **Reverse DCF (10y):** X% implied growth rate (Analyze what CAGR the market expects at current price vs history).\n"
                "• **Zombie Detector:** (Compare Operating Cash Flow vs Net Income. Check if cash backs the profits or if it's a fake/zombie corporate risk).\n\n"
                "🌡️ **SENTIMENT & MARKET**\n"
                "• **Bull Sentiment:** 🟢/🟡/🔴 X% (Wall Street consensus)\n"
                "• **Insider Flow:** (Buying/Selling/Neutral)\n\n"
                "💡 **VALUELENS VERDICT**\n"
                "(Max 4 lines. Clear, cynical insight on pricing errors, growth illusions, or financial quality risks)."
            )
        else:
            MODEL_NAME = "deepseek-v4-flash"  # Replace with "deepseek-chat" if using standard official API endpoints
            system_style = safety_rules + (
                "You are a fast market analyst. Provide an immediate FLASH snapshot.\n"
                "If 'Is Crypto' is True, write 'N/A (Crypto)' in the Risk Check bullet.\n"
                "STRICT TEMPLATE:\n"
                "⚡️ **ValueLens FLASH | TICKER (Company Name)**\n"
                "💰 **Current Price:** X | 🔄 **Trend (7d):** X%\n\n"
                "📊 **SNAPSHOT**\n"
                "• **Bull Sentiment:** 🟢/🟡/🔴 X% (Short comment)\n"
                "• **Key Support:** X\n"
                "• **Valuation:** (Core metric) (Short comment)\n"
                "• **Advanced Risk Check:** (1-line combo of Reverse DCF implied growth expectation and Cash Flow/Zombie status).\n\n"
                "💡 **SYNTHESIS**\n"
                "(Max 2 lines. Immediate actionable takeaway)."
            )

        # Robust extraction utilizing 'or' chains to capture missing values or explicit None types safely
        price_val = info.get('currentPrice') or info.get('regularMarketPrice') or 'N/A'
        market_cap = info.get('marketCap') or 'N/A'
        trailing_pe = info.get('trailingPE') or 'N/A'
        forward_pe = info.get('forwardPE') or 'N/A'
        peg_ratio = info.get('pegRatio') or 'N/A'
        profit_margins = info.get('profitMargins') or 'N/A'
        debt_to_equity = info.get('debtToEquity') or 'N/A'

        raw_data = (
            f"Current Price: {price_val}\n"
            f"Market Cap: {market_cap}\n"
            f"Trailing P/E: {trailing_pe}\n"
            f"Forward P/E: {forward_pe}\n"
            f"PEG Ratio: {peg_ratio}\n"
            f"Profit Margins: {profit_margins}\n"
            f"Debt-to-Equity: {debt_to_equity}\n"
            f"Operating Cash Flow (OCF): {ocf_val}\n"
            f"Net Income: {ni_val}\n"
            f"Is Crypto: {is_crypto}\n"
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
    """Scans an index for undervalued stocks forcing Reverse DCF and Zombie metrics, excluding crypto."""
    try:
        model_choice = "deepseek-v4-pro" if mode == 'PRO' else "deepseek-v4-flash"
        
        base_rules = (
            "You are a Value Screener. Find 2 highly capitalized corporate stocks in the requested index "
            "that are structurally undervalued. CRITICAL: EXCLUDE any cryptocurrencies or digital assets (e.g. no BTC).\n"
            "For each chosen corporate stock, you MUST execute a Reverse DCF calculation (implied 10-year growth expectations) "
            "and a Zombie Detector check (compare Net Income vs real Operating Cash Flow to prove earnings quality).\n"
            "CRITICAL FORMATTING: DO NOT use the '$' symbol before tickers (e.g. write AAPL). "
            "DO NOT use underscores (_) for italics. Use asterisks (*) for bold only."
        )
        
        if mode == 'PRO':
            system_style = base_rules + (
                "\nSTRICT TEMPLATE:\n"
                "📡 **Value Radar PRO | Market Anomalies Scan**\n"
                "I found 2 large-cap companies trading below intrinsic value:\n\n"
                "1️⃣ **TICKER (Company Name)**\n"
                "📉 **Est. Discount:** -X% vs Fair Value.\n"
                "🧮 **Stress-Tests:** [Reverse DCF CAGR: X%] | [Zombie Check: Pass/Fail based on OCF vs Net Income]\n"
                "💬 **Deep Analysis:** (3-4 lines explaining margins, catalysts, and why the market growth expectation is wrong).\n\n"
                "2️⃣ **TICKER (Company Name)**\n"
                "📉 **Est. Discount:** -X% vs Fair Value.\n"
                "🧮 **Stress-Tests:** (Reverse DCF & Zombie details).\n"
                "💬 **Deep Analysis:** (Explanation)."
            )
        else:
            system_style = base_rules + (
                "\nSTRICT TEMPLATE:\n"
                "📡 **Value Radar FLASH | Quick Scan**\n"
                "Top 2 undervalued alerts (excluding crypto):\n\n"
                "1️⃣ **TICKER (Company Name)**\n"
                "📉 **Discount:** -X%\n"
                "⚡️ **Risk Checks:** [Implied Growth: X%] | [Cash Quality: Good/Poor]\n"
                "💡 **Trigger:** (1 line summary of why it's cheap and the entry catalyst).\n\n"
                "2️⃣ **TICKER (Company Name)**\n"
                "📉 **Discount:** -X%\n"
                "⚡️ **Risk Checks:** (Growth & Cash status).\n"
                "💡 **Trigger:** (1 line summary)."
            )

        response = ai_client.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": system_style},
                {"role": "user", "content": f"Scan the {target_index} index, find 2 corporate anomalies, and compute stress-tests."}
            ]
        )
        return response.choices[0].message.content
        
    except Exception as e:
        return f"❌ Error running Value Radar on {target_index}: {str(e)}"