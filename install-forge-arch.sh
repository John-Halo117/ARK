#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
DESKTOP_TEMPLATE="$ROOT_DIR/packaging/linux/forge-app.desktop.in"
DESKTOP_TARGET="$APPS_DIR/forge-app.desktop"
ICON_SOURCE="$ROOT_DIR/packaging/linux/forge-app.svg"
ICON_TARGET="$ICON_DIR/forge-app.svg"
BIN_TARGET="$BIN_DIR/forge-app"

mkdir -p "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"

ln -sfn "$ROOT_DIR/forge-app" "$BIN_TARGET"
install -m 644 "$ICON_SOURCE" "$ICON_TARGET"
sed \
  -e "s|__ROOT__|$ROOT_DIR|g" \
  -e "s|__BIN__|$BIN_DIR|g" \
  "$DESKTOP_TEMPLATE" >"$DESKTOP_TARGET"
chmod 644 "$DESKTOP_TARGET"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

cat <<EOF
Forge is installed.

What this did:
- linked forge-app into $BIN_DIR
- installed a Forge desktop entry into $APPS_DIR
- installed the Forge icon into $ICON_DIR

Commands:
  forge-app            open Forge
  forge-app --status   show app status
  forge-app --stop     stop the browser app
  forge-app --cleanup  remove stale launcher state

No systemd service was created.
Forge starts only when you open it.
Use the Forge Shutdown button or: forge-app --stop

If your shell does not already include $BIN_DIR, add this:
  export PATH="$BIN_DIR:\$PATH"
EOF
