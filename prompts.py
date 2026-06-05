# prompts.py

# ==========================================
# 1. CORE TELEGRAM UI LOCALIZATION STRINGS
# ==========================================
UI_STRINGS = {
    "en": {
        "welcome": "📊 **Welcome to ValueLens Bot!**\n\nYour quantitative analyst for Global Stocks.\n⚡ **PRO features activated for FREE!**\n\nType /help to see all available commands and features.\n\n⚠️ *Disclaimer: Educational purposes only. Not financial advice.*",
        "help": "📖 **ValueLens Bot | Command Reference**\n\n• /start - Initialize the bot and check registration.\n• /help - Show this interactive command guide.\n• /radar - Scan indices (e.g., S&P 500) for structural value anomalies.\n• /insider - View active real-time C-Suite corporate insider buying alerts.\n• /language - Change menu and analytical report output language.\n\n💡 **Direct Analysis:** Just type any stock ticker symbol (e.g., AAPL, MSFT) directly in chat to compile custom FLASH or PRO reports.",
        "maintenance": "🤖 **ValueLens | Maintenance**\n\nRunning nightly market data updates. Back online in a few minutes!",
        "radar_menu": "📡 **Value Radar**\nSelect a market index to scan for undervalued anomalies:",
        "radar_scan_depth": "📡 **Index:** {index}\nSelect scanning depth:",
        "radar_running": "📡 Scanning the **{index}** ({mode} mode)... Please wait.",
        "lang_menu": "🌐 **Language Settings**\nSelect your preferred language for menus and intelligence reports:",
        "lang_success": "✅ Language configuration updated to English!",
        "ticker_prompt": "🤖 **Ticker recognized:** `{ticker}`\nSelect the analysis depth:",
        "compiling_report": "🔍 Compiling {mode} report for **{ticker}**... Please wait.",
        "insider_init": "🚀 **First-Time Initialization**\n\nThe global insider database is currently empty. Launching initial scan across top 1,000 US equities...\n\n⏱️ Takes approx. 2 minutes. Results will appear automatically!",
        "insider_active": "🕵️‍♂️ **ValueLens INSIDER | Active US Signals**\nCompanies detected at structural lows backed by heavy C-Suite buying:\n\n",
        "insider_footer": "\n💡 *Analyze these tickers individually by sending them in chat to view the updated Reverse DCF.*",
        "invalid_ticker": "❌ Invalid ticker format.",
        "system_updating": "System updating...",
        "system_error": "❌ System error: {error}",
        "radar_error": "❌ Radar error: {error}",
        "insider_none": (
            "🚨 **ValueLens INSIDER | No Signals Found**\n\n"
            "Top 1,000 US companies scanned. Currently, **zero** entities match our high-conviction criteria "
            "(Price near 52-week lows + Aggressive corporate executive buying within the last 6 months).\n\n"
            "💡 **Verdict:** Market valuations are stretched; insiders are holding cash. Rescanning tonight.\n\n"
            "📢 **Join our Telegram Channel:** [ValueLens Insider Signals]({channel_link})\n"
            "When high-conviction anomalies are discovered, they are instantly broadcasted there! "
            "The channel also hosts our **Virtual Tracker Portfolio**, monitoring real-time performance and ROI "
            "of all past insider alerts from their exact detection date."
        )
    },
    "it": {
        "welcome": "📊 **Benvenuto su ValueLens Bot!**\n\nIl tuo analista quantitativo personale per le azioni globali.\n⚡ **Funzionalità PRO attivate GRATIS!**\n\nDigita /help per visualizzare la guida ai comandi disponibili.\n\n⚠️ *Disclaimer: Solo a scopo didattico. Nessun consiglio finanziario.*",
        "help": "📖 **ValueLens Bot | Guida ai Comandi**\n\n• /start - Inizializza il bot e verifica la registrazione.\n• /help - Mostra questa guida interattiva ai comandi.\n• /radar - Scansiona indici (es. S&P 500) alla ricerca di forti anomalie di valore.\n• /insider - Mostra gli acquisti recenti eseguiti dai C-Suite Insider aziendali.\n• /language - Modifica la lingua dei menu e dei report generati.\n\n💡 **Analisi Diretta:** Invia il codice ticker di un'azione (es. AAPL, MSFT) direttamente in chat per compilare report personalizzati in modalità FLASH o PRO.",
        "maintenance": "🤖 **ValueLens | Manutenzione**\n\nAggiornamento dei dati di mercato notturno in corso. Di nuovo online tra pochissimi minuti!",
        "radar_menu": "📡 **Value Radar**\nSeleziona un indice di mercato da scansionare alla ricerca di aziende a sconto:",
        "radar_scan_depth": "📡 **Indice:** {index}\nSeleziona la profondità di scansione:",
        "radar_running": "📡 Scansione dell'indice **{index}** (modalità {mode}) in corso... Attendere prego.",
        "lang_menu": "🌐 **Impostazioni Lingua**\nSeleziona la tua lingua preferita per l'interfaccia e i report finanziari dell'IA:",
        "lang_success": "✅ Configurazione della lingua aggiornata in Italiano!",
        "ticker_prompt": "🤖 **Ticker riconosciuto:** `{ticker}`\nSeleziona la profondità dell'analisi:",
        "compiling_report": "🔍 Compilazione del report {mode} per **{ticker}**... Attendere prego.",
        "insider_init": "🚀 **Inizializzazione Sistema**\n\nIl database interno è vuoto. Lancio della scansione iniziale sulle top 1.000 azioni statunitensi...\n\n⏱️ Richiede circa 2 minuti. I risultati appariranno qui automaticamente!",
        "insider_active": "🕵️‍♂️ **ValueLens INSIDER | Segnali US Attivi**\nAziende rilevate ai minimi strutturali supportate da forti acquisti di manager interni:\n\n",
        "insider_footer": "\n💡 *Analizza questi ticker individualmente inviandoli in chat per vedere il modello Reverse DCF aggiornato.*",
        "invalid_ticker": "❌ Formato ticker non valido.",
        "system_updating": "Aggiornamento sistema in corso...",
        "system_error": "❌ Errore di sistema: {error}",
        "radar_error": "❌ Errore Radar: {error}",
        "insider_none": (
            "🚨 **ValueLens INSIDER | Nessun Segnale Trovato**\n\n"
            "Scansionate le top 1.000 aziende US. Attualmente, **zero** società rispettano i nostri criteri di alta convinzione "
            "(Prezzo vicino ai minimi di 52 settimane + Acquisti aggressivi del management negli ultimi 6 mesi).\n\n"
            "💡 **Verdetto:** Le valutazioni di mercato sono tese; gli insider preferiscono tenere liquidità.\n\n"
            "📢 **Unisciti al nostro Canale Telegram:** [ValueLens Insider Signals]({channel_link})\n"
            "Non appena vengono rilevate anomalie ad alta convinzione, vengono pubblicate istantaneamente lì! "
            "Il canale ospita anche il nostro **Virtual Tracker Portfolio**, che monitora le performance reali e il ROI "
            "di tutti i segnali passati dalla loro esatta data di rilevamento."
        )
    }
}

