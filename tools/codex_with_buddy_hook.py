#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import selectors
import shlex
import subprocess
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DAEMON_SRC = PROJECT_ROOT / "daemon" / "src"
DEFAULT_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
DEFAULT_BLE_APP = PROJECT_ROOT / "tools" / "CodexBuddyBridge.app"


class AppServerError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except AppServerError as exc:
        print(f"codex-buddy hook runner: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(
            f"codex-buddy hook runner: failed to launch process: {exc}",
            file=sys.stderr,
        )
        return 1


def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    hook_command = build_hook_command(args)
    bare_config = build_hooks_config(
        hook_command=hook_command,
        timeout_sec=args.hook_timeout,
        status_message=args.status_message,
    )
    hook_info = probe_hook_info(
        codex_bin=args.codex_bin,
        cwd=args.cwd.resolve(),
        hooks_config=bare_config,
        hook_command=hook_command,
        timeout_sec=args.probe_timeout,
    )
    trusted_config = build_hooks_config(
        hook_command=hook_command,
        timeout_sec=args.hook_timeout,
        status_message=args.status_message,
        trusted_key=hook_info["key"],
        trusted_hash=hook_info["currentHash"],
    )
    codex_args = build_codex_args(args, trusted_config)

    if args.print_config:
        print(trusted_config)
        return 0
    if args.print_command:
        print(shlex.join(codex_args))
        return 0

    os.execvp(codex_args[0], codex_args)
    return 127


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run Codex with a temporary trusted PermissionRequest hook that "
            "routes approvals through Codex Buddy hardware."
        )
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--cwd", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument(
        "--transport",
        choices=["stdout", "serial", "ble-app", "ble-socket", "local-bridge"],
        default="ble-socket",
    )
    parser.add_argument("--serial-port", type=Path)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--ble-app", type=Path, default=DEFAULT_BLE_APP)
    parser.add_argument("--ble-port", type=int, default=47391)
    parser.add_argument("--ble-timeout", type=float, default=30.0)
    parser.add_argument("--ble-device-name", default="Codex-Buddy")
    parser.add_argument("--ble-pair-code", default="")
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=47393)
    parser.add_argument("--bridge-timeout", type=float, default=120.0)
    parser.add_argument("--hook-timeout", type=int, default=120)
    parser.add_argument("--probe-timeout", type=float, default=20.0)
    parser.add_argument("--approval-policy", default="untrusted")
    parser.add_argument(
        "--status-message",
        default="Waiting for Codex Buddy hardware approval",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="print the final codex command instead of executing it",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="print only the temporary -c hook config instead of executing Codex",
    )
    parser.add_argument(
        "--alt-screen",
        action="store_true",
        help="allow Codex to use the terminal alternate screen",
    )
    parser.add_argument(
        "prompt",
        nargs=argparse.REMAINDER,
        help="optional prompt passed to Codex; prefix with -- if needed",
    )
    parsed = parser.parse_args(argv)
    if parsed.prompt and parsed.prompt[0] == "--":
        parsed.prompt = parsed.prompt[1:]
    return parsed


def build_hook_command(args: argparse.Namespace) -> str:
    command = [
        str(absolute_path(args.python)),
        "-m",
        "codex_buddy.cli",
        "approval-hook",
        "--transport",
        args.transport,
        "--approval-timeout",
        str(args.hook_timeout),
    ]
    if args.transport in {"ble-app", "ble-socket"}:
        command.extend(["--ble-app", str(absolute_path(args.ble_app))])
        command.extend(["--ble-timeout", str(args.ble_timeout)])
        command.extend(["--ble-device-name", args.ble_device_name])
        if args.ble_pair_code:
            command.extend(["--ble-pair-code", args.ble_pair_code])
    if args.transport == "ble-socket":
        command.extend(["--ble-port", str(args.ble_port)])
    if args.transport == "serial":
        if not args.serial_port:
            raise SystemExit("--serial-port is required when --transport serial is used")
        command.extend(["--serial-port", str(absolute_path(args.serial_port))])
        command.extend(["--baud", str(args.baud)])
    if args.transport == "local-bridge":
        command.extend(["--bridge-host", args.bridge_host])
        command.extend(["--bridge-port", str(args.bridge_port)])
        command.extend(["--bridge-timeout", str(args.bridge_timeout)])

    return " ".join(
        [
            f"PYTHONPATH={shlex.quote(str(DAEMON_SRC))}",
            shlex.join(command),
        ]
    )


def absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path.cwd() / expanded


