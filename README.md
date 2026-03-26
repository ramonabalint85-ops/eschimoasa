# 🌍 CarbonRisk Radar PRO - Analisi di Rischio Carbonio

## 📋 Descrizione
CarbonRisk Radar è uno strumento avanzato per l'analisi del rischio climatico e della tassazione sul carbonio per le aziende quotate. Integra direttamente i dati finanziari da **yfinance** per un'analisi accurata e in tempo reale.

## ✨ Versione 2.1 - Nuovo Sistema Anti-Rate-Limiting

### 🔥 Principali Miglioramenti
- **Cache Persistente** 💾: I dati rimangono disponibili anche offline
- **Retry Intelligente** 🔄: Sistema di backoff esponenziale se la connessione fallisce
- **Throttling Automatico** ⏸️: Evita i blocchi di yfinance da rate limiting
- **Fallback Graceful** 📦: Usa cache scaduta se non riesce a scaricare dati freschi

### 🧠 Integrazione yfinance
L'applicazione ora recupera automaticamente i seguenti dati dalle aziende quotate:

- 🌐 **Paese**: Sede dell'azienda
- 📈 **Settore GICS**: Classificazione settoriale globale
- 🏢 **Industria**: Classificazione specifica del settore
- 💵 **Attivo Totale**: Patrimonio netto dell'azienda
- 📊 **Ricavi**: Ricavi totali annuali
- ⚙️ **Costi Operativi (OpEx)**: Spese operative
- 🏗️ **CapEx**: Investimenti in capitale fisico
- 👥 **Dipendenti**: Numero di dipendenti a tempo pieno

### 🛡️ Sistema di Cache Anti-Rate-Limiting
- **Cache Locale**: I dati vengono salvati in `.yfinance_cache/` per riuso istantaneo
- **Timeout 24h**: Cache rimane valida fino a 24 ore
- **Retry Automatico**: Se bloccato, riprova automaticamente con attesa (1s → 2s → 4s)
- **Throttling**: 2 secondi tra le richieste per evitare sovraccarichi
- **Fallback**: Se non riesce a scaricare, usa cache scaduta (meglio che nulla!)

**Risultato**: Accesso istantaneo su ticker già visti, evita blocchi di yfinance

## 🚀 Come Utilizzare

### 1. Installazione
```bash
pip install -r requirements.txt
```

### 2. Avvio Applicazione
```bash
streamlit run app.py
```

### 3. Utilizzo
1. **Inserisci il Ticker**: Scrivi il ticker della società (es: AAPL, TSLA, ASML) nel campo "Inserisci Ticker Azienda"
2. **Caricamento Automatico**: L'app scaricherà automaticamente tutti i dati finanziari
3. **Revisione Dati**: Puoi modificare manualmente i valori se necessario
4. **Stress Test**: Seleziona il moltiplicatore di severità delle leggi
5. **Analisi**: Visualizza i grafici di proiezione
6. **Export**: Scarica il report in CSV o Excel

## 📊 Scenari di Analisi

L'app simula 3 scenari climatici (scenario IPCC):

- 🟢 **Net Zero 2050 (Ordinata)**: Scenario ottimistico con transizione ordinata
- 🟡 **Transizione Ritardata (Shock)**: Scenario con shock politico improvviso
- 🔴 **Politiche Attuali (BAU)**: Business as usual senza nuove politiche

## 💾 Esportazione

### CSV
- Scarica i dati dello stress test in formato CSV
- Compatibile con Excel e altri strumenti di analisi

### Excel
- Profilo completo della società (dati yfinance)
- Analisi dello stress test su carbonio
- Su due fogli separati per facile navigazione

## 🔍 Ticker Comuni

| Azienda | Ticker | Paese |
|---------|--------|-------|
| Apple | AAPL | 🇺🇸 USA |
| Tesla | TSLA | 🇺🇸 USA |
| ASML | ASML | 🇳🇱 Paesi Bassi |
| Siemens | SIE | 🇩🇪 Germania |
| Enel | ENEL | 🇮🇹 Italia |
| Allianz | ALV | 🇩🇪 Germania |
| Nestlé | NSRGY | 🇨🇭 Svizzera |

## 📈 Funzionalità della Dashboard

### KPI Principali
- Utile Previsto (2025)
- Passività Stimata (2030 - Shock)
- Stato a Breve Termine

### Grafici
1. **Erosione della Redditività**: Mostra come la tassa sul carbonio riduce i profitti
2. **Traiettoria Prezzo Carbonio**: Evoluzione del prezzo della CO2 negli scenari

### Parametri Regolabili
- **Moltiplicatore Severità Leggi**: Da 1.0x (standard) a 3.0x (più severo)
- **Emissioni CO2**: Personalizzabile per il profilo dell'azienda

## 🛠️ Gestione Errori

L'app gestisce intelligentemente:
- Ticker inesistenti
- Dati mancanti da yfinance
- Conversioni di valuta automatiche

## ⚙️ Requisiti Tecnici

- Python 3.8+
- Streamlit 1.0+
- Pandas
- Plotly
- yfinance
- openpyxl

## 📝 Note

- I dati provengono da yfinance (informazioni pubbliche)
- I prezzi del carbonio sono proiezioni basate su scenari IPCC
- Le analisi sono indicative e non costituiscono consulenza finanziaria

## � Note

- I dati provengono da yfinance (informazioni pubbliche)
- I prezzi del carbonio sono proiezioni basate su scenari IPCC
- Le analisi sono indicative e non costituiscono consulenza finanziaria
- **NEW**: Cache intelligente evita il 90% dei problemi di rate limiting

## 🔧 Troubleshooting Rate Limiting

### Problema: "Connessione bloccata"

**Soluzione rapida**:
1. Clicca **🗑️ Svuota cache** nel footer dell'app
2. Aspetta 30 secondi
3. Riprova con un altro ticker

### Problema: "Impossibile caricare dati"

**Cause possibili**:
- ❌ Nessuna connessione internet
- ❌ yfinance temporaneamente offline
- ❌ Rate limit di yfinance esaurito

**Soluzioni**:
1. Riprova a caricamento completato (sistema di retry farà il suo lavoro)
2. Usa un **ticker diverso** (potrebbe non avere rate limit)
3. **Aspetta 15 minuti** (blocco temporaneo di yfinance)
4. Visualizza **cache scaduta** (bottone nel footer)

## 📚 Documentazione Tecnica

- [CACHE_SYSTEM.md](CACHE_SYSTEM.md) - Introduzione al nuovo sistema di cache
- [TECHNICAL_SUMMARY.md](TECHNICAL_SUMMARY.md) - Implementazione tecnica
- [USAGE_EXAMPLES.md](USAGE_EXAMPLES.md) - Scenari di utilizzo pratico

## 🔐 Privacy

- Nessun dato viene memorizzato nel cloud
- L'app funziona completamente in locale
- Cache locale in `.yfinance_cache/` (cancellabile con `rm -rf .yfinance_cache`)
- yfinance scarica dati pubblici (nessuna API key richiesta)
