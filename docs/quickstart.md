# M5 Codex Buddy Quick Start

This guide is the shortest path from a flashed M5 Cardputer ADV to a working
Codex hardware approval flow.

## Prerequisites

- macOS with Codex CLI available as `codex`.
- M5 Cardputer ADV.
- This repository at `/path/to/Codex_buddy_Cardputer_ADV_Alice`.
- Project Python environment:

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
./.venv/bin/python --version
./.venv/bin/pio --version
```

The CLI launcher uses temporary Codex `-c` arguments. It does not modify
`~/.codex/config.toml`. Codex Desktop integration is opt-in and is managed by
`codex-buddy desktop`.

The persistent hook installed by `codex-buddy desktop install` lives in Codex's
shared `~/.codex/config.toml`. Codex Desktop and bare `codex` CLI can both read
it. That persistent hook only handles approval requests; heartbeat Status sync
still needs the menu bar bridge, `codex-buddy start`, or `codex-buddy watch`.

## Build and Flash

Put the device in download mode:

1. Unplug USB-C.
2. Switch the top power switch to `OFF`.
3. Hold `G0`.
4. Plug USB-C into the Mac.
5. Wait about one second, then release `G0`.

Confirm the port:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli ports
```

Build and flash:

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice/firmware
../.venv/bin/pio run -e cardputer-adv
../.venv/bin/pio run -e cardputer-adv -t upload --upload-port /dev/cu.usbmodem1101
```

Return to normal boot:

1. Unplug USB-C.
2. Switch the top power switch to `ON`.
3. Do not hold `G0`.
4. Plug USB-C back in.

## BLE Path

BLE is the fallback and local setup path.

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli once \
  --transport ble-socket \
  --ble-device-name Codex-Buddy \
  --ble-pair-code <six-digit-code>
```

Expected response:

```json
{"v":0,"type":"device_status","status":"heartbeat_applied","state":"running","animation":"running"}
```

If macOS asks for Bluetooth permission, allow `Codex Buddy Bridge`. On firmware
`0.3.27-ble-pair` or later, read the six-digit code from the device `Device`
page. Leave `--ble-pair-code` empty only for older firmware without Pair Code.

## WiFi Path

On the device, open `Menu -> WiFi` and set:

- SSID and password.
- Host: the Mac LAN IP, for example `192.168.1.34`.
- Port: `47392`.
- Token: optional. Leave empty only on a trusted local network.

Then press `Connect`.

When editing SSID, password, host, port, or token on firmware
`0.3.18-wifi-cursor` or later, `Fn+,` / `Fn+/` and HID left/right move the
cursor. `Del` removes the character before the cursor. Password and token fields
show cursor position and length without revealing the secret.

On the Mac:

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli once \
  --transport wifi-server \
  --wifi-port 47392 \
  --wifi-timeout 20
```

If you use a token, pass the same token:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli once \
  --transport wifi-server \
  --wifi-token "$CODEX_BUDDY_WIFI_TOKEN"
```

## Codex CLI Session Sync

For Codex CLI, the integrated path is `codex-buddy start`. It starts the
heartbeat background process, launches Codex CLI, and injects the temporary
approval hook:

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli start \
  --transport auto \
  --cwd /path/to/Codex_buddy_Cardputer_ADV_Alice
```

The background heartbeat is scoped to:

- `session_meta.cwd == --cwd`

Within that cwd, Codex Buddy follows the session that is actually active: a
fresh TUI exchange can move the hardware Status screen to TUI, while a Desktop
approval hook records the Desktop `session_id` and moves the Status screen to
Desktop. The active marker is not permanent; newer matching activity can take
over.

Running bare `codex` in a terminal does not start Codex Buddy heartbeat sync.
It can still write a Codex session file. If a `codex-buddy start` background
watcher is already running for the same cwd, it can pick up that activity. If no
watcher is running, no process will continuously push that file to the
Cardputer.

If you installed the persistent Codex hook from the menu bar app or
`codex-buddy desktop install`, bare `codex` can also route approval requests to
the hardware. Without that persistent hook, use `codex-buddy start` so the hook
is injected temporarily for that CLI session.

To attach an already running bare CLI session for status-only sync, run a
separate watcher. Add `--session-source cli` only when you explicitly want to
ignore Desktop sessions in the same cwd:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli watch \
  --transport auto \
  --session-cwd /path/to/Codex_buddy_Cardputer_ADV_Alice \
  --session-source cli \
  --interval 2
```

For a one-shot smoke test against the latest CLI session in that cwd:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli once \
  --transport auto \
  --session-cwd /path/to/Codex_buddy_Cardputer_ADV_Alice \
  --session-source cli
```

## Daily Start

Use `auto` for the normal path. It prefers WiFi and falls back to BLE.

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor --timeout 8
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor --timeout 8 --json
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli logs --lines 80
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli exit-codes

PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli start \
  --transport auto \
  --wifi-port 47392 \
  "Run exactly this command once: python3 -c 'print(\"codex-buddy-ok\")'"
```

`start` writes:

- Background log: `/tmp/codex-buddy-watch.log`
- Background status: `/tmp/codex-buddy-start-status.json`

