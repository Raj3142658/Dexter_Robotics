#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/raj/Dexter_Robotics"
SRC_DESKTOP="$ROOT/scripts/dexter-control-center.desktop"
SRC_ICON="$ROOT/scripts/assets/dexter-control-center.svg"
TARGET_DIR="$HOME/.local/share/applications"
TARGET_FILE="$TARGET_DIR/dexter-control-center.desktop"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
ICON_FILE="$ICON_DIR/dexter-control-center.svg"

mkdir -p "$TARGET_DIR"
cp "$SRC_DESKTOP" "$TARGET_FILE"

if [[ ! -f "$SRC_ICON" ]]; then
  echo "Icon not found: $SRC_ICON" >&2
  exit 1
fi

mkdir -p "$ICON_DIR"
cp "$SRC_ICON" "$ICON_FILE"
chmod +x "$ROOT/scripts/launch_control_center.sh" "$ROOT/scripts/stop_control_center.sh"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$TARGET_DIR" >/dev/null 2>&1 || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Installed desktop launcher: $TARGET_FILE"
echo "Installed icon: $ICON_FILE"
echo "Search 'Dexter Control Center' in Ubuntu apps and pin it to sidebar."
