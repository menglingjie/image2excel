#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

if [ ! -x .venv/bin/python ]; then
  echo "创建虚拟环境…"
  uv venv .venv --python 3.13
  uv pip install --python .venv/bin/python -r requirements.txt
fi

exec .venv/bin/python -m uvicorn image2excel_server:app --host "$HOST" --port "$PORT" "$@"
