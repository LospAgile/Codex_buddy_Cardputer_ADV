# Codex Buddy Cardputer ADV Alice

[中文文档](README.zh-CN.md)

Codex Buddy Cardputer ADV Alice turns an M5Stack Cardputer ADV into a small
hardware desk pet and approval terminal for Codex.

It mirrors compact Codex session activity on the device, shows the Alice pet,
and lets you approve or deny Codex permission requests from hardware. It works
with Codex CLI and Codex Desktop. The default transport is BLE, with optional
WiFi long-link support.

This repository is a Codex-focused implementation. It does not require Claude
Desktop, Claude hardware access, or Anthropic hardware permissions.

## Highlights

- Alice pet animation on M5Stack Cardputer ADV.
- Compact session activity: `user`, `Agent`, and `tool` entries.
- Hardware approvals: `Y`, `Enter`, or `Space` approve; `N`, `Del`, or `Back`
  deny.
- Codex CLI mode through a temporary hook launcher.
- Codex Desktop mode through an explicit managed `PermissionRequest` hook.
- BLE helper for macOS, including device-name filtering and optional Pair Code.
- Optional WiFi bridge with local token support.
- macOS menu bar app for normal users.
- Chinese / English firmware UI.
- PET Stats, SFX, LED feedback, IMU tilt motion, and auto sleep.
- Custom Codex Desktop pet rebuild flow.
- Ready-to-flash Alice release firmware.

## Repository Layout

```text
daemon/              macOS-side Python daemon and CLI
firmware/            PlatformIO firmware for M5Stack Cardputer ADV
apps/codex-buddy-menu
                     Rust macOS menu bar app
tools/               BLE helper, pet asset generator, release checks
examples/pets/alice  Default Alice pet package
release/firmware/    Ready-to-flash firmware binary
release/apps/        macOS menu bar app zip
docs/                Quick start, Desktop, app, pet, protocol, release docs
AI_DEPLOYMENT.md     Deployment guide for AI coding agents
```

## No-Code Install: Alice Firmware + Menu Bar App

For most users, use the two prebuilt release files:

```text
release/firmware/codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin
release/apps/CodexBuddyMenu-v0.1.0-macos-arm64.zip
```

The firmware binary in this repository is the Alice build: it boots with Alice
as the default hardware pet.

1. Flash `codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin` to Cardputer ADV.
2. Unzip `CodexBuddyMenu-v0.1.0-macos-arm64.zip`.
3. Clear macOS quarantine on the current unsigned preview app, then open it:

```bash
unzip CodexBuddyMenu-v0.1.0-macos-arm64.zip
xattr -dr com.apple.quarantine CodexBuddyMenu.app
open CodexBuddyMenu.app
```

4. Choose `Connection Guide -> Connect with BLE...` and enter the Pair Code from
   the device `Device` page, or use `Connect with WiFi...` for LAN mode.
5. Use `Install Desktop Hook...` only if you want Codex Desktop integration.

The macOS app is currently ad-hoc signed and not notarized. If macOS says the
app cannot be opened because the developer cannot be verified, run the `xattr`
command above once after unzipping.

`Install Desktop Hook...` writes a managed Codex `PermissionRequest` hook into
`~/.codex/config.toml`. Codex Desktop and bare `codex` CLI can both read that
same config. It does not start the heartbeat watcher by itself; keep the menu
bar bridge running, or use `codex-buddy start` for the all-in-one CLI flow.

Developers can still use the Python CLI directly.

## Fastest Path: Flash The Release Firmware

Use the merged binary:

```text
release/firmware/codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin
```

This is the Alice firmware build.

Put Cardputer ADV into download mode:

1. Turn the top power switch OFF.
2. Hold `G0`.
3. Plug USB-C into the Mac.
4. Wait one second.
5. Release `G0`.

Flash with M5Burner, ESP tools, or this command:

```bash
python3 -m pip install esptool
esptool.py --chip esp32s3 --port /dev/cu.usbmodemXXXX --baud 1500000 \
  write_flash 0x0 release/firmware/codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin
```

Normal boot:

1. Unplug USB-C.
2. Turn the top power switch ON.
3. Do not hold `G0`.
4. Plug USB-C back in.

## Install From Source

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e daemon -r requirements-dev.txt
tools/build_ble_bridge_app.sh
tools/build_menu_bar_app.sh
```

Build firmware:

```bash
./.venv/bin/python -m pip install platformio
./.venv/bin/pio run -d firmware -e cardputer-adv
```

Flash source-built firmware:

```bash
./.venv/bin/pio run -d firmware -e cardputer-adv -t upload \
  --upload-port /dev/cu.usbmodemXXXX
```

## Build Release Artifacts On GitHub

The repository includes a GitHub Actions workflow:

```text
.github/workflows/release-artifacts.yml
```

It can be run manually from GitHub Actions, or by pushing a `v*` tag. The
workflow builds the Alice firmware, builds the macOS menu bar app, uploads
`dist/release`, and attaches the generated files to the GitHub Release for tag
builds.

## Codex CLI Mode

If you use the menu bar app, set the transport there and start the bridge first.
The CLI flow below is the developer-friendly equivalent.

For CLI users there are two supported patterns:

- `codex-buddy start`: launches Codex CLI with a temporary approval hook and
  starts heartbeat sync. It does not modify `~/.codex/config.toml`.
- bare `codex`: can use the persistent hook installed by `Install Desktop
  Hook...`, because Codex Desktop and CLI share Codex hook config. Keep the menu
  bar bridge or a separate watcher running if you also want live Status updates.

Check the hardware link first:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor --timeout 8
```