Before launching Codex, `start` preflights the working directory, Python,
Codex binary, hook runner, BLE helper, and serial port arguments. Startup
failures should be short stderr messages rather than Python tracebacks.

Exit code semantics:

- `0`: success.
- `1`: runtime transport, hook, or live command failure.
- `2`: invalid CLI usage.
- `78`: local launcher configuration error.
- `130`: interrupted by `Ctrl-C`.

`doctor` also reads the status file and prints `start-status`, including
background state, PID, restart count, last exit code, update time, and log path.
Use `doctor --json` when another tool or session needs machine-readable
diagnostics.

Use `logs --lines 80` when `start` behaves oddly and you need the latest
background status plus the watch / WiFi bridge log tail without manually opening
`/tmp/codex-buddy-watch.log`.

## Optional LaunchAgent

The project does not install a login item automatically. To inspect the
LaunchAgent that would keep `codex-buddy watch --transport auto` alive after
login:

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli launch-agent print
```

If you decide to enable it later, install it explicitly:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli launch-agent install
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli launch-agent status
```

To remove it:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli launch-agent uninstall
```

The LaunchAgent runs only the heartbeat watch. Keep using `codex-buddy start`
when you want to launch a Codex TUI session with hardware approvals.

## Persistent Codex Hook

Use this when you want Codex Desktop, or bare `codex` CLI launched separately,
to send `PermissionRequest` approvals to the hardware through a persistent
Codex hook.

First inspect the current status:

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop status
```

Print the exact managed config block without writing anything:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop print \
  --python /path/to/Codex_buddy_Cardputer_ADV_Alice/.venv/bin/python \
  --transport ble-socket
```

Install the managed hook only after reviewing the printed block:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop install \
  --python /path/to/Codex_buddy_Cardputer_ADV_Alice/.venv/bin/python \
  --transport ble-socket
```

`desktop install` appends a marked `# BEGIN CODEX BUDDY DESKTOP HOOK` block to
`~/.codex/config.toml` and writes a timestamped backup next to it. It refuses to
overwrite an existing unmanaged `PermissionRequest` hook unless `--force` is
provided.

To remove only the managed block:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop uninstall
```

For Desktop status updates without starting a CLI session, keep the optional
LaunchAgent watch enabled or run `codex-buddy watch --transport auto` manually.
Desktop approval via WiFi should use `--transport local-bridge` and requires a
separate long-lived `codex-buddy wifi-bridge` process before an approval request
arrives. The default Desktop path is `ble-socket` because it can start the BLE
helper on demand and does not bind the WiFi server port per hook invocation.

## Hardware Approval Keys

- Approve: `Y`, `Enter`, or `Space`.
- Deny: `N`, `Del`, or `Back`.
- Menu navigation: `W/S`, and `Fn` + arrow keys where exposed by Cardputer.

## Minimum Regression Checklist

Run these before a release:

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
./.venv/bin/python tools/release_check.py
./.venv/bin/python tools/release_check.py --report-json /tmp/codex-buddy-release-check.json
./.venv/bin/python tools/release_check.py --report-md /tmp/codex-buddy-release-check.md
./.venv/bin/python tools/release_check.py --report-dir /tmp/codex-buddy-release-check
```

Hardware smoke:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor --timeout 8
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli soak --transport auto --count 30
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli soak --transport auto --count 30 --json
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli approval-demo \
  --transport auto \
  --id release-smoke-approval
```

Use the plain `soak` output for live reading. Use `soak --json` when saving a
machine-readable evidence file for another session or a release report. Use
`release_check.py --report-json <path>` when you want one local gate report that
still prints the normal terminal summary. Use `release_check.py --report-md <path>`
for a human-readable release note. Use `release_check.py --report-dir <dir>` to
write both files from one run.

## Troubleshooting

No `/dev/cu.usbmodem1101`:

- If flashing, re-enter download mode with `G0` held while plugging USB-C.
- If normally booted, USB serial may not enumerate; use BLE or WiFi.

BLE helper not responding:

- Check macOS Bluetooth permission for `Codex Buddy Bridge`.
- Re-run `doctor --timeout 8`.
- If the app was rebuilt, macOS may require permission again.

WiFi heartbeat times out:

- Confirm device WiFi page shows `connected`.
- Confirm Host is the Mac LAN IP, not `127.0.0.1`.
- Confirm Port is `47392`.
- If token is set on one side, it must match on both sides.
- If the WiFi port is busy, stop the other `codex-buddy` process or change
  `--wifi-port`.

`auto` falls back to BLE:

- This is expected if WiFi does not return a heartbeat within the probe window.
- Increase `--auto-probe-timeout` only if WiFi is known to be online but slow.

Approval request appears stuck:

- Check the device screen for an active approval card.
- Run `doctor` in another terminal and inspect `start-status`.
- Tail `/tmp/codex-buddy-watch.log`.
- Run `logs --lines 80` to inspect the latest bridge/watch status and log tail.

Screen goes dark:

- Press any key or move the device if `Pet motion` is enabled.
- If testing approval behavior, disable sleep in device Settings to remove that
  variable during the test.

For the full local and hardware release gate, see `docs/release-checklist.md`.
