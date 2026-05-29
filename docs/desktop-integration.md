# Persistent Codex Hook

This page covers the opt-in persistent hook path for using M5 Codex Buddy with
Codex Desktop and bare `codex` CLI.

## What It Does

Codex Desktop and Codex CLI both use Codex hook configuration.
`codex-buddy desktop` generates a persistent `PermissionRequest` hook in
`~/.codex/config.toml` that forwards approval requests to the Cardputer.

The runtime path is:

```text
Codex Desktop or bare codex CLI PermissionRequest
  -> ~/.codex/config.toml managed hook
  -> codex-buddy approval-hook
  -> BLE socket or local bridge
  -> Cardputer approval card
  -> approve_once / deny
  -> Codex allow / deny
```

For CLI-only users, `codex-buddy start` is still the easiest path. It injects a
temporary hook and starts heartbeat sync without editing `~/.codex/config.toml`.
The persistent hook is useful when you want separately launched Desktop or CLI
sessions to share the same approval route.

## Safety Model

- Nothing is installed automatically.
- `desktop print` is read-only.
- `desktop install` writes a timestamped backup next to `~/.codex/config.toml`.
- The installed block is wrapped in:
  - `# BEGIN CODEX BUDDY DESKTOP HOOK`
  - `# END CODEX BUDDY DESKTOP HOOK`
- `desktop uninstall` removes only that managed block.
- Existing unmanaged Codex hook config is not overwritten unless `--force` is
  explicitly used.

## BLE Setup

BLE is the recommended first Desktop path because the hook process can start the
BLE helper on demand and does not need to bind the WiFi server port.

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice

PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop status

PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop print \
  --python /path/to/Codex_buddy_Cardputer_ADV_Alice/.venv/bin/python \
  --transport ble-socket \
  --ble-device-name Codex-Buddy \
  --ble-pair-code <six-digit-code>

PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop install \
  --python /path/to/Codex_buddy_Cardputer_ADV_Alice/.venv/bin/python \
  --transport ble-socket \
  --ble-device-name Codex-Buddy \
  --ble-pair-code <six-digit-code>
```

After installing, restart Codex Desktop so it reloads `~/.codex/config.toml`.
For CLI, start a new `codex` process after installing so it reloads the config.
Then trigger a tool call that needs approval and approve or deny it on the
Cardputer.

On firmware `0.3.27-ble-pair` or later, read the six-digit code from the device
`Device` page. The menu bar app can store the same value in Preferences.

The generated hook passes `--approval-timeout` to `codex-buddy approval-hook`.
This keeps Desktop approvals aligned with the Codex hook timeout even if an
older `doctor --timeout <short>` command started the long-lived BLE helper with
a shorter default request timeout.

## Session Activity

Codex Buddy does not only forward approvals. The heartbeat path tails Codex
session JSONL and sends a compact Status summary to the Cardputer:

- recent user request as `user`;
- recent assistant reply as `assistant`;
- recent tool calls as `tool`.

When a Desktop `PermissionRequest` reaches `approval-hook`, the hook records the
Desktop `session_id` into `~/.codex/codex-buddy-active-session.json`. Later
`watch` / `wifi-bridge` heartbeats can prefer that active session, so multiple
Codex windows do not silently steal the hardware Status screen. The active
marker is not a permanent override: if a newer matching session appears after
the marker, the heartbeat can follow the newer session instead.

For Codex CLI Status sessions, prefer `--session-source cli` together with
`--session-cwd` only when you deliberately want a CLI-only watcher. The normal
global desk-pet behavior should leave source unfiltered, so TUI and Desktop can
hand off the hardware Status screen based on the newest activity or approval
marker.

For manual debugging, pin a session explicitly:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli watch \
  --transport ble-socket \
  --session-id 019e63cd-1a05-78b3-ac49-2b1967a39a2e \
  --interval 2
```

Or follow the latest CLI session in a repository:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli watch \
  --transport auto \
  --session-cwd /path/to/Codex_buddy_Cardputer_ADV_Alice \
  --session-source cli \
  --interval 2
```

## WiFi Setup

WiFi Desktop approval should use a long-lived `wifi-bridge`. Do not configure
the persistent Desktop hook to use `wifi-server` directly; a short-lived hook
process would try to bind the WiFi server port per approval.

Terminal 1:

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli wifi-bridge \
  --wifi-host 0.0.0.0 \
  --wifi-port 47392
```

Terminal 2:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop install \
  --python /path/to/Codex_buddy_Cardputer_ADV_Alice/.venv/bin/python \
  --transport local-bridge
```

Restart Codex Desktop after changing the hook config.

## Remove Integration

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli desktop uninstall
```

Restart Codex Desktop after uninstalling.
