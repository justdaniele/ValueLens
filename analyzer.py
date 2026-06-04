import os
import yfinance as yf
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

ai_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

def analyze_company(ticker: str, mode: str, lang: str = "en") -> str:
    """Compiles single equity evaluations with highly scannable paragraph spaces and clean Markdown."""
    try:
        yf_ticker = "BTC-USD" if ticker.upper() == "BTC" else ticker.upper()
        stock = yf.Ticker(yf_ticker)
        info = stock.info or {}
        is_crypto = yf_ticker.endswith("-USD") or yf_ticker == "BTC-USD"
        
        ocf_val, ni_val = "N/A", "N/A"
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

        # Critical layout rules enforced on the LLM engine to guarantee UI scannability
        safety_rules = (
            "CRITICAL FORMATTING RULES:\n"
            "- DO NOT use the '$' symbol before any ticker names (e.g. write MSFT, not $MSFT).\n"
            "- ALWAYS use double asterisks (**) for bold text formatting. NEVER use a single asterisk (*).\n"
            "- NEVER use raw formatting characters or weird indentation arrows like ↳ or 🚀 inside bullet points.\n"
            "- Separate EVERY metric, header, and distinct commentary block with a double line break (\\n\\n).\n"
            "- Use clean paragraph spacing so the user can easily read the text on small mobile screens.\n"
        )
        
        if lang == "it":
            safety_rules += "LANGUAGE RULE: You MUST write the complete analytical response, data commentary, labels, and final verdict exclusively in ITALIAN.\n"
        else:
            safety_rules += "LANGUAGE RULE: You MUST write the complete analytical response exclusively in ENGLISH.\n"

        if mode == 'PRO':
            MODEL_NAME = "deepseek-v4-pro"
            if lang == "it":
                system_style = safety_rules + (
                    "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
                    "🔍 **ValueLens PRO | {TICKER} (Nome Azienda)**\n\n"
                    "💰 **Prezzo Attuale:** X\n\n"
                    "🎯 **Fair Value Stimato:** Y (Sconto/Premio %)\n\n"
                    "📊 **METRICHE CHIAVE**\n\n"
                    "• **P/E (Forward):** X.X\n"
                    "  Commento: (Breve commento)\n\n"
                    "• **Margine Netto:** X%\n"
                    "  Commento: (Breve commento)\n\n"
                    "• **Debito/Equity:** X%\n"
                    "  Commento: (Breve commento)\n\n"
                    "• **PEG Ratio:** X.X\n"
                    "  Commento: (Breve commento)\n\n"
                    "🧮 **STRESS-TEST AVANZATI**\n\n"
                    "📈 **Reverse DCF (10 anni):** X% tasso di crescita implicito\n"
                    "  Analisi: Spiega quale tasso si aspetta il mercato rispetto alla storia aziendale.\n\n"
                    "🧟 **Zombie Detector:** Passato/Fallito (Flusso di Cassa Operativo TTM: X vs Utile Netto: Y)\n"
                    "  Verifica: Spiega se il denaro reale generato copre i profitti contabili o se ci sono rischi.\n\n"
                    "🌡️ **SENTIMENT E MERCATO**\n\n"
                    "• **Sentiment Analisti:** 🟢/🟡/🔴 X% (Wall Street consensus)\n\n"
                    "• **Flusso Insider:** (Acquisti/Vendite/Neutrale)\n\n"
                    "💡 **VERDETTO VALUELENS**\n\n"
                    "(Analisi cinica, diretta e distanziata su anomalie di prezzo o rischi strutturali)."
                )
            else:
                system_style = safety_rules + (
                    "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
                    "🔍 **ValueLens PRO | {TICKER} (Company Name)**\n\n"
                    "💰 **Current Price:** X\n\n"
                    "🎯 **Est. Fair Value:** Y (Discount/Premium %)\n\n"
                    "📊 **KEY METRICS**\n\n"
                    "• **P/E (Forward):** X.X\n"
                    "  Insight: (Short comment)\n\n"
                    "• **Net Margin:** X%\n"
                    "  Insight: (Short comment)\n\n"
                    "• **Debt/Equity:** X%\n"
                    "  Insight: (Short comment)\n\n"
                    "• **PEG Ratio:** X.X\n"
                    "  Insight: (Short comment)\n\n"
                    "🧮 **ADVANCED STRESS-TESTS**\n\n"
                    "📈 **Reverse DCF (10y):** X% implied growth rate\n"
                    "  Analysis: Analyze what CAGR the market expects at current price vs history.\n\n"
                    "🧟 **Zombie Detector:** Pass/Fail (TTM Operating Cash Flow: X vs Net Income: Y)\n"
                    "  Verification: Check if corporate cash backs accounting profits or signals high risk.\n\n"
                    "🌡️ **SENTIMENT & MARKET**\n\n"
                    "• **Bull Sentiment:** 🟢/🟡/🔴 X% (Wall Street consensus)\n\n"
                    "• **Insider Flow:** (Buying/Selling/Neutral)\n\n"
                    "💡 **VALUELENS VERDICT**\n\n"
                    "(Clear, cynical insight on pricing errors, growth illusions, or financial quality risks)."
                )
        else:
            MODEL_NAME = "deepseek-v4-flash"
            if lang == "it":
                system_style = safety_rules + (
                    "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
                    "⚡️ **ValueLens FLASH | {TICKER} (Nome Azienda)**\n\n"
                    "💰 **Prezzo Attuale:** X\n\n"
                    "🔄 **Trend (7 giorni):** X%\n\n"
                    "📊 **SNAPSHOT DI MERCATO**\n\n"
                    "• **Sentiment Analisti:** 🟢/🟡/🔴 X%\n\n"
                    "• **Supporto Chiave:** X\n\n"
                    "• **Valutazione Core:** (Metrica core + breve commento)\n\n"
                    "• **Controllo Rischi Rapido:** (Sintesi tra Reverse DCF e stato Cash Flow).\n\n"
                    "💡 **SINTESI OPERATIVA**\n\n"
                    "(Takeaway immediato e azionabile)."
                )
            else:
                system_style = safety_rules + (
                    "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
                    "⚡️ **ValueLens FLASH | {TICKER} (Company Name)**\n\n"
                    "💰 **Current Price:** X\n\n"
                    "🔄 **Trend (7d):** X%\n\n"
                    "📊 **SNAPSHOT**\n\n"
                    "• **Bull Sentiment:** 🟢/🟡/🔴 X%\n\n"
                    "• **Key Support:** X\n\n"
                    "• **Valuation:** (Core metric insight)\n\n"
                    "• **Advanced Risk Check:** (1-line combo of Reverse DCF growth expectation and Cash Flow status).\n\n"
                    "💡 **SYNTHESIS**\n\n"
                    "(Immediate actionable takeaway)."
                )

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
                {"role": "system", "content": system_style.format(TICKER=ticker.upper())},
                {"role": "user", "content": f"Generate {mode} report for {ticker.upper()}.\nData:\n{raw_data}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Error analyzing {ticker.upper()}: {str(e)}"

def get_value_radar(target_index: str, mode: str, lang: str = "en") -> str:
    """Scans systematic indices and outputs beautifully spaced, non-congested asset reports."""
    try:
        model_choice = "deepseek-v4-pro" if mode == 'PRO' else "deepseek-v4-flash"
        
        base_rules = (
            "You are an elite quantitative asset manager scanning index components for structural discounts.\n"
            "CRITICAL FORMATTING RULES:\n"
            "- DO NOT use the '$' symbol before ticker identities (e.g. write AAPL, not $AAPL).\n"
            "- ALWAYS use double asterisks (**) for bold text formatting. NEVER use a single asterisk (*).\n"
            "- NEVER use sub-bullets or raw indentation formatting markers like ↳.\n"
            "- Use double line breaks (\\n\\n) generously between sections and companies to build clean paragraphs.\n"
            "- Separate different corporate stock profiles using a clear markdown horizontal line (---).\n"
        )
        if lang == "it":
            base_rules += "LANGUAGE RULE: You MUST write the entire system layout, descriptions, and commentaries in ITALIAN.\n"
        else:
            base_rules += "LANGUAGE RULE: You MUST write the entire system layout in ENGLISH.\n"
        
        if mode == 'PRO':
            if lang == "it":
                system_style = base_rules + (
                    "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
                    "📡 **ValueLens Radar PRO | Analisi Indice {INDEX_NAME}**\n\n"
                    "Componenti dell'indice scansionati. Rilevate azioni societarie a forte sconto strutturale:\n\n"
                    "---"
                    "\n\n"
                    "1️⃣ **{TICKER_1} (Nome Azienda 1)**\n\n"
                    "📉 **Sconto Stimato:** -X% rispetto al Fair Value\n\n"
                    "⚠️ **Profilo di Debito:** Rapporto Debt/Equity al X%\n"
                    "Analisi Debito: (Fornisci una valutazione chiara sulla stabilità finanziaria e rischio insolvenza)\n\n"
                    "🧮 **Modello Reverse DCF:** X% Tasso di Crescita Implicito a 10 anni\n"
                    "Aspettativa del Mercato: Il prezzo attuale assume una crescita dei flussi di cassa di appena il X% annuo. Se il business reale supera questa bassa barriera, l'azione è gravemente sottovalutata.\n"
                    "🧟 **Zombie Detector:** Passato/Fallito (Flusso di Cassa Operativo TTM: X vs Utile Netto: Y)\n"
                    "Qualità degli Utili: Dimostra se i profitti contabili sono supportati da denaro reale generato dalle operazioni commerciali.\n\n"
                    "💬 **Catalizzatore di Valore:**\n"
                    "(3-4 righe spiegando trend dei margini o vantaggi competitivi stabili).\n\n"
                    "---"
                    "\n\n"
                    "2️⃣ **{TICKER_2} (Nome Azienda 2)**\n\n"
                    "📉 **Sconto Stimato:** -X% rispetto al Fair Value\n\n"
                    "⚠️ **Profilo di Debito:** Rapporto Debt/Equity al X%\n"
                    "Analisi Debito: (Valutazione stabilità finanziaria)\n\n"
                    "🧮 **Modello Reverse DCF:** X% Tasso di Crescita Implicito a 10 anni\n"
                    "Aspettativa del Mercato: (Commento sulla crescita implicita).\n\n"
                    "🧟 **Zombie Detector:** Passato/Fallito\n"
                    "Qualità degli Utili: (Commento sulla cassa reale).\n\n"
                    "💬 **Catalizzatore di Valore:**\n"
                    "(Commento finale sui catalizzatori di mercato)."
                )
            else:
                system_style = base_rules + (
                    "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
                    "📡 **ValueLens Radar PRO | {INDEX_NAME} Index Scan**\n\n"
                    "Scanned index components. Found corporate equities trading at clear structural discounts:\n\n"
                    "---"
                    "\n\n"
                    "1️⃣ **{TICKER_1} (Company Name 1)**\n\n"
                    "📉 **Est. Discount:** -X% vs Fair Value\n\n"
                    "⚠️ **Financial Debt:** Debt/Equity ratio is X%\n"
                    "Debt Analysis: (Provide an absolute assessment of debt risk and bankruptcy safety)\n\n"
                    "🧮 **Reverse DCF Model:** X% Implied 10y Growth Rate\n"
                    "Market Expectation: The current stock price assumes the company grows its cash flows by only X% annually over the next decade. If actual operations exceed this low hurdle rate, the equity is severely mispriced.\n\n"
                    "🧟 **Zombie Detector:** Pass/Fail (TTM Operating Cash Flow: X vs Net Income: Y)\n"
                    "Earnings Quality: Proves accounting net profits are fully backed by tangible cash coming through corporate operations.\n\n"
                    "💬 **Deep Value Catalyst:**\n"
                    "(3-4 lines explaining margin trends, market pricing flaws, or business model moats providing a deep-value buffer).\n\n"
                    "---"
                    "\n\n"
                    "2️⃣ **{TICKER_2} (Company Name 2)**\n\n"
                    "📉 **Est. Discount:** -X% vs Fair Value\n\n"
                    "⚠️ **Financial Debt:** Debt/Equity ratio is X%\n"
                    "Debt Analysis: (Assessment of corporate stability and balance sheet protection).\n\n"
                    "🧮 **Reverse DCF Model:** X% Implied 10y Growth Rate\n"
                    "Market Expectation: (Insight into current price implied assumptions).\n\n"
                    "🧟 **Zombie Detector:** Pass/Fail\n"
                    "Earnings Quality: (Verification of operational cash flows against accounting income).\n\n"
                    "💬 **Deep Value Catalyst:**\n"
                    "(Final macro or equity specific catalyst text block)."
                )
        else:
            if lang == "it":
                system_style = base_rules + (
                    "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
                    "⚡️ **ValueLens Radar FLASH | Scansione Rapida {INDEX_NAME}**\n\n"
                    "Top alert di valore immediato supportati da flussi di cassa positivi:\n\n"
                    "---"
                    "\n\n"
                    "1️⃣ **{TICKER_1} (Nome Azienda 1)**\n\n"
                    "📉 **Sconto:** -X% rispetto al Fair Value\n\n"
                    "⚠️ **Situazione Debitoria:** Debt/Equity: X% (Sicuro/Cautela)\n\n"
                    "📊 **Valutazione Reverse DCF:** Tasso Implicito del X% CAGR\n\n"
                    "🧟 **Qualità della Cassa:** Buona/Scarsa\n\n"
                    "💡 **Innesco Operativo:** (1-2 righe che riassumono il motivo dello sconto e il catalizzatore).\n\n"
                    "---"
                    "\n\n"
                    "2️⃣ **{TICKER_2} (Nome Azienda 2)**\n\n"
                    "(Ripeti la stessa struttura pulita per la seconda azienda)"
                )
            else:
                system_style = base_rules + (
                    "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
                    "⚡️ **ValueLens Radar FLASH | {INDEX_NAME} Quick Scan**\n\n"
                    "Top immediate value alerts backed by positive cash generation:\n\n"
                    "---"
                    "\n\n"
                    "1️⃣ **{TICKER_1} (Company Name 1)**\n\n"
                    "📉 **Discount:** -X% vs Fair Value\n\n"
                    "⚠️ **Debt Profile:** Debt/Equity: X% (Safe/Caution)\n\n"
                    "📊 **Reverse DCF Valuation:** X% Implied 10y CAGR\n\n"
                    "🧟 **Cash Quality:** Good/Poor\n\n"
                    "💡 **Actionable Trigger:** (1-2 lines summarizing why the company is trading cheap and near-term catalyst).\n\n"
                    "---"
                    "\n\n"
                    "2️⃣ **{TICKER_2} (Company Name 2)**\n\n"
                    "(Apply the same quick flash layout structure)"
                )

        response = ai_client.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": system_style.format(INDEX_NAME=target_index, TICKER_1="INTC", TICKER_2="F")},
                {"role": "user", "content": f"Scan the {target_index} index, extract 2 undervalued corporate stocks, and run structural stress-tests."}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Error running Value Radar on {target_index}: {str(e)}"