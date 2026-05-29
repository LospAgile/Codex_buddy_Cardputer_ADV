#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/dist/release/firmware"
BUILD_DIR="$ROOT_DIR/firmware/.pio/build/cardputer-adv"
FIRMWARE_VERSION="$(
  sed -n 's/.*kFirmwareVersion = "\([^"]*\)".*/\1/p' "$ROOT_DIR/firmware/src/main.cpp" | head -1
)"
if [[ -z "$FIRMWARE_VERSION" ]]; then
  echo "firmware version was not found in firmware/src/main.cpp" >&2
  exit 1
fi
MERGED_BIN="$OUT_DIR/codex-buddy-cardputer-adv-v${FIRMWARE_VERSION}-merged.bin"
SHA_PATH="$OUT_DIR/SHA256SUMS.txt"
MANIFEST_PATH="$OUT_DIR/codex-buddy-cardputer-adv.json"

PIO_BIN="$ROOT_DIR/.venv/bin/pio"
if [[ ! -x "$PIO_BIN" ]]; then
  PIO_BIN="$(command -v pio || true)"
fi

if [[ -z "$PIO_BIN" ]]; then
  cat >&2 <<'EOF'
PlatformIO was not found.

Install it first:
  python3 -m pip install platformio
EOF
  exit 127
fi
PIO_PYTHON="$(dirname "$PIO_BIN")/python"
if [[ ! -x "$PIO_PYTHON" ]]; then
  PIO_PYTHON="python3"
fi

"$PIO_BIN" run -d "$ROOT_DIR/firmware" -e cardputer-adv >/dev/null

BOOT_APP0="$(find "$HOME/.platformio/packages/framework-arduinoespressif32/tools/partitions" -name boot_app0.bin -print 2>/dev/null | head -1 || true)"
ESPTOOL="$(find "$HOME/.platformio/packages/tool-esptoolpy" -name esptool.py -print 2>/dev/null | head -1 || true)"

if [[ -z "$BOOT_APP0" || -z "$ESPTOOL" ]]; then
  echo "required PlatformIO ESP32 package files were not found" >&2
  exit 1
fi

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

"$PIO_PYTHON" "$ESPTOOL" --chip esp32s3 merge_bin \
  -o "$MERGED_BIN" \
  0x0000 "$BUILD_DIR/bootloader.bin" \
  0x8000 "$BUILD_DIR/partitions.bin" \
  0xe000 "$BOOT_APP0" \
  0x10000 "$BUILD_DIR/firmware.bin" >/dev/null

(
  cd "$OUT_DIR"
  shasum -a 256 "$(basename "$MERGED_BIN")" > "$SHA_PATH"
)

cat > "$MANIFEST_PATH" <<EOF
{
  "name": "codex-buddy-cardputer-adv",
  "platform": "m5stack-cardputer-adv",
  "firmware_version": "$FIRMWARE_VERSION",
  "default_pet": "Alice",
  "merged_bin": "$(basename "$MERGED_BIN")",
  "sha256_file": "SHA256SUMS.txt",
  "flash_offset": "0x0",
  "flash_offsets": {
    "bootloader": "0x0000",
    "partitions": "0x8000",
    "boot_app0": "0xe000",
    "app": "0x10000"
  }
}
EOF

echo "$OUT_DIR"
