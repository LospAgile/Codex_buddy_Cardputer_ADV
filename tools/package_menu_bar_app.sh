#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(awk -F '"' '/^version = / {print $2; exit}' "$ROOT_DIR/apps/codex-buddy-menu/Cargo.toml")"
ARCH="$(uname -m)"
OUT_DIR="$ROOT_DIR/dist/release/apps"
APP_PATH="$ROOT_DIR/tools/CodexBuddyMenu.app"
ZIP_NAME="CodexBuddyMenu-v${VERSION}-macos-${ARCH}.zip"
ZIP_PATH="$OUT_DIR/$ZIP_NAME"
SHA_PATH="$OUT_DIR/SHA256SUMS.txt"
MANIFEST_PATH="$OUT_DIR/CodexBuddyMenu-v${VERSION}-macos-${ARCH}.json"

"$ROOT_DIR/tools/build_menu_bar_app.sh" >/dev/null

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

(
  cd "$(dirname "$APP_PATH")"
  ditto -c -k --sequesterRsrc --keepParent "$(basename "$APP_PATH")" "$ZIP_PATH"
)

(
  cd "$OUT_DIR"
  shasum -a 256 "$ZIP_NAME" > "$SHA_PATH"
)

cat > "$MANIFEST_PATH" <<EOF
{
  "name": "CodexBuddyMenu",
  "version": "$VERSION",
  "platform": "macos",
  "arch": "$ARCH",
  "artifact": "$ZIP_NAME",
  "sha256_file": "SHA256SUMS.txt",
  "contains": [
    "CodexBuddyMenu.app",
    "CodexBuddyMenu.app/Contents/MacOS/codex-buddy-menu",
    "CodexBuddyMenu.app/Contents/MacOS/codex-buddy-preferences",
    "CodexBuddyMenu.app/Contents/Resources/codex-buddy-daemon",
    "CodexBuddyMenu.app/Contents/Resources/CodexBuddyBridge.app",
    "CodexBuddyMenu.app/Contents/Resources/daemon/src/codex_buddy"
  ],
  "signature": "ad-hoc"
}
EOF

echo "$ZIP_PATH"
