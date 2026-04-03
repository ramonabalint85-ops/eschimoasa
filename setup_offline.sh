#!/usr/bin/env bash
# setup_offline.sh — Prepara l'ambiente Python per l'app offline su un nuovo PC
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

echo "=== Setup Supporto PMI Offline Completo ==="
echo ""

# Verifica Python 3
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERRORE: Python 3 non trovato. Installalo da https://www.python.org/downloads/"
  exit 1
fi

PYTHON_VER=$(python3 --version 2>&1)
echo "Trovato: $PYTHON_VER"

# Crea virtual environment
if [ ! -d ".venv" ]; then
  echo "Creazione virtual environment (.venv)..."
  python3 -m venv .venv
else
  echo "Virtual environment già esistente (.venv)"
fi

# Installa dipendenze
echo "Installazione dipendenze da requirements.txt..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt

echo ""
echo "=== Setup completato! ==="
echo ""
echo "Per avviare l'app:"
echo "  ./open_offline_full_app.sh"
echo ""
echo "Oppure manualmente:"
echo "  .venv/bin/python -m streamlit run streamlit_app_offline_full.py --server.port 8504"
echo ""