# ==========================================
# 2. LLM RAW ENGINE RULES & CORE INSTRUCTIONS
# ==========================================
SAFETY_RULES = (
    "CRITICAL FORMATTING RULES:\n"
    "- DO NOT use the '$' symbol before any ticker names (e.g. write MSFT, not $MSFT).\n"
    "- ALWAYS use double asterisks (**) for bold text formatting. NEVER use a single asterisk (*).\n"
    "- NEVER use raw formatting characters or weird indentation arrows like ↳ or 🚀 inside bullet points.\n"
    "- Separate EVERY metric, header, and distinct commentary block with a double line break (\\n\\n).\n"
    "- Use clean paragraph spacing so the user can easily read the text on small mobile screens.\n"
    "\n\nCRITICAL TELEGRAM FORMATTING RULE:\n"
    "- NEVER use double underscores (__text__) for bolding or styling, because Telegram interprets them as UNDERLINE.\n"
    "- ALWAYS use double asterisks (**text**) exclusively for bold text.\n"
    "- NEVER use single underscores (_) for italics, use single asterisks (*) if absolutely needed.\n"
    "- Ensure all markdown tags are perfectly opened and closed. Do not leave trailing or unclosed formatting tags.\n"
)

LANGUAGE_RULES = {
    "it": "LANGUAGE RULE: You MUST write the complete analytical response, data commentary, labels, and final verdict exclusively in ITALIAN.\n",
    "en": "LANGUAGE RULE: You MUST write the complete analytical response exclusively in ENGLISH.\n"
}

