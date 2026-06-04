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
    """Compiles single equity evaluations localized into English or Italian."""
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

        safety_rules = (
            "CRITICAL FORMATTING RULES:\n"
            "- DO NOT use the '$' symbol before any ticker names (e.g. write MSFT).\n"
            "- DO NOT use underscores (_) for italics. Use asterisks (*) for bold text formatting only.\n"
            "- Keep the output clean, without bracket frames around system text blocks.\n"
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
                    "🔍 **ValueLens PRO | TICKER (Nome Azienda)**\n"
                    "💰 **Prezzo Attuale:** X | 🎯 **Fair Value Stimato:** Y (Sconto/Premio %)\n\n"
                    "📊 **METRICHE CHIAVE**\n"
                    "• **P/E (Forward):** X.X (Breve commento)\n"
                    "• **Margine Netto:** X% (Breve commento)\n"
                    "• **Debito/Equity:** X% (Breve commento)\n"
                    "• **PEG Ratio:** X.X (Breve commento)\n\n"
                    "🧮 **STRESS-TEST AVANZATI**\n"
                    "• **Reverse DCF (10a):** X% tasso di crescita implicito (Spiega quale tasso si aspetta il mercato rispetto alla storia).\n"
                    "• **Zombie Detector:** (Confronta Operating Cash Flow vs Utile Netto per validare la qualità dei profitti contabilizzati).\n\n"
                    "🌡️ **SENTIMENT E MERCATO**\n"
                    "• **Sentiment Analisti:** 🟢/🟡/🔴 X% (Consensus di Wall Street)\n"
                    "• **Flusso Insider:** (Acquisti/Vendite/Neutrale)\n\n"
                    "💡 **VERDETTO VALUELENS**\n"
                    "(Max 4 righe. Analisi cinica e diretta su anomalie di prezzo, illusioni di crescita o rischi finanziari)."
                )
            else:
                system_style = safety_rules + (
                    "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
                    "🔍 **ValueLens PRO | TICKER (Company Name)**\n"
                    "💰 **Current Price:** X | 🎯 **Est. Fair Value:** Y (Discount/Premium %)\n\n"
                    "📊 **KEY METRICS**\n"
                    "• **P/E (Forward):** X.X (Short comment)\n"
                    "• **Net Margin:** X% (Short comment)\n"
                    "• **Debt/Equity:** X% (Short comment)\n"
                    "• **PEG Ratio:** X.X (Short comment)\n\n"
                    "🧮 **ADVANCED STRESS-TESTS**\n"
                    "• **Reverse DCF (10y):** X% implied growth rate (Analyze what CAGR the market expects at current price vs history).\n"
                    "• **Zombie Detector:** (Compare Operating Cash Flow vs Net Income. Check if cash backs profits or corporate risk).\n\n"
                    "🌡️ **SENTIMENT & MARKET**\n"
                    "• **Bull Sentiment:** 🟢/🟡/🔴 X% (Wall Street consensus)\n"
                    "• **Insider Flow:** (Buying/Selling/Neutral)\n\n"
                    "💡 **VALUELENS VERDICT**\n"
                    "(Max 4 lines. Clear, cynical insight on pricing errors, growth illusions, or financial quality risks)."
                )
        else:
            MODEL_NAME = "deepseek-v4-flash"
            if lang == "it":
                system_style = safety_rules + (
                    "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
                    "⚡️ **ValueLens FLASH | TICKER (Nome Azienda)**\n"
                    "💰 **Prezzo Attuale:** X | 🔄 **Trend (7g):** X%\n\n"
                    "📊 **SNAPSHOT DI MERCATO**\n"
                    "• **Sentiment Analisti:** 🟢/🟡/🔴 X%\n"
                    "• **Supporto Chiave:** X\n"
                    "• **Valutazione:** (Metrica core + Breve commento)\n"
                    "• **Controllo Rischi Avanzato:** (Sintesi in 1 riga tra Reverse DCF e stato Cash Flow/Zombie).\n\n"
                    "💡 **SINTESI OPERATIVA**\n"
                    "(Max 2 righe. Takeaway immediato e azionabile)."
                )
            else:
                system_style = safety_rules + (
                    "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
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

def get_value_radar(target_index: str, mode: str, lang: str = "en") -> str:
    """Scans systematic indices for corporate pricing discrepancies translated natively."""
    try:
        model_choice = "deepseek-v4-pro" if mode == 'PRO' else "deepseek-v4-flash"
        
        base_rules = (
            "You are an elite quantitative asset manager scanning index components for structural discounts.\n"
            "CRITICAL FORMATTING RULES:\n"
            "- DO NOT use the '$' symbol before ticker identities (e.g. write AAPL).\n"
            "- DO NOT use underscores (_) for italics. Use asterisks (*) for bold text formatting only.\n"
            "- DO NOT wrap text output elements inside square brackets [ ] or piping symbols |.\n"
        )
        if lang == "it":
            base_rules += "LANGUAGE RULE: You MUST write the entire system layout, descriptions, and commentaries in ITALIAN.\n"
        else:
            base_rules += "LANGUAGE RULE: You MUST write the entire system layout in ENGLISH.\n"
        
        if mode == 'PRO':
            if lang == "it":
                system_style = base_rules + (
                    "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
                    "📡 **ValueLens Radar PRO | Analisi Indice {INDEX_NAME}**\n"
                    "Componenti dell'indice scansionati. Rilevate 2 azioni societarie a forte sconto strutturale:\n\n"
                    "1️⃣ **TICKER (Nome Azienda)**\n"
                    "📉 **Sconto Stimato:** -X% rispetto al Fair Value\n"
                    "⚠️ **Profilo di Debito:** Rapporto Debt/Equity al X% (Fornisci una valutazione chiara sulla stabilità finanziaria e rischio insolvenza)\n"
                    "🧮 **Modello Reverse DCF:** X% Tasso di Crescita Implicito a 10 anni\n"
                    "   ↳ *Aspettativa di Mercato:* Il prezzo attuale scommette che l'azienda crescerà i suoi flussi di cassa solo del X% annuo nei prossimi 10 anni. Se il business reale supera questa bassa barriera, l'azione è gravemente sottovalutata.\n"
                    "🧟 **Zombie Detector:** Passato/Fallito (Flusso di Cassa Operativo TTM: $X vs Utile Netto: $Y)\n"
                    "   ↳ *Qualità degli Utili:* Dimostra se i profitti contabili sono supportati da denaro reale generato dalle operazioni commerciali, escludendo rischi di aziende artificiali sorrette solo da debito.\n"
                    "💬 **Catalizzatore di Valore:** (3-4 righe spiegando trend dei margini, inefficienze di prezzo del mercato o vantaggi competitivi stabili).\n\n"
                    "2️⃣ **TICKER (Company Name)**\n"
                    "(Applica lo stesso identico blocco pulito per la seconda azienda)"
                )
            else:
                system_style = base_rules + (
                    "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
                    "📡 **ValueLens Radar PRO | {INDEX_NAME} Index Scan**\n"
                    "Scanned index components. Found 2 corporate equities trading at clear structural discounts:\n\n"
                    "1️⃣ **TICKER (Company Name)**\n"
                    "📉 **Est. Discount:** -X% vs Fair Value\n"
                    "⚠️ **Financial Debt:** Debt/Equity ratio is X% (Provide an absolute assessment of debt risk and bankruptcy safety)\n"
                    "🧮 **Reverse DCF Model:** X% Implied 10y Growth Rate\n"
                    "   ↳ *Market Expectation:* The current stock price assumes the company grows its cash flows by only X% annually over the next decade. If actual operations exceed this low hurdle rate, the equity is severely mispriced.\n"
                    "🧟 **Zombie Detector:** Pass/Fail (TTM Operating Cash Flow: $X vs Net Income: $Y)\n"
                    "   ↳ *Earnings Quality:* Proves accounting net profits are fully backed by tangible cash coming through corporate operations, verifying it is a healthy business and not a dying debt-fueled entity.\n"
                    "💬 **Deep Value Catalyst:** (3-4 lines explaining margin trends, market pricing flaws, or business model moats providing a deep-value buffer).\n\n"
                    "2️⃣ **TICKER (Company Name)**\n"
                    "(Apply the exact same clear block format for the second stock asset)"
                )
        else:
            if lang == "it":
                system_style = base_rules + (
                    "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
                    "⚡️ **ValueLens Radar FLASH | Scansione Rapida {INDEX_NAME}**\n"
                    "Top 2 alert di valore immediato supportati da flussi di cassa positivi:\n\n"
                    "1️⃣ **TICKER (Nome Azienda)**\n"
                    "📉 **Sconto:** -X% rispetto al Fair Value\n"
                    "⚠️ **Situazione Debitoria:** Debt/Equity: X% (Sicuro/Cautela)\n"
                    "📊 **Valutazione Reverse DCF:** Tasso Implicito a 10 anni del X% CAGR (Il mercato sta impostando aspettative di crescita estremamente basse)\n"
                    "🧟 **Qualità della Cassa:** Buona/Scarsa (I flussi di cassa operativi coprono in modo sicuro i profitti contabili)\n"
                    "💡 **Innesco Operativo:** (1-2 righe che riassumono il motivo dello sconto e il catalizzatore di mercato a breve termine).\n\n"
                    "2️⃣ **TICKER (Nome Azienda)**\n"
                    "(Applica lo stesso identico blocco pulito per la seconda azienda)"
                )
            else:
                system_style = base_rules + (
                    "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
                    "⚡️ **ValueLens Radar FLASH | {INDEX_NAME} Quick Scan**\n"
                    "Top 2 immediate value alerts backed by positive cash generation:\n\n"
                    "1️⃣ **TICKER (Company Name)**\n"
                    "📉 **Discount:** -X% vs Fair Value\n"
                    "⚠️ **Debt Profile:** Debt/Equity: X% (Safe/Caution)\n"
                    "📊 **Reverse DCF Valuation:** X% Implied 10y CAGR (The growth bar set by current market pricing is exceptionally low)\n"
                    "🧟 **Cash Quality:** Good/Poor (Real operating cash flow securely backs or fails accounting profits)\n"
                    "💡 **Actionable Trigger:** (1-2 lines summarizing why the company is trading cheap and the near-term structural market catalyst).\n\n"
                    "2️⃣ **TICKER (Company Name)**\n"
                    "(Apply the exact same clear block format for the second stock asset)"
                )

        response = ai_client.chat.completions.create(
            model=model_choice,
            messages=[
                {"role": "system", "content": system_style},
                {"role": "user", "content": f"Scan the {target_index} index, extract 2 undervalued corporate stocks, and run structural stress-tests."}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ Error running Value Radar on {target_index}: {str(e)}"