#!/bin/bash
set -Eeuo pipefail

pause_on_exit() {
  echo ""
  read -n 1 -s -r -p "Press any key to exit..."
  echo ""
}

on_error() {
  local code=$?
  echo ""
  echo "[ERROR] Script failed (exit code: $code)"
  echo "[ERROR] Command: ${BASH_COMMAND}"
  pause_on_exit
  exit "$code"
}

trap on_error ERR

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"

HOST="127.0.0.1"
PORT="8000"
URL="http://${HOST}:${PORT}/"

echo "[INFO] Project root: $ROOT"
echo "[INFO] Backend dir  : $BACKEND"

PY=""
USING_VENV="0"

if [[ -x "$BACKEND/.venv/bin/python" ]]; then
  PY="$BACKEND/.venv/bin/python"
  USING_VENV="1"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
  USING_VENV="1"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "[ERROR] No Python found."
  echo "[ERROR] Install Python 3 or create a venv at backend/.venv or .venv."
  pause_on_exit
  exit 1
fi

echo "[INFO] Using Python: $PY"
$PY -c "import sys; print(sys.version); print(sys.executable)"

$PY -m pip --version >/dev/null 2>&1 || {
  echo "[ERROR] pip is not available for this Python."
  echo "[ERROR] Reinstall Python with pip enabled, or use a venv."
  pause_on_exit
  exit 1
}

[[ -f "$BACKEND/app.py" ]] || {
  echo "[ERROR] Missing backend/app.py."
  pause_on_exit
  exit 1
}

[[ -f "$BACKEND/data/passages.json" ]] || {
  echo "[ERROR] Missing backend/data/passages.json."
  echo "[ERROR] Run: $PY \"$BACKEND/scripts/import_pdf_to_json.py\""
  pause_on_exit
  exit 1
}

if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[ERROR] Port $PORT is already in use."
  echo "[ERROR] Stop the other process or change PORT in run.command."
  pause_on_exit
  exit 1
fi

cd "$BACKEND"
$PY -c "import app; print('app import ok')" >/dev/null 2>&1 || {
  echo "[ERROR] backend/app.py failed to import."
  echo "[ERROR] Run: cd \"$BACKEND\" && $PY -c \"import app\""
  pause_on_exit
  exit 1
}

if ! $PY -c "import uvicorn" >/dev/null 2>&1; then
  echo "[WARN] uvicorn not found. Installing requirements..."
  if [[ "$USING_VENV" == "1" ]]; then
    $PY -m pip install -r "$BACKEND/requirements.txt"
  else
    $PY -m pip install --user -r "$BACKEND/requirements.txt"
  fi
fi

echo ""
echo "[INFO] Starting verraco on $URL"
echo "[INFO] Press Ctrl+C to stop."
echo ""

( sleep 1; open "$URL" ) >/dev/null 2>&1 || true

exec $PY -m uvicorn app:app --host "$HOST" --port "$PORT"
