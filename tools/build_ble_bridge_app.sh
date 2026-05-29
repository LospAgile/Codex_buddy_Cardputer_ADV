#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/tools/CodexBuddyBridge.app"
PLIST="$ROOT_DIR/tools/ble_bridge_Info.plist"
MACOS_DIR="$APP_DIR/Contents/MacOS"
EXECUTABLE="$MACOS_DIR/codex_buddy_ble_bridge"

mkdir -p "$MACOS_DIR"
cp "$PLIST" "$APP_DIR/Contents/Info.plist"
swiftc "$ROOT_DIR/tools/ble_smoke.swift" \
  -Xlinker -sectcreate \
  -Xlinker __TEXT \
  -Xlinker __info_plist \
  -Xlinker "$PLIST" \
  -o "$EXECUTABLE"
codesign -s - --force --deep "$APP_DIR"

echo "$APP_DIR"
