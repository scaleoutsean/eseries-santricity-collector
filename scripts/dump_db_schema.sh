#!/usr/bin/env bash
set -euo pipefail

PY_SCRIPT="$(dirname "$0")/dump_db_schema.py"
if [ ! -x "$PY_SCRIPT" ]; then
    chmod +x "$PY_SCRIPT" || true
fi

python3 "$PY_SCRIPT"