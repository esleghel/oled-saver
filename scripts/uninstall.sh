#!/bin/bash
set -e

APP_NAME="oled-saver"
BIN_DIR="$HOME/.local/bin"
AUTOSTART_DIR="$HOME/.config/autostart"

echo "=== OLED Saver — Uninstall ==="
echo ""

# Stop running instance
PID_FILE="/tmp/$APP_NAME-$(id -u).pid"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null || true
        echo "✓ Stopped running instance (PID $PID)"
    fi
    rm -f "$PID_FILE"
fi

# Remove files
rm -f "$BIN_DIR/$APP_NAME"
echo "✓ Removed $BIN_DIR/$APP_NAME"

rm -f "$BIN_DIR/$APP_NAME-toggle"
echo "✓ Removed $BIN_DIR/$APP_NAME-toggle"

rm -f "$AUTOSTART_DIR/$APP_NAME.desktop"
echo "✓ Removed autostart entry"

echo ""
echo "=== Done! ==="
echo ""
echo "Config file kept at: ~/.config/oled-saver.conf"
echo "Delete it manually if you want a clean removal."
