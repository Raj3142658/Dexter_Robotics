#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/raj/Dexter_Robotics"
RUNTIME_DIR="$ROOT/.runtime/trajectory_bridge"
PID_FILE="$RUNTIME_DIR/bridge.pid"
HOST="${DEXTER_TRAJECTORY_BRIDGE_HOST:-127.0.0.1}"
PORT="${DEXTER_TRAJECTORY_BRIDGE_PORT:-8765}"

killed=0

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    killed=1
  fi
  rm -f "$PID_FILE"
fi

if command -v lsof >/dev/null 2>&1; then
  pids="$(lsof -ti tcp:"${PORT}" || true)"
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
    sleep 0.4
    pids="$(lsof -ti tcp:"${PORT}" || true)"
    if [[ -n "$pids" ]]; then
      kill -9 $pids 2>/dev/null || true
    fi
    killed=1
  fi
fi

if [[ "$killed" -eq 1 ]]; then
  echo "Bridge stopped"
else
  echo "Bridge not running"
fi
