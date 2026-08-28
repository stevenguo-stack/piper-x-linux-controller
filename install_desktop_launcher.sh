#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_FILE="$APP_DIR/nxtektal-piper-x-remote.desktop"
CAN_PORT="${1:-can0}"
SPEED="${2:-10}"

mkdir -p "$APP_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=NXTektal PiPER X 遥控器
Comment=PiPER X Linux graphical remote controller
Exec="$ROOT/run_remote.sh" --can "$CAN_PORT" --speed "$SPEED"
Path="$ROOT"
Icon=applications-engineering
Terminal=false
Categories=Development;Engineering;Utility;
StartupNotify=true
EOF
chmod +x "$DESKTOP_FILE"

echo "Desktop launcher installed: $DESKTOP_FILE"
echo "Open your application menu and search for: NXTektal PiPER X 遥控器"
