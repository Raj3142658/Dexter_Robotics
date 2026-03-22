#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/raj/Dexter_Robotics"
RUNTIME_DIR="$ROOT/.runtime/control_center"
MIDDLEWARE_PORT="8080"
UI_PORT="8090"
QUIET=0
FROM_API=0

for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=1 ;;
    --from-api) FROM_API=1 ;;
  esac
done

kill_pid_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    local pid
    pid=$(cat "$file" || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 0.4
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$file"
  fi
}

kill_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti tcp:"$port" || true)
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
    sleep 0.4
    pids=$(lsof -ti tcp:"$port" || true)
    if [[ -n "$pids" ]]; then
      kill -9 $pids 2>/dev/null || true
    fi
  fi
}

kill_pid_file "$RUNTIME_DIR/ui.pid"
kill_pid_file "$RUNTIME_DIR/middleware.pid"

kill_port "$UI_PORT"
kill_port "$MIDDLEWARE_PORT"

# Optionally stop the launcher shell if it still exists.
if [[ "$FROM_API" -eq 1 ]]; then
  kill_pid_file "$RUNTIME_DIR/launcher.pid"
else
  rm -f "$RUNTIME_DIR/launcher.pid"
fi

if [[ "$QUIET" -ne 1 ]]; then
  echo "Dexter Control Center stopped"
fi
