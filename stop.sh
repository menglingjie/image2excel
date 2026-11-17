#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

ENTRY="python -m uvicorn image2excel_server:app"
PIDS=""
for pid in $(pgrep -f "uvicorn image2excel_server:app" || true); do
  comm=$(cat "/proc/$pid/comm" 2>/dev/null || true)
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
  case "$comm" in
    python*)
      case "$cmd" in
        *"$ENTRY"*) PIDS="$PIDS $pid" ;;
      esac
      ;;
  esac
done

if [ -z "$PIDS" ]; then
  echo "没有正在运行的服务"
  exit 0
fi

echo "正在停止服务：进程 $PIDS"
kill -TERM $PIDS

for _ in $(seq 1 50); do
  ALIVE=""
  for pid in $PIDS; do
    if kill -0 "$pid" 2>/dev/null; then
      ALIVE="$ALIVE $pid"
    fi
  done
  if [ -z "$ALIVE" ]; then
    echo "服务已停止"
    exit 0
  fi
  sleep 0.1
done

echo "进程$ALIVE 未退出，强制停止…"
kill -KILL $ALIVE 2>/dev/null || true
echo "服务已强制停止"
