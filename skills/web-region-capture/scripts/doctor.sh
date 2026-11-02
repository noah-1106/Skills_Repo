#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ ! -x "$ROOT/.venv/bin/python" ]; then echo 'Run scripts/bootstrap.sh first' >&2; exit 1; fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/runtime/ms-playwright"
export TMPDIR="$ROOT/runtime/tmp"
mkdir -p "$TMPDIR"
exec "$ROOT/.venv/bin/python" -m web_region_capture --root "$ROOT" doctor "$@"
