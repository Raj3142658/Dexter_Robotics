#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/raj/Dexter_Robotics"
MIDDLEWARE_DIR="$ROOT/src/dexter_middleware"
UI_DIR="$ROOT/src/dexter_temp_ui"
RUNTIME_DIR="$ROOT/.runtime/control_center"
MIDDLEWARE_PORT="8080"
UI_PORT="8090"

mkdir -p "$RUNTIME_DIR"

"$ROOT/scripts/stop_control_center.sh" --quiet || true

kill_port() {
  local port="$1"
  local pids
  pids=$(lsof -ti tcp:"$port" || true)
  if [[ -n "$pids" ]]; then
    kill $pids || true
    sleep 0.5
    pids=$(lsof -ti tcp:"$port" || true)
    if [[ -n "$pids" ]]; then
      kill -9 $pids || true
    fi
  fi
}

kill_port "$MIDDLEWARE_PORT"
kill_port "$UI_PORT"

MIDDLEWARE_LOG="$RUNTIME_DIR/middleware.log"
UI_LOG="$RUNTIME_DIR/ui.log"
: > "$MIDDLEWARE_LOG"
: > "$UI_LOG"

if [[ -x "$MIDDLEWARE_DIR/.venv/bin/python" ]]; then
  "$MIDDLEWARE_DIR/.venv/bin/python" -m uvicorn app.main:app --app-dir "$MIDDLEWARE_DIR" --host 0.0.0.0 --port "$MIDDLEWARE_PORT" --reload >> "$MIDDLEWARE_LOG" 2>&1 &
else
  python3 -m uvicorn app.main:app --app-dir "$MIDDLEWARE_DIR" --host 0.0.0.0 --port "$MIDDLEWARE_PORT" --reload >> "$MIDDLEWARE_LOG" 2>&1 &
fi
echo $! > "$RUNTIME_DIR/middleware.pid"

(
  cd "$UI_DIR"
  python3 -m http.server "$UI_PORT" >> "$UI_LOG" 2>&1 &
  echo $! > "$RUNTIME_DIR/ui.pid"
)

echo $$ > "$RUNTIME_DIR/launcher.pid"
sleep 1
xdg-open "http://127.0.0.1:${UI_PORT}/" >/dev/null 2>&1 || true
