#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"

cd "$ROOT_DIR"
exec "$VENV_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
