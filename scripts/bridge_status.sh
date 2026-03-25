#!/usr/bin/env bash
set -euo pipefail

MW_URL="${DEXTER_MIDDLEWARE_URL:-http://127.0.0.1:8080}"
BRIDGE_URL="${DEXTER_TRAJECTORY_BRIDGE_URL:-http://127.0.0.1:8765}"

echo "[CHECK] Middleware: ${MW_URL}"
if curl -sS -m 2 "${MW_URL}/health" >/dev/null; then
  echo "  - middleware: online"
else
  echo "  - middleware: offline"
fi

echo "[CHECK] Trajectory backend status"
if command -v python3 >/dev/null 2>&1; then
  curl -sS -m 3 "${MW_URL}/trajectory/backend/status" | python3 -m json.tool || true
else
  curl -sS -m 3 "${MW_URL}/trajectory/backend/status" || true
fi

echo "[CHECK] Bridge ping: ${BRIDGE_URL}/ping"
if curl -sS -m 2 "${BRIDGE_URL}/ping" >/dev/null; then
  echo "  - bridge: online"
else
  echo "  - bridge: offline"
fi
