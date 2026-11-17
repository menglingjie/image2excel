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

if ! command -v tesseract >/dev/null 2>&1; then
  echo "安装 Tesseract OCR…"
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim
fi

exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