def build_hooks_config(
    *,
    hook_command: str,
    timeout_sec: int,
    status_message: str,
    trusted_key: str | None = None,
    trusted_hash: str | None = None,
) -> str:
    hook = ",".join(
        [
            'type="command"',
            f"command={toml_quote(hook_command)}",
            f"timeout={max(1, int(timeout_sec))}",
            f"statusMessage={toml_quote(status_message)}",
        ]
    )
    fields = [f"PermissionRequest=[{{hooks=[{{{hook}}}]}}]"]
    if trusted_key and trusted_hash:
        fields.append(
            "state={"
            f"{toml_quote(trusted_key)}={{trusted_hash={toml_quote(trusted_hash)}}}"
            "}"
        )
    return "hooks={" + ",".join(fields) + "}"


def toml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def probe_hook_info(
    *,
    codex_bin: str,
    cwd: Path,
    hooks_config: str,
    hook_command: str,
    timeout_sec: float,
) -> dict[str, str]:
    proc = subprocess.Popen(
        [
            codex_bin,
            "-c",
            hooks_config,
            "app-server",
            "--listen",
            "stdio://",
        ],
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        send_jsonrpc(proc, 0, "initialize", initialize_params())
        read_response(proc, 0, timeout_sec)
        send_notification(proc, "initialized")
        send_jsonrpc(proc, 1, "hooks/list", {"cwds": [str(cwd)]})
        response = read_response(proc, 1, timeout_sec)
        return select_permission_hook(response, hook_command)
    finally:
        stop_process(proc)


def initialize_params() -> dict[str, Any]:
    return {
        "clientInfo": {
            "name": "codex-buddy-hook-probe",
            "title": None,
            "version": "0.1.0",
        },
        "capabilities": {"experimentalApi": True},
    }


def send_jsonrpc(
    proc: subprocess.Popen[str],
    request_id: int,
    method: str,
    params: dict[str, Any] | None = None,
) -> None:
    if proc.stdin is None:
        raise AppServerError("app-server stdin is closed")
    payload: dict[str, Any] = {"id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def send_notification(proc: subprocess.Popen[str], method: str) -> None:
    if proc.stdin is None:
        raise AppServerError("app-server stdin is closed")
    proc.stdin.write(json.dumps({"method": method}, separators=(",", ":")) + "\n")
    proc.stdin.flush()


def read_response(
    proc: subprocess.Popen[str],
    request_id: int,
    timeout_sec: float,
) -> dict[str, Any]:
    if proc.stdout is None:
        raise AppServerError("app-server stdout is closed")

    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_sec
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppServerError(app_server_timeout_message(proc, request_id))
            events = selector.select(remaining)
            if not events:
                continue
            line = proc.stdout.readline()
            if line == "":
                raise AppServerError(app_server_exit_message(proc))
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AppServerError(f"invalid app-server JSON line: {line!r}") from exc
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise AppServerError(f"app-server error: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise AppServerError(f"app-server response missing result: {message}")
            return result
    finally:
        selector.close()


def select_permission_hook(response: dict[str, Any], hook_command: str) -> dict[str, str]:
    for entry in response.get("data", []):
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks", []):
            if not isinstance(hook, dict):
                continue
            event_name = str(hook.get("eventName", "")).lower()
            if event_name not in {"permissionrequest", "permission_request"}:
                continue
            if hook.get("command") != hook_command:
                continue
            key = hook.get("key")
            current_hash = hook.get("currentHash")
            if isinstance(key, str) and isinstance(current_hash, str):
                return {"key": key, "currentHash": current_hash}
    raise AppServerError(
        "PermissionRequest hook was not listed by Codex app-server. "
        "Check that Codex hooks are available in this Codex build."
    )


def build_codex_args(args: argparse.Namespace, hooks_config: str) -> list[str]:
    command = [args.codex_bin]
    if not args.alt_screen:
        command.append("--no-alt-screen")
    command.extend(
        [
            "-a",
            args.approval_policy,
            "-C",
            str(args.cwd.resolve()),
            "-c",
            hooks_config,
        ]
    )
    command.extend(args.prompt)
    return command


def stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def app_server_timeout_message(proc: subprocess.Popen[str], request_id: int) -> str:
    stderr = read_stderr(proc)
    suffix = f" stderr: {stderr}" if stderr else ""
    return f"timed out waiting for app-server response id {request_id}.{suffix}"


def app_server_exit_message(proc: subprocess.Popen[str]) -> str:
    stderr = read_stderr(proc)
    suffix = f" stderr: {stderr}" if stderr else ""
    return f"app-server exited before returning a response.{suffix}"


def read_stderr(proc: subprocess.Popen[str]) -> str:
    if proc.stderr is None:
        return ""
    if proc.poll() is None:
        return ""
    try:
        return proc.stderr.read().strip()
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
