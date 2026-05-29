# Codex Buddy Menu Bar App

Status: public MVP, macOS menu bar app, Rust-based.

The menu bar app is the normal user-facing launcher for Mac users. It packages
the bridge helper and a standalone daemon helper into one `.app`, supervises the
existing bridge commands, and keeps the Python CLI scripts available for
developers.

## What Ships

Release artifacts should include both device firmware and the Mac helper app:

- `codex-buddy-cardputer-adv-v<firmware-version>-merged.bin`: direct flash
  image for M5Burner or esptool.
- `CodexBuddyMenu-v<version>-macos-<arch>.zip`: menu bar app bundle.
- `SHA256SUMS.txt` and JSON manifests for each artifact group.

The app bundle contains:

- `Contents/MacOS/codex-buddy-menu`: menu bar process.
- `Contents/MacOS/codex-buddy-preferences`: preferences window.
- `Contents/Resources/codex-buddy-daemon`: standalone daemon helper used by the
  menu app and Desktop hook.
- `Contents/Resources/CodexBuddyBridge.app`: bundled BLE bridge helper.
- `Contents/Resources/daemon/src/codex_buddy`: bundled Python daemon source for
  diagnostics and developer visibility.

The original Python commands remain in `daemon/src` and `tools/`. They are still
the preferred entry point for development, testing, and open-source
customization.

## User Flow

1. Download the firmware `.bin` and `CodexBuddyMenu` zip from a release.
2. Burn the firmware to Cardputer ADV.
3. Unzip the app, clear macOS quarantine on the current unsigned preview build,
   and open it:

```bash
unzip CodexBuddyMenu-v0.1.0-macos-arm64.zip
xattr -dr com.apple.quarantine CodexBuddyMenu.app
open CodexBuddyMenu.app
```

4. Use `Connection Guide -> Connect with BLE...` for the first connection, or
   `Connect with WiFi...` for LAN mode.
5. Use `Install Desktop Hook...` only when Codex Desktop integration is desired.
6. Use `Preferences...` for ports, session directory, language, auto start, auto
   restart, and launch at login.

The `Install Desktop Hook...` menu item writes a managed Codex
`PermissionRequest` hook to `~/.codex/config.toml`. Codex Desktop and bare
`codex` CLI can both read that same hook config. The menu label says Desktop
because Desktop is the most common reason to install a persistent hook; CLI
users can also use `codex-buddy start` for a temporary per-session hook.

The user should not need to locate or open `CodexBuddyBridge.app` manually.

## Menu Actions

- Start Bridge
- Stop Bridge
- Restart Bridge
- Connection Guide
  - Connect with BLE...
  - Connect with WiFi...
  - Check current connection
- Connection Mode
  - Auto
  - WiFi only
  - BLE only
- Start bridge when app opens
  - On
  - Off
- Restart bridge if it exits
  - On
  - Off
- Launch app at macOS login
  - On
  - Off
- Language
  - English
  - 中文
- Preferences...
- Configure Ports...
- Run Doctor
- Open Logs
- Copy Diagnostics
- Install Desktop Hook...
- Uninstall Desktop Hook...
- Quit

## Preferences

The preferences window edits `~/.codex/codex-buddy-menu.env`.

It currently supports:

- transport mode: `auto`, `ble`, or `wifi`
- language: English or Chinese
- session working directory
- WiFi listen port, BLE socket port, local bridge port
- heartbeat interval
- optional pairing token
- BLE device name and optional BLE Pair Code
- auto start
- auto restart
- launch at login

Launch at login is implemented as a user-level LaunchAgent:

```text
~/Library/LaunchAgents/local.codex-buddy.menu.plist
```

It opens the `.app` bundle on login. It is only installed when the user toggles
the setting or uses the menu action.

## Runtime Design

The app is intentionally a shell around the already-tested bridge stack:

- Rust tray shell: `apps/codex-buddy-menu`.
- Menu framework: `tray-icon` plus `tao`.
- Preferences UI: `eframe` / `egui`.
- BLE bridge: `CodexBuddyBridge.app`.
- Daemon: bundled `codex-buddy-daemon` when available, otherwise
  `python -m codex_buddy.cli` from the repository.
- Config: `~/.codex/codex-buddy-menu.env`.
- Log: `/tmp/codex-buddy-menu.log`.

When launched from a packaged `.app`, the app prefers bundled resources under
`Contents/Resources`. When launched from the repository, it falls back to the
local repo layout.

## Build Locally

Rust, Python 3.10+, and PyInstaller are required to build the macOS app bundle.
PlatformIO is required only when packaging firmware. The packaged `.app` embeds
`codex-buddy-daemon`, so normal users do not need Python to run the bridge.

```bash
tools/build_menu_bar_app.sh
open tools/CodexBuddyMenu.app
```

Create the menu bar app release zip:

```bash
tools/package_menu_bar_app.sh
```

Create the firmware release images:

```bash
tools/package_firmware_release.sh
```

Generated artifacts are written under:

```text
dist/release/apps/
dist/release/firmware/
```

## GitHub Actions

Release artifacts can also be built by GitHub Actions.

Workflow:

```text
.github/workflows/release-artifacts.yml
```

Triggers:

- manual `workflow_dispatch`
- tag pushes matching `v*`

The workflow builds firmware, builds the macOS app, and uploads
`dist/release` as a workflow artifact. On `v*` tag pushes, it also attaches all
generated firmware and app artifacts to the matching GitHub Release.

## Current Signing Boundary

The local MVP uses ad-hoc signing:

```bash
codesign -s - --force --deep tools/CodexBuddyMenu.app
```

This is enough for local testing and unsigned release candidates, but it is not
Developer ID signed or notarized. If macOS blocks the release app after unzip,
users must clear quarantine once:

```bash
xattr -dr com.apple.quarantine CodexBuddyMenu.app
```

Before a polished public macOS release, add:

- Developer ID signing.
- notarization.
- ideally a `.dmg` or signed `.pkg` distribution.

## Why Keep Python

The app is a productized launcher, not a replacement for the development API.
Keeping the Python bridge commands visible has two benefits:

- contributors can debug and extend transports without rebuilding the app;
- AI-assisted deployment can still run the same commands shown in docs and
  scripts.

The release should therefore ship the convenient app for normal users while
keeping CLI scripts in the repository for developers.
