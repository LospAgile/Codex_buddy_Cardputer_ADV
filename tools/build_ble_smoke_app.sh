#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "tools/build_ble_smoke_app.sh is deprecated; use tools/build_ble_bridge_app.sh" >&2
"$ROOT_DIR/tools/build_ble_bridge_app.sh"
