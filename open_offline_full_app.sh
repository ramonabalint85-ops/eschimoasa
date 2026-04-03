#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${SMES_REPORTING_OFFLINE_PORT:-8504}"
PYTHON_BIN="$APP_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

cd "$APP_DIR"
nohup "$PYTHON_BIN" -m streamlit run streamlit_app_offline_full.py --server.headless true --server.port "$PORT" >/tmp/smes_offline_full.log 2>&1 &

URL="http://localhost:$PORT"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL"
elif command -v open >/dev/null 2>&1; then
  open "$URL"
else
  echo "Apri manualmente questo link nel browser: $URL"
fi

echo "App offline completa avviata su $URL"
echo "Log: /tmp/smes_offline_full.log"
