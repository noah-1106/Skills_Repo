#!/bin/sh
# Thin, client-independent macOS/Linux bootstrap. Run from any working directory.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${PYTHON:-python3}
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
cd "$ROOT"
if [ ! -x "$ROOT/.venv/bin/python" ]; then "$PYTHON" -m venv "$ROOT/.venv"; fi
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install --no-deps -r "$ROOT/requirements.txt"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/runtime/ms-playwright"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" "$ROOT/runtime/tmp"
"$ROOT/.venv/bin/python" -m playwright install chromium
if [ ! -f "$ROOT/config/local.json" ]; then cp "$ROOT/config/local.example.json" "$ROOT/config/local.json"; fi
exec sh "$ROOT/scripts/doctor.sh"
