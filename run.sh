#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Missing .venv. Run ./setup.sh first."
  exit 1
fi

if [[ -f ".env" ]]; then
  set -a
  source .env
  set +a
fi

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:${BACKEND_PORT}}"

source .venv/bin/activate

if lsof -tiTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $BACKEND_PORT in use — killing existing process..."
  lsof -tiTCP:"$BACKEND_PORT" -sTCP:LISTEN | xargs kill
  sleep 1
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

python -m uvicorn backend.app.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
BACKEND_PID=$!

npm --prefix frontend run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" --strictPort
