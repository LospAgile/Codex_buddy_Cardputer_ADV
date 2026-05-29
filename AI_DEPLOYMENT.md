# AI Deployment Guide

This file is written for coding agents. Follow it exactly when a user drops
this repository into an AI coding environment and asks to deploy or test it.

## Goal

Deploy Codex Buddy Cardputer ADV Alice:

- Flash M5Stack Cardputer ADV firmware.
- Build or use the macOS BLE helper / menu bar app.
- Connect Codex CLI or Codex Desktop permission approvals to the hardware.
- Keep the hardware Status screen focused on compact current-session activity
  when possible: user prompts, assistant replies, and tool calls.
- Optionally rebuild firmware with a custom Codex Desktop pet.

## Repository Map

```text
daemon/              Python package, CLI entrypoint is codex_buddy.cli
firmware/            PlatformIO project for M5Stack Cardputer ADV
apps/codex-buddy-menu
                     Rust macOS menu bar app
tools/               BLE helper source, build scripts, utility scripts
examples/pets/alice  Default pet package
release/firmware/    Ready-to-flash merged firmware bin
release/apps/        Ready-to-run macOS menu bar app zip
```

Do not assume global dependencies. Prefer the repository `.venv`.

## Bootstrap

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e daemon -r requirements-dev.txt
tools/build_ble_bridge_app.sh
tools/build_menu_bar_app.sh
```

If firmware compilation is needed:

```bash
./.venv/bin/python -m pip install platformio
./.venv/bin/pio run -d firmware -e cardputer-adv
```

## Flash Firmware

If the user wants the fastest path, use the prebuilt merged bin:

```bash
python3 -m pip install esptool
esptool.py --chip esp32s3 --port /dev/cu.usbmodemXXXX --baud 1500000 \
  write_flash 0x0 release/firmware/codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin
```

If building from source:

```bash
./.venv/bin/pio run -d firmware -e cardputer-adv -t upload \
  --upload-port /dev/cu.usbmodemXXXX
```

Cardputer ADV download mode:

1. Power switch OFF.
2. Hold `G0`.
3. Plug USB-C.
4. Wait one second.
5. Release `G0`.

Normal boot:

1. Unplug USB-C.
2. Power switch ON.
3. Do not hold `G0`.
4. Plug USB-C.

## BLE Path

Run doctor first:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor --timeout 8
```

Expected:

```text
summary: usable
```

If macOS asks for Bluetooth permission, allow `Codex Buddy Bridge`.

Firmware `0.3.27-ble-pair` and later requires BLE pairing. Read the six-digit
code from the device `Device` page, then pass it to CLI commands:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor \
  --transport ble-socket \
  --ble-device-name Codex-Buddy \
  --ble-pair-code <six-digit-code>
```

The menu bar app prompts for the same code in the BLE setup flow.

## Menu Bar App Path

For normal users, prefer the prebuilt app:

```text
release/apps/CodexBuddyMenu-v0.1.0-macos-arm64.zip
```

Unzip it, clear macOS quarantine on the current unsigned preview app, open
`CodexBuddyMenu.app`, then use the menu bar item to:

```bash
unzip CodexBuddyMenu-v0.1.0-macos-arm64.zip
xattr -dr com.apple.quarantine CodexBuddyMenu.app
open CodexBuddyMenu.app
```

- choose `Auto`, `WiFi`, or `BLE`;
- enter BLE device name and Pair Code in Preferences;
- start, stop, or restart the bridge;
- install or uninstall the Codex Desktop hook;
- run diagnostics and copy logs.

If testing from source, build the app first:

```bash
tools/build_menu_bar_app.sh
open tools/CodexBuddyMenu.app
```

## GitHub Actions Release Build

If the user asks for a GitHub-hosted build, keep
`.github/workflows/release-artifacts.yml`. It installs Python, Rust,
PlatformIO, and PyInstaller, runs host-side checks, builds the Alice firmware,
builds the macOS menu bar app, uploads `dist/release`, and attaches artifacts to
GitHub Releases for `v*` tags.

## Codex CLI Path

For CLI users, prefer `codex-buddy start` when possible. It launches Codex CLI,
injects a temporary approval hook with `-c`, and starts heartbeat sync. It does
not edit `~/.codex/config.toml`.

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli start \
  --transport ble-socket \
  --ble-device-name Codex-Buddy \
  --ble-pair-code <six-digit-code>
```

Use `--transport auto` only after WiFi is configured and verified.

## Persistent Hook Path

Never edit `~/.codex/config.toml` by hand unless explicitly asked.

`codex-buddy desktop install` writes a managed Codex `PermissionRequest` hook to
the shared Codex config. Codex Desktop and bare `codex` CLI can both read it.
This persistent hook handles approval requests only; live Status sync still
needs the menu bar bridge, `codex-buddy start`, or `codex-buddy watch`.

Read-only preview:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop print \
  --python "$PWD/.venv/bin/python" \
  --transport ble-socket \
  --ble-device-name Codex-Buddy \
  --ble-pair-code <six-digit-code>
```

Install only after user confirmation:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop install \
  --python "$PWD/.venv/bin/python" \
  --transport ble-socket \
  --ble-device-name Codex-Buddy \
  --ble-pair-code <six-digit-code>
```

Tell the user to restart Codex Desktop, or start a new `codex` CLI process,
after install. The command creates a timestamped backup next to
`~/.codex/config.toml` and manages only the block between:

```text
# BEGIN CODEX BUDDY DESKTOP HOOK
# END CODEX BUDDY DESKTOP HOOK
```

The Desktop hook records the active `session_id` when an approval request is
handled. Later heartbeat commands prefer that active session. If multiple Codex
sessions are running and the user asks to pin one manually, use:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli watch \
  --transport ble-socket \
  --session-id <codex-session-id> \
  --interval 2
```

Uninstall:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop uninstall
```

## WiFi Path

Run a long-lived bridge:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli wifi-bridge \
  --wifi-host 0.0.0.0 \
  --wifi-port 47392
```

Device WiFi page must use the Mac LAN IP and port `47392`. Token may be empty
only on trusted local networks.

For Codex Desktop over WiFi, install Desktop hook with `--transport local-bridge`
and keep `wifi-bridge` running. Do not install Desktop hook with
`--transport wifi-server`.

## Custom Pet Rebuild

Input package:

```text
~/.codex/pets/<pet-id>/pet.json
~/.codex/pets/<pet-id>/spritesheet.webp
```

Requirements:

- `spritesheet.webp`: `1536x1872`.
- Atlas: `8 x 9`.
- Cell: `192x208`.
- Firmware output: `72x78`, 57 frames.

Validate:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli pet \
  --pet-dir ~/.codex/pets/<pet-id> \
  --json
```

Generate firmware arrays:

```bash
./.venv/bin/python tools/generate_pet_sprite_asset.py \
  --spritesheet ~/.codex/pets/<pet-id>/spritesheet.webp \
  --label "<Pet Name>" \
  --contact-sheet tools/<pet-id>-firmware-contact-sheet.png
```

Then compile and flash again.

## Verification

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m unittest discover daemon/tests
PYTHONPATH=daemon/src ./.venv/bin/python tools/release_check.py --skip-firmware
./.venv/bin/pio run -d firmware -e cardputer-adv
```

If hardware is connected in normal boot mode:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor --timeout 8
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli approval-demo \
  --transport ble-socket
```
