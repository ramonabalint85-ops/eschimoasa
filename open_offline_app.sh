#!/usr/bin/env bash
set -e
FILE="$(cd "$(dirname "$0")" && pwd)/supporto_rendicontazione_offline.html"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$FILE"
elif command -v open >/dev/null 2>&1; then
  open "$FILE"
else
  echo "Apri manualmente questo link nel browser: file://$FILE"
fi
