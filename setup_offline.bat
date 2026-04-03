@echo off
REM setup_offline.bat — Prepara l'ambiente Python per l'app offline su Windows
setlocal

echo === Setup Supporto PMI Offline Completo ===
echo.

REM Verifica Python 3
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato.
    echo Installalo da https://www.python.org/downloads/
    echo Assicurati di spuntare "Add Python to PATH" durante l'installazione.
    pause
    exit /b 1
)

python --version

REM Crea virtual environment
if not exist ".venv" (
    echo Creazione virtual environment ^(.venv^)...
    python -m venv .venv
) else (
    echo Virtual environment gia' esistente ^(.venv^)
)

REM Installa dipendenze
echo Installazione dipendenze da requirements.txt...
.venv\Scripts\pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt

echo.
echo === Setup completato! ===
echo.
echo Per avviare l'app, esegui:
echo   avvia_offline.bat
echo.
pause
