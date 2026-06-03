import os
import yfinance as yf
from openai import OpenAI
from dotenv import load_dotenv
import sqlite3

# Load environmental variables from .env file
load_dotenv()

# Initialize OpenAI client pointing to DeepSeek's API infrastructure
ai_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

def analyze_company(ticker: str, user_id: int) -> str:
    """
    Fetches financial data from Yahoo Finance and routes it to DeepSeek V4 
    Flash or Pro depending on the user's tier premium status.
    """
    try:
        # 1. Fetch user level from SQLite database
        conn = sqlite3.connect("valuelens.db")
        cursor = conn.cursor()
        cursor.execute("SELECT user_level FROM users WHERE user_id = ?", (user_id,))
        res = cursor.fetchone()
        conn.close()
        
        user_level = res[0] if res else 0
        
        # 2. Dynamic model routing based on user tier
        if user_level == 1:
            MODEL_NAME = "deepseek-v4-pro"
            system_style = (
                "You are an institutional Senior Quantitative Analyst specializing in Value Investing. "
                "Perform an advanced, cynical, and deeply analytical stress-test on the provided financial data. "
                "CRITICAL RULES:\n"
                "- Never use generic fluff, introductory filler, or clichés like 'the market is volatile'.\n"
                "- Thoroughly evaluate the interplay between debt, margins, and valuation multiples (P/E, PEG).\n"
                "- Be cold, mathematical, and concise.\n"
                "- Structure your answer using Markdown bullet points into three specific sections: "
                "[Metrics Synthesis], [Critical Risk Assessment], and [ValueLens Verdict]."
            )
        else:
            MODEL_NAME = "deepseek-v4-flash"
            system_style = (
                "You are a sharp, fast financial analyst. Provide a highly schematic, straight-to-the-point valuation. "
                "CRITICAL RULES:\n"
                "- Avoid pleasantries, generic disclaimers, or pre-programmed filler phrases.\n"
                "- Focus purely on raw numbers and structural facts.\n"
                "- Structure your answer using Markdown bullet points into three specific sections: "
                "[Metrics Synthesis], [Critical Risk Assessment], and [ValueLens Verdict]."
            )

        # 3. Retrieve raw market metrics via yfinance
        stock = yf.Ticker(ticker)
        info = stock.info
        
        raw_data = (
            f"Current Price: {info.get('currentPrice', 'N/A')}\n"
            f"Market Cap: {info.get('marketCap', 'N/A')}\n"
            f"Trailing P/E: {info.get('trailingPE', 'N/A')}\n"
            f"Forward P/E: {info.get('forwardPE', 'N/A')}\n"
            f"PEG Ratio: {info.get('pegRatio', 'N/A')}\n"
            f"Profit Margins: {info.get('profitMargins', 'N/A')}\n"
            f"Debt-to-Equity: {info.get('debtToEquity', 'N/A')}\n"
        )
        
        # 4. Execute the DeepSeek API call
        response = ai_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_style},
                {"role": "user", "content": f"Analyze the financial metrics for ticker: {ticker.upper()}.\nRaw Data:\n{raw_data}"}
            ]
        )
        
        # Prepend a premium or standard visual badge to the response
        badge = "⚡ *[ValueLens PRO Analysis]*\n\n" if user_level == 1 else "📊 *[ValueLens Standard Analysis]*\n\n"
        return badge + response.choices[0].message.content
        
    except Exception as e:
        return f"❌ Error analyzing ticker {ticker.upper()}: {str(e)}"
