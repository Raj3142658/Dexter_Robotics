#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/raj/Dexter_Robotics"
MIDDLEWARE_DIR="$ROOT/src/dexter_middleware"
UI_DIR="${DEXTER_CONTROL_CENTER_UI_DIR:-$ROOT/src/dexter_temp_ui}"
RUNTIME_DIR="$ROOT/.runtime/control_center"
MIDDLEWARE_PORT="8080"
UI_PORT="8090"
MODE="${DEXTER_CONTROL_CENTER_MODE:-none}"
START_BRIDGE="${DEXTER_CONTROL_CENTER_START_BRIDGE:-false}"
USE_RVIZ="${DEXTER_CONTROL_CENTER_USE_RVIZ:-true}"
LOAD_MOVEIT="${DEXTER_CONTROL_CENTER_LOAD_MOVEIT:-true}"
GAZEBO_GUI="${DEXTER_CONTROL_CENTER_GAZEBO_GUI:-true}"
HARDWARE_TRANSPORT="${DEXTER_CONTROL_CENTER_HARDWARE_TRANSPORT:-udp}"
HARDWARE_DEVICE_PORT="${DEXTER_CONTROL_CENTER_HARDWARE_PORT:-8888}"
OPEN_BROWSER="${DEXTER_CONTROL_CENTER_OPEN_BROWSER:-true}"

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
LAUNCH_LOG="$RUNTIME_DIR/launcher.log"
: > "$MIDDLEWARE_LOG"
: > "$UI_LOG"
: > "$LAUNCH_LOG"

log() {
  echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LAUNCH_LOG"
}

if [[ -x "$MIDDLEWARE_DIR/.venv/bin/python" ]]; then
  bash -lc "source /opt/ros/jazzy/setup.bash && if [ -f '$ROOT/install/setup.bash' ]; then source '$ROOT/install/setup.bash'; fi && exec '$MIDDLEWARE_DIR/.venv/bin/python' -m uvicorn app.main:app --app-dir '$MIDDLEWARE_DIR' --host 0.0.0.0 --port '$MIDDLEWARE_PORT'" >> "$MIDDLEWARE_LOG" 2>&1 &
else
  bash -lc "source /opt/ros/jazzy/setup.bash && if [ -f '$ROOT/install/setup.bash' ]; then source '$ROOT/install/setup.bash'; fi && exec python3 -m uvicorn app.main:app --app-dir '$MIDDLEWARE_DIR' --host 0.0.0.0 --port '$MIDDLEWARE_PORT'" >> "$MIDDLEWARE_LOG" 2>&1 &
fi
echo $! > "$RUNTIME_DIR/middleware.pid"
log "Middleware starting on port $MIDDLEWARE_PORT"

if [[ -d "$UI_DIR" ]]; then
  if [[ -f "$UI_DIR/package.json" ]]; then
    (
      cd "$UI_DIR"
      if [[ -f "pnpm-lock.yaml" ]]; then
        pnpm install >> "$UI_LOG" 2>&1 || true
        pnpm run dev -- --host 0.0.0.0 --port "$UI_PORT" >> "$UI_LOG" 2>&1 &
      elif [[ -f "yarn.lock" ]]; then
        yarn install >> "$UI_LOG" 2>&1 || true
        yarn dev --host 0.0.0.0 --port "$UI_PORT" >> "$UI_LOG" 2>&1 &
      else
        npm install >> "$UI_LOG" 2>&1 || true
        npm run dev -- --host 0.0.0.0 --port "$UI_PORT" >> "$UI_LOG" 2>&1 &
      fi
      echo $! > "$RUNTIME_DIR/ui.pid"
    )
    log "Vite dev server starting on port $UI_PORT (dir=$UI_DIR)"
  elif [[ -f "$UI_DIR/index.html" ]]; then
    (
      cd "$UI_DIR"
      python3 -m http.server "$UI_PORT" >> "$UI_LOG" 2>&1 &
      echo $! > "$RUNTIME_DIR/ui.pid"
    )
    log "Static UI server starting on port $UI_PORT (dir=$UI_DIR)"
  elif [[ -d "$UI_DIR/dist" ]]; then
    (
      cd "$UI_DIR/dist"
      python3 -m http.server "$UI_PORT" >> "$UI_LOG" 2>&1 &
      echo $! > "$RUNTIME_DIR/ui.pid"
    )
    log "Static UI server starting on port $UI_PORT (dir=$UI_DIR/dist)"
  else
    log "UI directory found but no package.json or dist/: $UI_DIR"
  fi
else
  log "UI directory not found: $UI_DIR (set DEXTER_CONTROL_CENTER_UI_DIR to override)"
fi

echo $$ > "$RUNTIME_DIR/launcher.pid"

wait_for_mw() {
  for _ in $(seq 1 40); do
    if curl -sS -m 1 "http://127.0.0.1:${MIDDLEWARE_PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

if wait_for_mw; then
  log "Middleware online"
else
  log "Middleware did not respond to /health (check $MIDDLEWARE_LOG)"
fi

case "$MODE" in
  full_stack)
    log "Starting full stack (Gazebo + MoveIt + RViz=$USE_RVIZ)"
    curl -sS -m 12 -X POST "http://127.0.0.1:${MIDDLEWARE_PORT}/ros/full-stack/start" \
      -H 'Content-Type: application/json' \
      --data "{\"use_rviz\": ${USE_RVIZ}, \"load_moveit\": ${LOAD_MOVEIT}}" >/dev/null 2>&1 || \
      log "Full stack start failed (check middleware logs)"
    ;;
  gazebo)
    log "Starting Gazebo (GUI=$GAZEBO_GUI)"
    curl -sS -m 12 -X POST "http://127.0.0.1:${MIDDLEWARE_PORT}/ros/gazebo/start" \
      -H 'Content-Type: application/json' \
      --data "{\"gui\": ${GAZEBO_GUI}}" >/dev/null 2>&1 || \
      log "Gazebo start failed (check middleware logs)"
    ;;
  hardware)
    log "Starting hardware bringup (transport=$HARDWARE_TRANSPORT port=$HARDWARE_DEVICE_PORT)"
    curl -sS -m 12 -X POST "http://127.0.0.1:${MIDDLEWARE_PORT}/ros/hardware/start" \
      -H 'Content-Type: application/json' \
      --data "{\"transport\": \"${HARDWARE_TRANSPORT}\", \"device_port\": \"${HARDWARE_DEVICE_PORT}\", \"use_rviz\": ${USE_RVIZ}, \"load_moveit\": ${LOAD_MOVEIT}}" >/dev/null 2>&1 || \
      log "Hardware start failed (check middleware logs)"
    ;;
  none)
    log "Skipping ROS service startup (MODE=none). Web app will trigger ROS services when needed."
    ;;
  *)
    log "Unknown MODE='$MODE' (use full_stack|gazebo|hardware|none)"
    ;;
esac

if [[ "$START_BRIDGE" == "true" ]]; then
  log "Starting trajectory bridge"
  curl -sS -m 8 -X POST "http://127.0.0.1:${MIDDLEWARE_PORT}/trajectory/backend/start" >/dev/null 2>&1 || \
    log "Bridge start failed (check middleware logs)"
fi

if [[ "$OPEN_BROWSER" == "true" ]]; then
  sleep 1
  if [[ -d "$UI_DIR" ]]; then
    xdg-open "http://127.0.0.1:${UI_PORT}/" >/dev/null 2>&1 || true
  else
    xdg-open "http://127.0.0.1:${MIDDLEWARE_PORT}/docs" >/dev/null 2>&1 || true
  fi
fi
