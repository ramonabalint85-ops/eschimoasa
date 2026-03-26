# 📋 CHANGELOG

## 🚀 v2.1 - Cache & Resilienza (26 Marzo 2026)

### ✨ Nuove Funzionalità
- **Cache Persistente su Disco** 💾
  - I dati scaricati rimangono salvati in `.yfinance_cache/`
  - Accesso istantaneo su ticker già visti (0.01s vs 2-3s)
  - Timeout di 24 ore per mantenere i dati freschi

- **Retry Intelligente con Exponential Backoff** 🔄
  - Ritenta automaticamente se la connessione fallisce
  - Attese progressive: 1s → 2s → 4s
  - Massimo 3 tentativi prima di fallimento

- **Throttling Automatico** ⏸️
  - 2 secondi di attesa tra richieste successive
  - Evita rate limiting e sovraccarichi della API
  - Protegge sia l'app che il server yfinance

- **Fallback Graceful** 📦
  - Se nessun dato fresco disponibile, usa cache scaduta
  - Messaggio all'utente: "Usando cache di X giorni fa"
  - Meglio dati vecchi che nulla!

- **Bottone Svuota Cache** 🗑️
  - Nel footer dell'app per cancellare cache locale
  - Forza il download fresco da yfinance
  - Utile se bloccati dal rate limiting

### 🔧 Miglioramenti Tecnici
- Aggiunto `@lru_cache` per memorizzazione in memoria sessione
- Nuovo file `CACHE_SYSTEM.md` con documentazione completa
- Funzioni di utilità:
  - `is_cache_valid()` - Controlla freshness della cache
  - `load_from_cache()` - Carica da disco
  - `save_to_cache()` - Salva su disco
  - `retry_with_backoff()` - Retry logic con backoff esponenziale

### 📊 Benchmark
| Scenario | Prima | Dopo | Miglioramento |
|----------|-------|------|---------------|
| Primo caricamento AAPL | 2-3s | 2-3s | Uguale (nuovo) |
| Secondo caricamento AAPL | ❌ Bloccato (1-15min) | 0.01s | **∞x (da cache)** |
| Terzo caricamento TSLA | ❌ Bloccato | 2-3s | **Possibile** |
| Quarto caricamento TSLA | ❌ Bloccato | 0.01s | **∞x (da cache)** |

### 📝 File Modificati
- `app.py` - Aggiunto sistema cache, retry logic
- `requirements.txt` - Aggiunto `requests`
- `README.md` - Aggiunto sezione cache e troubleshooting
- [Nuovo] `CACHE_SYSTEM.md` - Documentazione dettagliata cache
- [Nuovo] `test_cache_system.py` - Script test cache

### ⚠️ Breaking Changes
Nessuno - completamente backwards compatible

---

## v2.0 - Integrazione yfinance (26 Marzo 2026)

### ✨ Nuove Funzionalità
- **Campo Input Ticker** 📊
  - Inserisci il ticker dell'azienda (es: AAPL, TSLA)
  - Caricamento automatico da yfinance

- **Dati Aziendali Automatici** 📈
  - Paese, Settore GICS, Industria
  - Attivo Totale, Ricavi, OpEx, CapEx
  - Numero di dipendenti

- **Precompilazione Intelligente** 🧠
  - Ricavi e OpEx si riempiono automaticamente dal ticker
  - Paese mappato nella lista disponibile
  - Dati finanziari pronti per l'analisi

- **Dashboard Informazioni Società** 💡
  - 8 KPI principal di visualizzati
  - Link diretto al sito web dell'azienda
  - Status badge con fonte dei dati

- **Export Avanzato** 📥
  - CSV: Stress test in formato tabulare
  - Excel: Report con 2 fogli (Profilo + Analisi)
  - Timestamp automatico sui file

### 📝 File Creati
- [Nuovo] `config.py` - Configurazioni globali
- [Nuovo] `test_yfinance.py` - Test integrazione
- [Nuovo] `README.md` - Documentazione utente
- [Nuovo] `TECHNICAL_SUMMARY.md` - Dettagli tecnici
- [Nuovo] `USAGE_EXAMPLES.md` - Esempi pratici

### 🔧 Tech Stack
- yfinance per dati in tempo reale
- openpyxl per export Excel
- Caching con @lru_cache
- Gestione errori robust

---

## v1.0 - Base Foundation (XX Marzo 2026)

### ✨ Funzionalità
- Stress test su scenari climatici IPCC
- 3 scenari di proiezione (Net Zero, Shock, BAU)
- Grafici interattivi con Plotly
- Calcoli di impatto tassa carbonio
- Export CSV

---

## 📊 Statistiche di Sviluppo

| Versione | Features | Files | Lines of Code | Dependencies |
|----------|----------|-------|----------------|---|
| v1.0 | 5 | 1 | ~150 | 3 |
| v2.0 | 13 | 5 | ~400 | 5 |
| v2.1 | 18 | 7 | ~550 | 6 |

---

## 🎯 Roadmap Futuri

### Prossime Versione (v2.2)
- [ ] Cache compresso (gzip)
- [ ] Precaricamento smart di ticker frequenti
- [ ] Notifiche quando cache va in scadenza
- [ ] Dark mode per Streamlit

### Medium Term (v3.0)
- [ ] Multi-language support (IT, EN, DE, FR)
- [ ] Dashboard per confrontare più ticker
- [ ] Integrazione dati ESG reali
- [ ] Analisi di scenari personalizzati

### Long Term
- [ ] Archivio storico dei prezzi carbonio
- [ ] Predizioni con ML
- [ ] API pubblica per integrazione
- [ ] App mobile (React Native)

---

## 🔗 Link Utili

- [Documentazione Cache](CACHE_SYSTEM.md)
- [Riepilogo Tecnico](TECHNICAL_SUMMARY.md)
- [Esempi di Utilizzo](USAGE_EXAMPLES.md)

---

**Ultimo Aggiornamento**: 26 Marzo 2026  
**Maintainer**: CarbonRisk Team  
**License**: Open Source (MIT)
