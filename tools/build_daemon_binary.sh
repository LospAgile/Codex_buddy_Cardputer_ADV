#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
OUT_BIN="$ROOT_DIR/tools/codex-buddy-daemon"
WORK_DIR="$ROOT_DIR/build/pyinstaller/codex-buddy-daemon"
SPEC_DIR="$ROOT_DIR/build/pyinstaller"
LOG_PATH="$ROOT_DIR/build/pyinstaller/codex-buddy-daemon.log"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3 || true)"
fi

if [[ -z "$PYTHON" ]]; then
  cat >&2 <<'EOF'
Python 3 was not found.

Install Python 3.10+ or create the project .venv first.
EOF
  exit 127
fi

if ! "$PYTHON" -c 'import PyInstaller' >/dev/null 2>&1; then
  cat >&2 <<'EOF'
PyInstaller was not found in the selected Python environment.

Install it into the project environment:
  ./.venv/bin/python -m pip install pyinstaller
EOF
  exit 127
fi

rm -f "$OUT_BIN"
mkdir -p "$WORK_DIR" "$SPEC_DIR"

if ! PYTHONPATH="$ROOT_DIR/daemon/src" "$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --log-level WARN \
  --onefile \
  --name codex-buddy-daemon \
  --distpath "$ROOT_DIR/tools" \
  --workpath "$WORK_DIR" \
  --specpath "$SPEC_DIR" \
  --paths "$ROOT_DIR/daemon/src" \
  "$ROOT_DIR/tools/codex_buddy_daemon_entry.py" >"$LOG_PATH" 2>&1; then
  cat "$LOG_PATH" >&2
  exit 1
fi

codesign -s - --force "$OUT_BIN" >/dev/null
echo "$OUT_BIN"
