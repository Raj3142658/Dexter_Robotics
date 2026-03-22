#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/raj/Dexter_Robotics"
SRC_DESKTOP="$ROOT/scripts/dexter-control-center.desktop"
TARGET_DIR="$HOME/.local/share/applications"
TARGET_FILE="$TARGET_DIR/dexter-control-center.desktop"

mkdir -p "$TARGET_DIR"
cp "$SRC_DESKTOP" "$TARGET_FILE"
chmod +x "$ROOT/scripts/launch_control_center.sh" "$ROOT/scripts/stop_control_center.sh"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$TARGET_DIR" >/dev/null 2>&1 || true
fi

echo "Installed desktop launcher: $TARGET_FILE"
echo "Search 'Dexter Control Center' in Ubuntu apps and pin it to sidebar."
