#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".git" ]]; then
  git init
fi

if [[ ! -d ".venv" ]]; then
  uv venv
fi

source .venv/bin/activate
uv pip install -r requirements.txt
npm --prefix frontend install
python -m backend.app.init_db

echo
echo "Setup complete."
echo "1. Copy .env.example to .env and add your Earth Engine project if needed."
echo "2. Run ./run.sh"
echo "3. Open http://127.0.0.1:\${FRONTEND_PORT:-5173}"