# ==========================================
# 3. DEEPSEEK SYSTEM REPORT TEMPLATES
# ==========================================
ANALYZE_TEMPLATES = {
    "PRO": {
        "it": (
            "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
            "🔍 **ValueLens PRO | {TICKER} (Nome Azienda)**\n\n"
            "💰 **Prezzo Attuale:** X\n\n"
            "🎯 **Fair Value Stimato:** Y (Sconto/Premio %)\n\n"
            "📊 **METRICHE CHIAVE**\n\n"
            "• **P/E (Forward):** X.X\n  Commento: (Breve commento)\n\n"
            "• **Margine Netto:** X%\n  Commento: (Breve commento)\n\n"
            "• **Debito/Equity:** X%\n  Commento: (Breve commento)\n\n"
            "• **PEG Ratio:** X.X\n  Commento: (Breve commento)\n\n"
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
        ),
        "en": (
            "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
            "🔍 **ValueLens PRO | {TICKER} (Company Name)**\n\n"
            "💰 **Current Price:** X\n\n"
            "🎯 **Est. Fair Value:** Y (Discount/Premium %)\n\n"
            "📊 **KEY METRICS**\n\n"
            "• **P/E (Forward):** X.X\n  Insight: (Short comment)\n\n"
            "• **Net Margin:** X%\n  Insight: (Short comment)\n\n"
            "• **Debt/Equity:** X%\n  Insight: (Short comment)\n\n"
            "• **PEG Ratio:** X.X\n  Insight: (Short comment)\n\n"
            "🧮 **ADVANCED STRESS-TESTS**\n\n"
            "📈 **Reverse DCF (10y):** X% implied growth rate\n"
            "  Analysis: Analyze what CAGR the market expects at current price vs history.\n\n"
            "🧟 **Zombie Detector:** Pass/Fail (TTM Operating Cash Flow: X vs Net Income: Y)\n"
            "  Verification: Check if corporate cash backs accounting profits or signals high risk.\n\n"
            "🌡️─ **SENTIMENT & MARKET**\n\n"
            "• **Bull Sentiment:** 🟢/🟡/🔴 X% (Wall Street consensus)\n\n"
            "• **Insider Flow:** (Buying/Selling/Neutral)\n\n"
            "💡 **VALUELENS VERDICT**\n\n"
            "(Clear, cynical insight on pricing errors, growth illusions, or financial quality risks)."
        )
    },
    "FLASH": {
        "it": (
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
        ),
        "en": (
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
    }
}

# ==========================================
# 4. DEEPSEEK SYSTEM INDEX RADAR TEMPLATES
# ==========================================
RADAR_TEMPLATES = {
    "PRO": {
        "it": (
            "You are an elite quantitative asset manager scanning index components for structural discounts.\n"
            "STRICT FORMATTING RULE: NEVER use double underscores (__). NEVER open a bold tag (**) without closing it immediately on the same word.\n"
            "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
            "📡 **ValueLens Radar PRO | Analisi Indice {INDEX_NAME}**\n\n"
            "Componenti dell'indice scansionati. Rilevate azioni societarie a forte sconto strutturale:\n\n"
            "1️⃣ **{TICKER_1}**\n\n"
            "📉 **Sconto Stimato:** -X% rispetto al Fair Value\n\n"
            "⚠️ **Profilo di Debito:** Rapporto Debt/Equity al X%\n"
            "Analisi Debito: (Fornisci una valutazione chiara sulla stabilità finanziaria e rischio insolvenza)\n\n"
            "🧮 **Modello Reverse DCF:** X% Tasso di Crescita Implicito a 10 anni\n"
            "Aspettativa del Mercato: Il prezzo attuale assume una crescita dei flussi di cassa di appena il X% annuo.\n\n"
            "🧟 **Zombie Detector:** Passato/Fallito (Flusso di Cassa Operativo TTM: X vs Utile Netto: Y)\n"
            "Qualità degli Utili: Dimostra se i profitti contabili sono supportati da denaro reale.\n\n"
            "💬 **Catalizzatore di Valore:**\n(3-4 righe spiegando trend dei margini o vantaggi competitivi).\n\n"
            "2️⃣ **{TICKER_2}**\n\n"
            "📉 **Sconto Stimato:** -X% rispetto al Fair Value\n\n"
            "⚠️ **Profilo di Debito:** Rapporto Debt/Equity al X%\n"
            "🧮 **Modello Reverse DCF:** X% Tasso di Crescita Implicito a 10 anni\n"
            "🧟 **Zombie Detector:** Passato/Fallito\n"
            "💬 **Catalizzatore di Valore:**\n(Commento finale sui catalizzatori)."
        ),
        "en": (
            "You are an elite quantitative asset manager scanning index components for structural discounts.\n"
            "STRICT FORMATTING RULE: NEVER use double underscores (__). NEVER open a bold tag (**) without closing it immediately on the same word.\n"
            "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
            "📡 **ValueLens Radar PRO | {INDEX_NAME} Index Scan**\n\n"
            "Scanned index components. Found corporate equities trading at clear structural discounts:\n\n"
            "1️⃣ **{TICKER_1}**\n\n"
            "📉 **Est. Discount:** -X% vs Fair Value\n\n"
            "⚠️ **Financial Debt:** Debt/Equity ratio is X%\n"
            "Debt Analysis: (Provide an absolute assessment of debt risk and bankruptcy safety)\n\n"
            "🧮 **Reverse DCF Model:** X% Implied 10y Growth Rate\n"
            "Market Expectation: The current stock price assumes the company grows its cash flows by only X% annually.\n\n"
            "🧟 **Zombie Detector:** Pass/Fail (TTM Operating Cash Flow: X vs Net Income: Y)\n"
            "Earnings Quality: Proves accounting net profits are fully backed by tangible cash.\n\n"
            "💬 **Deep Value Catalyst:**\n(3-4 lines explaining margin trends or market pricing flaws).\n\n"
            "2️⃣ **{TICKER_2}**\n\n"
            "📉 **Est. Discount:** -X% vs Fair Value\n\n"
            "⚠️ **Financial Debt:** Debt/Equity ratio is X%\n"
            "🧮 **Reverse DCF Model:** X% Implied 10y Growth Rate\n"
            "🧟 **Zombie Detector:** Pass/Fail\n"
            "💬 **Deep Value Catalyst:**\n(Final macro or equity specific catalyst text block)."
        )
    },
    "FLASH": {
        "it": (
            "You are an elite quantitative asset manager scanning index components for structural discounts.\n"
            "STRICT ITALIAN OUTPUT TEMPLATE:\n\n"
            "⚡️ **ValueLens Radar FLASH | Scansione Rapida {INDEX_NAME}**\n\n"
            "Top alert di valore immediato supportati da flussi di cassa positiv:\n\n"
            "1️⃣ **{TICKER_1}**\n\n"
            "📉 **Sconto:** -X% rispetto al Fair Value\n\n"
            "⚠️ **Situazione Debitoria:** Debt/Equity: X%\n\n"
            "📊 **Valutazione Reverse DCF:** Tasso Implicito del X% CAGR\n\n"
            "🧟 **Qualità della Cassa:** Buona/Scarsa\n\n"
            "💡 **Innesco Operativo:** (1-2 righe che riassumono il motivo dello sconto).\n\n"
            "2️⃣ **{TICKER_2}**\n\n(Ripeti la stessa struttura pulita per la seconda azienda)"
        ),
        "en": (
            "You are an elite quantitative asset manager scanning index components for structural discounts.\n"
            "STRICT ENGLISH OUTPUT TEMPLATE:\n\n"
            "⚡️ **ValueLens Radar FLASH | {INDEX_NAME} Quick Scan**\n\n"
            "Top immediate value alerts backed by positive cash generation:\n\n"
            "1️⃣ **{TICKER_1}**\n\n"
            "📉 **Discount:** -X% vs Fair Value\n\n"
            "⚠️ **Debt Profile:** Debt/Equity: X%\n\n"
            "📊 **Reverse DCF Valuation:** X% Implied 10y CAGR\n\n"
            "🧟 **Cash Quality:** Good/Poor\n\n"
            "💡 **Actionable Trigger:** (1-2 lines summarizing cheap valuation and catalyst).\n\n"
            "2️⃣ **{TICKER_2}**\n\n(Apply the same quick flash layout structure)"
        )
    }
}

# ==========================================
# 5. PUBLIC TELEGRAM CHANNEL BROADCASTS
# ==========================================
CHANNEL_STRINGS = {
    "weekly_header": (
        "📋 **VALUELENS | WEEKLY EARNINGS DOSSIER** 📋\n"
        "*Institutional High-Cap Catalysts Monitored This Week:*\n\n"
    ),
    "weekly_item": (
        "• **{ticker}** ({company_name})\n"
        "  📅 Date: `{date}` | Cap: ${market_cap_billions}B\n\n"
    ),
    "weekly_footer": (
        "📡 *Sniper alerts with full DeepSeek AI Sentiment and Option Skew scores "
        "will broadcast 24 hours prior to execution windows.*"
    ),
    "sniper_alert": (
        "🎯 **VALUELENS SNIPER ALERT | {ticker}** 🎯\n"
        "🏢 **Company:** {company_name}\n"
        "📊 **Earnings Edge Score:** `{final_ees} / 100`\n"
        "⚖️ **Strategic Verdict:** {verdict}\n\n"
        "• *Quant Alignment:* Analysts targets show {quant_score} pts baseline factor.\n"
        "• *Smart Money Flow:* Options chain volume delta added {options_modifier} pts tracking.\n"
        "• *DeepSeek Intelligence:* Financial catalyst extraction rating at {ai_sentiment_score} pts.\n\n"
        "🤖 **ValueLens Historical Track Record Accuracy:** `{accuracy_str}`"
    ),
    "verdicts": {
        "bullish": "🟢 Strong Upside Surprise Potential",
        "bearish": "🔴 High Downside Risk Vector",
        "neutral": "🟡 Neutral Operational Horizon"
    }
}