# Deploy online

Questa repository include ora:

- una copia completa standard tramite `streamlit_app.py`
- una copia online brandizzata e separata tramite `streamlit_app_brand.py`

## Avvio locale

```bash
streamlit run streamlit_app.py
```

## Avvio copia brandizzata

```bash
streamlit run streamlit_app_brand.py
```

## Deploy su Streamlit Community Cloud

1. Pubblica la repository su GitHub.
2. Crea una nuova app su Streamlit Community Cloud.
3. Seleziona come file principale `streamlit_app.py` oppure `streamlit_app_brand.py`.
4. Lascia che Streamlit installi le dipendenze da `requirements.txt`.
5. Se vuoi separare cache e progetti dal path di default, imposta la variabile ambiente `SMES_REPORTING_DATA_DIR`.

## Persistenza dei progetti online

L'app mantiene tutte le funzionalità principali anche online.

- Salvataggio locale sul server: attivo.
- Backup portabile: disponibile tramite `Scarica progetto JSON`.
- Ripristino completo: disponibile tramite `Importa progetto JSON`.
- Branding separato: disponibile tramite le variabili `SMES_REPORTING_PAGE_TITLE` e `SMES_REPORTING_DISPLAY_TITLE`.

Questo permette di usare la stessa analisi da browser diversi o dopo un riavvio dell'istanza cloud.

La copia brandizzata usa inoltre un data directory separato di default, così non interferisce con l'istanza locale.

## Uso online da GitHub Codespaces

Se l'app gira in Codespaces, l'URL esterno segue di norma questo formato:

```text
https://<codespace-name>-8501.app.github.dev
```

Se il link non si apre da un altro dispositivo, imposta la porta 8501 come `Public` dal pannello `Ports` del Codespace.