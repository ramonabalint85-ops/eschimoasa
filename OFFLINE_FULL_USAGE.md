# Uso della versione offline completa

## File principali
- `streamlit_app_offline_full.py`
- `open_offline_full_app.sh`

## Cosa include
- tutte le tab dell'app Streamlit completa
- diagnosi azienda e checklist VSME complete
- piano rischi con upload file e inserimento coordinate GPS
- stress test, calcolatore GHG, deliverable PDF
- salvataggio progetto locale e backup/import JSON

## Cosa cambia rispetto alla versione online
- nessuna chiamata internet obbligatoria
- geolocalizzazione da indirizzo disattivata: in offline usa coordinate GPS o file con `Lat` e `Lon`
- eventuali dati finanziari online usano solo cache locale, se disponibile

## Avvio
```bash
./open_offline_full_app.sh
```

In alternativa:
```bash
streamlit run streamlit_app_offline_full.py --server.port 8504
```

## Note pratiche
- La directory dati offline dedicata è `.offline_full_data/`
- Se vuoi includere la sede in mappa senza internet, inserisci latitudine e longitudine nella sidebar
- La versione offline lite HTML resta separata e non viene modificata