Start Codex CLI with the hardware approval hook:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli start \
  --transport ble-socket
```

After WiFi is configured on the device, you can use auto transport:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli start \
  --transport auto
```

`auto` tries WiFi first and falls back to BLE when WiFi is unavailable.

### BLE Pair Code

Firmware `0.3.27-ble-pair` and later shows a six-digit Pair Code on the device
`Device` page. The menu bar app asks for it during BLE setup. CLI users can pass
it explicitly:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor \
  --transport ble-socket \
  --ble-device-name Codex-Buddy \
  --ble-pair-code 123456
```

Leave the pair code empty only for older firmware that does not show a code.

## Persistent Codex Hook For Desktop And Bare CLI

This mode uses a managed Codex `PermissionRequest` hook in
`~/.codex/config.toml`. It is named "Desktop Hook" in the menu because Desktop is
the common reason to install it, but the config is shared by Codex Desktop and
bare `codex` CLI.

Preview the config block first:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop print \
  --python "$PWD/.venv/bin/python" \
  --transport ble-socket
```

Install only after you have reviewed it:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop install \
  --python "$PWD/.venv/bin/python" \
  --transport ble-socket
```

The installer writes only a managed block between:

```text
# BEGIN CODEX BUDDY DESKTOP HOOK
# END CODEX BUDDY DESKTOP HOOK
```

It also creates a timestamped backup next to `~/.codex/config.toml`.

Restart Codex Desktop after installation. When Desktop triggers a permission
request, the device will show the approval card. The hook records the active
Desktop session id, so later heartbeat updates can keep showing the same
Desktop conversation activity.

The menu bar app can install and uninstall the same managed hook from the menu.
It uses the bundled daemon helper, so normal users do not need to locate the
Python entry point manually.

Uninstall:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop uninstall
```

## WiFi Mode

On the device WiFi page, set:

- SSID and password.
- Mac LAN IP as `Host`.
- `47392` as `Port`.
- Optional token.

Run the bridge:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli wifi-bridge \
  --wifi-host 0.0.0.0 \
  --wifi-port 47392
```

For Codex Desktop over WiFi, keep `wifi-bridge` running and install Desktop
hook with `--transport local-bridge`. Do not install the Desktop hook directly
with `--transport wifi-server`.

## Custom Pets

The hardware pet is compiled into firmware. It is not downloaded dynamically at
runtime.

Your Codex Desktop pet package should look like:

```text
~/.codex/pets/<pet-id>/pet.json
~/.codex/pets/<pet-id>/spritesheet.webp
```

Current firmware asset rules:

- `spritesheet.webp`: `1536x1872`.
- Atlas: `8 x 9`.
- Cell: `192x208`.
- Firmware frame output: `72x78`.
- Firmware frame count: `57`.
- Expected animation rows: idle, running-right, running-left, waving, jumping,
  failed, waiting, running, review.

Validate a pet:

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

Then rebuild and flash firmware.

## For AI Coding Agents

Use [AI_DEPLOYMENT.md](AI_DEPLOYMENT.md).

That file is intentionally written as an operational deployment guide for AI
coding agents. If a user drops this repository into Codex and says "deploy
this", start there.

## Development Checks

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m unittest discover daemon/tests
PYTHONPATH=daemon/src ./.venv/bin/python tools/release_check.py --skip-firmware
./.venv/bin/pio run -d firmware -e cardputer-adv
```

## Why Alice Is The Default Pet

Alice is a desktop AI Agent created by
[Luoxiaoshan](https://luoxiaoshan.cn/). It is designed less as a generic tool
and more as a companion with personality, memory, and a cast of agent friends
who help with everyday work such as posters, AI learning, reports, and
multi-agent analysis.

Official Alice site: [alice.miyang.cn](https://alice.miyang.cn/)

This repository uses Alice as the default pet because the goal is not to ship a
generic sample mascot. The goal is to show that a real desktop Agent with its
own character can become a physical hardware companion on your desk.

If you want a different pet, replace Alice with your own Codex Desktop pet
package and rebuild the firmware.

## License

MIT. See [LICENSE](LICENSE).

## Friendship Link 友情链接

Thanks for the support and feedback from the friends at
[LINUX DO](https://linux.do/).

感谢 [LINUX DO](https://linux.do/) 朋友们的支持和反馈。

Friendly links:

- [Anthropic Claude Desktop Buddy](https://github.com/anthropics/claude-desktop-buddy)
- [claude-desktop-buddy-cardputer by y88huang](https://github.com/y88huang/claude-desktop-buddy-cardputer)
- [M5Burner documentation](https://docs.m5stack.com/en/uiflow/m5burner/intro)
- [M5Stack UIFlow MicroPython](https://github.com/m5stack/uiflow-micropython)

The original idea of a hardware buddy for coding-agent approvals was strongly
influenced by Claude Desktop Buddy. This project keeps that useful hardware
approval pattern, but rebuilds the firmware, daemon, protocol, and Desktop
integration around Codex and the Codex Desktop pet model.

It is not affiliated with Anthropic, OpenAI, or M5Stack.
