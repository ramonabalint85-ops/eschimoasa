@echo off
REM avvia_offline.bat — Avvia l'app Supporto PMI Offline su Windows
setlocal

set PORT=8504
set URL=http://localhost:%PORT%

REM Usa il .venv locale se esiste, altrimenti python di sistema
if exist ".venv\Scripts\python.exe" (
    set PYTHON_BIN=.venv\Scripts\python.exe
) else (
    set PYTHON_BIN=python
)

echo Avvio Supporto PMI Offline Completo...
echo URL: %URL%
echo.

REM Avvia Streamlit in background
set SMES_REPORTING_OFFLINE_MODE=1
set SMES_REPORTING_PAGE_TITLE=Supporto PMI Offline Completo
start "" %PYTHON_BIN% -m streamlit run streamlit_app_offline_full.py --server.port %PORT% --server.headless true

REM Attendi qualche secondo e apri il browser
timeout /t 4 /noisy >nul
start "" "%URL%"

echo App avviata. Se il browser non si apre, vai su: %URL%
echo Per fermare l'app, chiudi la finestra del terminale Streamlit.
echo.
pause
