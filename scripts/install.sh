#!/bin/bash
set -e

APP_NAME="oled-saver"
BIN_DIR="$HOME/.local/bin"
AUTOSTART_DIR="$HOME/.config/autostart"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== OLED Saver — Install ==="
echo ""

# Create directories
mkdir -p "$BIN_DIR"
mkdir -p "$AUTOSTART_DIR"

# Copy binary
if [ -f "$SCRIPT_DIR/$APP_NAME" ]; then
    cp "$SCRIPT_DIR/$APP_NAME" "$BIN_DIR/$APP_NAME"
    chmod +x "$BIN_DIR/$APP_NAME"
    echo "✓ Binary installed to $BIN_DIR/$APP_NAME"
else
    echo "✗ Binary '$APP_NAME' not found in $SCRIPT_DIR"
    exit 1
fi

# Copy toggle script
if [ -f "$SCRIPT_DIR/toggle-pause.sh" ]; then
    cp "$SCRIPT_DIR/toggle-pause.sh" "$BIN_DIR/$APP_NAME-toggle"
    chmod +x "$BIN_DIR/$APP_NAME-toggle"
    echo "✓ Toggle script installed to $BIN_DIR/$APP_NAME-toggle"
fi

# Install desktop file for autostart
cat > "$AUTOSTART_DIR/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=OLED Saver
Comment=Blank or dim OLED monitors when idle to prevent burn-in
Exec=$BIN_DIR/$APP_NAME
Icon=preferences-desktop-screensaver
Terminal=false
Categories=Utility;
X-KDE-autostart-after=panel
EOF
echo "✓ Autostart enabled ($AUTOSTART_DIR/$APP_NAME.desktop)"

echo ""
echo "=== Done! ==="
echo ""
echo "OLED Saver will start automatically on next login."
echo "To start now:  $BIN_DIR/$APP_NAME &"
echo ""
echo "Optional: Add a global hotkey (Super+B) to toggle pause:"
echo "  KDE: System Settings → Shortcuts → Custom Shortcuts → $BIN_DIR/$APP_NAME-toggle"
echo ""
echo "To uninstall:  ./uninstall.sh"
