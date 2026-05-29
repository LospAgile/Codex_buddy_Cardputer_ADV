# Codex Buddy Protocol

This document describes the public JSON line protocol between the Mac bridge
and the Cardputer firmware.

## Transport

All messages are UTF-8 JSON followed by `\n`.

Supported transports:

- BLE Nordic UART Service, used by `CodexBuddyBridge.app`.
- WiFi TCP, default daemon listen port `47392`.
- Local bridge IPC, default localhost port `47393`, used by Desktop hooks when
  a long-lived WiFi bridge is already running.

The daemon must send compact summaries only. It should not forward full Codex
conversation logs, secrets, cookies, tokens, or raw tool inputs.

## BLE Pairing

Firmware `0.3.27-ble-pair` and later requires an application-level Pair Code.
The code is shown on the device `Device` page.

Before sending heartbeat or approval messages over BLE, the Mac side sends:

```json
{"v":0,"type":"pair_request","code":"123456"}
```

Success:

```json
{"v":0,"type":"device_status","status":"pair_ok"}
```

Failure:

```json
{"v":0,"type":"error","message":"pair code mismatch"}
```

This is not Bluetooth bonding. It is a small application-level guard to avoid
connecting to the wrong Nordic UART device and to make onboarding clearer.

## WiFi Hello

WiFi can be used without a token on trusted local networks. If a token is
configured, the device sends a hello frame before normal traffic:

```json
{"v":0,"type":"hello","token":"optional-shared-token"}
```

The daemon accepts heartbeat and approval traffic only after the token matches.

## Host To Device

### heartbeat

Updates the Status screen.

```json
{
  "v": 0,
  "type": "heartbeat",
  "state": "running",
  "animation": "running",
  "summary": "Running command",
  "entries": [
    {"kind": "user", "text": "Check the build"},
    {"kind": "assistant", "text": "The build passed"},
    {"kind": "tool", "text": "exec_command"}
  ],
  "pet": {
    "id": "alice",
    "displayName": "Alice"
  }
}
```

`state` values:

- `idle`
- `running`
- `waiting`
- `review`
- `failed`

`animation` values:

- `idle`
- `running`
- `waiting`
- `waving`
- `jumping`
- `review`
- `failed`
- `running-left`
- `running-right`

`entries` are intentionally short. The device is a glanceable status screen, not
a full chat reader.

The optional `pet` field is metadata only. Firmware uses the pet sprite compiled
into `CodexPetSprite.*`; it does not download image assets at runtime.

### approval_request

Shows a hardware approval card.

```json
{
  "v": 0,
  "type": "approval_request",
  "id": "request-id",
  "tool": "exec_command",
  "hint": "Run shell command",
  "choices": ["approve_once", "deny"]
}
```

Device behavior:

- `Y`, `Enter`, or `Space` returns `approve_once`.
- `N`, `Del`, or `Back` returns `deny`.
- The default UI keeps the approval panel inside the Status page.

### wifi_config

Optionally writes WiFi settings to the device over BLE or serial.

```json
{
  "v": 0,
  "type": "wifi_config",
  "ssid": "Office WiFi",
  "password": "secret",
  "host": "192.168.1.10",
  "port": 47392,
  "token": "optional-shared-token",
  "connect": true
}
```

`ssid`, `password`, `host`, `port`, and `token` are partial updates. If
`connect` is true, the device attempts to connect after saving the config.

## Device To Host

### approval_decision

```json
{
  "v": 0,
  "type": "approval_decision",
  "id": "request-id",
  "decision": "approve_once"
}
```

`decision` is either `approve_once` or `deny`.

### device_status

```json
{
  "v": 0,
  "type": "device_status",
  "status": "heartbeat_applied",
  "state": "running",
  "animation": "running"
}
```

Common `status` values:

- `pair_ok`
- `heartbeat_applied`
- `approval_request_applied`
- `wifi_config_applied`

### error

```json
{
  "v": 0,
  "type": "error",
  "message": "pairing required"
}
```

## BLE UUIDs

Nordic UART Service:

- Service: `6e400001-b5a3-f393-e0a9-e50e24dcca9e`
- RX: `6e400002-b5a3-f393-e0a9-e50e24dcca9e`
- TX: `6e400003-b5a3-f393-e0a9-e50e24dcca9e`

## Codex Hook Mapping

The Mac daemon maps Codex `PermissionRequest` hook stdin to `approval_request`.

Important behavior:

- `tool_name` maps to `tool`.
- shell command fields become the approval `hint`.
- sensitive keys such as `password`, `token`, `secret`, `api_key`, `auth`,
  `cookie`, and `credential` are redacted.
- hardware `approve_once` maps to Codex hook allow.
- hardware `deny` maps to Codex hook deny.

If the bridge or device is unavailable, the hook should let Codex fall back to
its own approval UI instead of blocking forever.
