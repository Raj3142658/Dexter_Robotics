#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/raj/Dexter_Robotics"
APP_DIR="$ROOT/src/dexter_middleware/app"
RUNTIME_DIR="$ROOT/.runtime/trajectory_bridge"
PID_FILE="$RUNTIME_DIR/bridge.pid"
LOG_FILE="$RUNTIME_DIR/bridge.log"
HOST="${DEXTER_TRAJECTORY_BRIDGE_HOST:-127.0.0.1}"
PORT="${DEXTER_TRAJECTORY_BRIDGE_PORT:-8765}"

mkdir -p "$RUNTIME_DIR"

is_online() {
  curl -sS -m 1 "http://${HOST}:${PORT}/ping" >/dev/null 2>&1
}

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
    if is_online; then
      echo "Bridge already running (pid ${pid})"
      exit 0
    fi
  fi
  rm -f "$PID_FILE"
fi

if is_online; then
  echo "Bridge already online at http://${HOST}:${PORT}"
  exit 0
fi

# Free stale listener on bridge port if present.
if command -v lsof >/dev/null 2>&1; then
  stale_pids="$(lsof -ti tcp:"${PORT}" || true)"
  if [[ -n "$stale_pids" ]]; then
    kill $stale_pids 2>/dev/null || true
    sleep 0.4
  fi
fi

: > "$LOG_FILE"

(
  cd "$APP_DIR"
  python3 -m uvicorn trajectory_bridge_compat:app --host "$HOST" --port "$PORT" --log-level warning >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
)

for _ in $(seq 1 30); do
  if is_online; then
    echo "Bridge started at http://${HOST}:${PORT}"
    exit 0
  fi
  sleep 0.2
done

echo "Bridge failed to start; see $LOG_FILE" >&2
exit 1
