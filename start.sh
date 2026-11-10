#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    printf 'Error: %s was not found. Install Python 3 and python3-venv first.\n' "$PYTHON_BIN" >&2
    exit 1
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

REQUIREMENTS_FILE="$PROJECT_DIR/backend/requirements.txt"
INSTALL_MARKER="$VENV_DIR/.requirements-installed"
if [[ ! -f "$INSTALL_MARKER" || "$REQUIREMENTS_FILE" -nt "$INSTALL_MARKER" ]]; then
    "$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS_FILE"
    touch "$INSTALL_MARKER"
fi

cd "$PROJECT_DIR/backend"
exec "$VENV_DIR/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000