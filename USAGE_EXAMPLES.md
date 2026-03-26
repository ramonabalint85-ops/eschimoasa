# 🎯 Esempi di Utilizzo - CarbonRisk Radar

## Scenario 1: Analisi di Apple Inc. (AAPL)

### Input
1. Inserisci nel campo "Inserisci Ticker Azienda": **AAPL**
2. Sistema carica automaticamente:
   - Settore: Technology
   - Industria: Consumer Electronics
   - Paesi: Stati Uniti → Selezionato automaticamente
   - Ricavi: ~€435B (precompilato)
   - Dipendenti: 150,000

### Cosa Accade
- ✅ Dashboard mostra dati aziendali in tempo reale
- ✅ Stress test calcola impatto tassa carbonio
- ✅ Grafici mostrano proiezioni profittabilità
- ✅ Export include dati societari + analisi

---

## Scenario 2: Analisi di ASML (ASML) - Produttore Semiconduttori

### Input
1. Inserisci: **ASML**
2. Settore: Technology
3. Industria: Semiconductor Equipment
4. Paese: Netherlands → Mappato a "Paesi Bassi"

### Focus Analisi
- Settore tecnologico = emissioni strategiche
- Paese (Paesi Bassi) = fattore carbonio 1.5x
- Ricavi: ~€32.67B
- Dipendenti: 43,520

### Output atteeso
- 2030 Shock scenario: Passività signifi­cativa
- Margine di profit ridotto con tassa carbonio
- CapEx impatto rilevante su profittabilità

---

## Scenario 3: PMI Italiana non Quotata

### Quando Non Usi yfinance
Se stai analizzando una piccola azienda non quotata:

1. **Non inserire ticker** (o immettere uno inesistente)
2. Usa i **campi manuali**:
   - Ricavi: 5 milioni €
   - OpEx: 2 milioni €
   - Emissioni: 500 tonnellate CO2
   - Paese: Italia (seleziona da dropdown)

### Risultato
- Analisi funziona normalmente
- Italia ha moltiplicatore carbonio 1.4x
- Impatto più elevato su margini

---

## Scenario 4: Confronto Accelerato - 3 Ticker

### Processo Rapido
```
1. Analizza AAPL   → Scarica report  ✅
2. Analizza TSLA   → Scarica report  ✅  
3. Analizza MSFT   → Scarica report  ✅
```

### Confronto
Capisci quale settore è più resiliente:
- **Tech vs Industrial**: Diversa sensitivity
- **USA vs EU**: Diversi fattori carbonio
- **Large Cap vs SMid Cap**: Scale differences

---

## Scenario 5: Stress Test Personalizzato

### Input Parametri
1. Ticker: **SAP**
2. Moltiplicatore Severità: **2.5x** (shock massimo)

### Analisi
- SAP (Germania): Settore Technology
- Mit 2.5x severità: Scenario pessimistico
- 2030 Shock: Riduzione profitti signifi­cativa
- Visibilità su rischio estremo

---

## Scenario 6: Export per Due Diligence

### Caso d'Uso
Devi presentare analisi rischio carbonio a investor:

1. Inserisci ticker: **SIEMENS**
2. Modifica emissioni con dato reale: 12.5 Mt CO2
3. Scarica "Report Completo (Excel)"

### Documento Finale Contiene
- **Foglio 1 - Profilo Siemens**: Meta dati, settore, dati finanziari
- **Foglio 2 - Stress Test**: 7 anni × 3 scenari di analisi

Pronto per presentazione!

---

## Scenario 7: Ricerca Settoriale

### Domanda
"Quale settore è più esposto al rischio carbonio?"

### Metodo
1. Analizza aziende da diversi settori
   - AAPL (Technology)
   - BP (Energy)
   - SIEMENS (Industrials)
2. Confronta report
3. Valuta resilienza relativa

### Insight
Energy sector mostra passività massime in tutti gli scenari.

---

## 📊 Ticker Consigliati per Testing

### Large Cap Globali
- **AAPL** - Apple (USA, Technology)
- **MSFT** - Microsoft (USA, Technology)
- **ASML** - ASML (Paesi Bassi, Technology)
- **SAP** - SAP (Germania, Technology)
- **BP** - BP (UK, Energy)
- **RDS.A** - Shell (Paesi Bassi, Energy)
- **SIEMENS** - Siemens (Germania, Industrials)
- **ENEL** - Enel (Italia, Utilities)

### PMI Europee
- **SAM** - Zurich (Svizzera)
- **NOKIA** - Nokia (Finlandia)
- **VOLC** - Volvo (Svezia)

### Crescita
- **TSLA** - Tesla (USA, Auto)
- **NVDA** - Nvidia (USA, Semiconductors)
- **AMD** - AMD (USA, Semiconductors)

---

## 💡 Best Practices

### DO ✅
- ✅ Usa ticker ufficiali da Bloomberg/Yahoo Finance
- ✅ Personalizza emissioni con dati reali aziendali
- ✅ Esporta report per documenti importanti
- ✅ Confronta più scenari per robustezza

### DON'T ❌
- ❌ Non confondere il ticker di quotazione
- ❌ Non usare dati di emissioni non verificati
- ❌ Non considerare l'analisi come consulenza finanziaria
- ❌ Non ignorare i margini di incertezza

---

## 🔧 Troubleshooting

### Ticker non trovato
```
⚠️ "Errore nel caricamento dati per ABC"
→ Verifica: ticker è corretto su Yahoo Finance
→ Prova: simbolo completo (es: ENEL.MI per Enel)
```

### Dati mancanti (N/A)
```
Campo mostra "N/A"
→ Normale per alcuni settori/mercati
→ Inserisci valore manualmente
```

### Caricamento lento
```
Timeout > 10 secondi
→ Connessione internet lenta
→ Prova di nuovo tra qualche minuto
```

---

**Generated**: Marzo 2026  
**For**: CarbonRisk Radar PRO v2.0 con yfinance Integration
