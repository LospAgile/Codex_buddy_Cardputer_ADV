#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="CodexBuddyMenu.app"
APP_DIR="$ROOT_DIR/tools/$APP_NAME"
MACOS_DIR="$APP_DIR/Contents/MacOS"
RESOURCES_DIR="$APP_DIR/Contents/Resources"
PLIST="$APP_DIR/Contents/Info.plist"
VERSION="$(awk -F '"' '/^version = / {print $2; exit}' "$ROOT_DIR/apps/codex-buddy-menu/Cargo.toml")"
BIN_NAME="codex-buddy-menu"
PREFS_BIN_NAME="codex-buddy-preferences"
ICON_NAME="CodexBuddyMenu"
ICONSET="$ROOT_DIR/apps/codex-buddy-menu/assets/$ICON_NAME.iconset"
EMBEDDED_DAEMON_DIR="$RESOURCES_DIR/daemon"
EMBEDDED_BLE_APP="$RESOURCES_DIR/CodexBuddyBridge.app"
EMBEDDED_DAEMON_BIN="$RESOURCES_DIR/codex-buddy-daemon"

if ! command -v cargo >/dev/null 2>&1; then
  cat >&2 <<'EOF'
cargo was not found.

Install Rust first, then rerun:
  brew install rust

This script does not install toolchains automatically.
EOF
  exit 127
fi

"$ROOT_DIR/tools/build_ble_bridge_app.sh" >/dev/null
"$ROOT_DIR/tools/build_daemon_binary.sh" >/dev/null

cargo build \
  --manifest-path "$ROOT_DIR/apps/codex-buddy-menu/Cargo.toml" \
  --release \
  --bins

mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
cp "$ROOT_DIR/apps/codex-buddy-menu/target/release/$BIN_NAME" "$MACOS_DIR/$BIN_NAME"
cp "$ROOT_DIR/apps/codex-buddy-menu/target/release/$PREFS_BIN_NAME" "$MACOS_DIR/$PREFS_BIN_NAME"
iconutil -c icns "$ICONSET" -o "$RESOURCES_DIR/$ICON_NAME.icns"
rm -rf "$EMBEDDED_BLE_APP" "$EMBEDDED_DAEMON_DIR" "$EMBEDDED_DAEMON_BIN"
ditto "$ROOT_DIR/tools/CodexBuddyBridge.app" "$EMBEDDED_BLE_APP"
cp "$ROOT_DIR/tools/codex-buddy-daemon" "$EMBEDDED_DAEMON_BIN"
mkdir -p "$EMBEDDED_DAEMON_DIR"
ditto "$ROOT_DIR/daemon/src" "$EMBEDDED_DAEMON_DIR/src"
cp "$ROOT_DIR/daemon/pyproject.toml" "$EMBEDDED_DAEMON_DIR/pyproject.toml"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key>
  <string>local.codex-buddy.menu</string>
  <key>CFBundleName</key>
  <string>Codex Buddy Menu</string>
  <key>CFBundleDisplayName</key>
  <string>Codex Buddy Menu</string>
  <key>CFBundleExecutable</key>
  <string>codex-buddy-menu</string>
  <key>CFBundleIconFile</key>
  <string>CodexBuddyMenu</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>CFBundleShortVersionString</key>
  <string>$VERSION</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
EOF

codesign -s - --force --deep "$APP_DIR"
echo "$APP_DIR"
