from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import selectors
import shlex
import subprocess
import time
from typing import Any


BEGIN_MARKER = "# BEGIN CODEX BUDDY DESKTOP HOOK"
END_MARKER = "# END CODEX BUDDY DESKTOP HOOK"
MANAGED_BLOCK_RE = re.compile(
    rf"\n?{re.escape(BEGIN_MARKER)}\n.*?\n{re.escape(END_MARKER)}\n?",
    re.DOTALL,
)


class DesktopConfigError(RuntimeError):
    pass


class AppServerError(RuntimeError):
    pass


@dataclass(frozen=True)
class DesktopHookOptions:
    codex_bin: str
    cwd: Path
    python: Path
    daemon_src: Path
    transport: str
    hook_binary: Path | None = None
    hook_timeout: int = 120
    status_message: str = "Waiting for Codex Buddy hardware approval"
    serial_port: Path | None = None
    baud: int = 115200
    ble_app: Path | None = None
    ble_port: int = 47391
    ble_timeout: float = 30.0
    ble_device_name: str = "Codex-Buddy"
    ble_pair_code: str = ""
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 47393
    bridge_timeout: float = 120.0


def build_desktop_hook_command(options: DesktopHookOptions) -> str:
    env_prefix: list[str] = []
    if options.hook_binary is not None:
        command = [
            str(_absolute_path(options.hook_binary)),
            "approval-hook",
            "--transport",
            options.transport,
            "--approval-timeout",
            str(options.hook_timeout),
        ]
    else:
        command = [
            str(_absolute_path(options.python)),
            "-m",
            "codex_buddy.cli",
            "approval-hook",
            "--transport",
            options.transport,
            "--approval-timeout",
            str(options.hook_timeout),
        ]
        env_prefix.append(
            f"PYTHONPATH={shlex.quote(str(_absolute_path(options.daemon_src)))}"
        )
    if options.transport in {"ble-app", "ble-socket"}:
        if options.ble_app is None:
            raise DesktopConfigError("BLE transport needs a BLE helper app path")
        command.extend(["--ble-app", str(_absolute_path(options.ble_app))])
        command.extend(["--ble-timeout", str(options.ble_timeout)])
        command.extend(["--ble-device-name", options.ble_device_name])
        if options.ble_pair_code:
            command.extend(["--ble-pair-code", options.ble_pair_code])
    if options.transport == "ble-socket":
        command.extend(["--ble-port", str(options.ble_port)])
    if options.transport == "serial":
        if options.serial_port is None:
            raise DesktopConfigError("--serial-port is required for serial transport")
        command.extend(["--serial-port", str(_absolute_path(options.serial_port))])
        command.extend(["--baud", str(options.baud)])
    if options.transport == "local-bridge":
        command.extend(["--bridge-host", options.bridge_host])
        command.extend(["--bridge-port", str(options.bridge_port)])
        command.extend(["--bridge-timeout", str(options.bridge_timeout)])

    return " ".join([*env_prefix, shlex.join(command)])


def build_inline_hooks_config(
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


def build_desktop_config_block(
    *,
    hook_command: str,
    timeout_sec: int,
    status_message: str,
    trusted_key: str,
    trusted_hash: str,
) -> str:
    hook = (
        "{ "
        'type = "command", '
        f"command = {toml_quote(hook_command)}, "
        f"timeout = {max(1, int(timeout_sec))}, "
        f"statusMessage = {toml_quote(status_message)}"
        " }"
    )
    return "\n".join(
        [
            BEGIN_MARKER,
            "# Managed by codex-buddy desktop. Remove via `codex-buddy desktop uninstall`.",
            "[hooks]",
            f"PermissionRequest = [{{ hooks = [{hook}] }}]",
            "",
            f"[hooks.state.{toml_quote(trusted_key)}]",
            f"trusted_hash = {toml_quote(trusted_hash)}",
            END_MARKER,
            "",
        ]
    )


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
            "name": "codex-buddy-desktop-probe",
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


def install_managed_config_block(
    config_path: Path,
    block: str,
    *,
    force: bool = False,
) -> Path:
    config_path = config_path.expanduser()
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    stripped = remove_managed_config_block(text)
    if not force and contains_unmanaged_permission_hook(stripped):
        raise DesktopConfigError(
            "existing unmanaged PermissionRequest hook found in config.toml; "
            "use --force only after reviewing the existing hook config"
        )

    config_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = backup_config(config_path)
    prefix = stripped.rstrip()
    new_text = f"{prefix}\n\n{block}" if prefix else block
    config_path.write_text(new_text, encoding="utf-8")
    return backup_path


def uninstall_managed_config_block(config_path: Path) -> tuple[bool, Path | None]:
    config_path = config_path.expanduser()
    if not config_path.exists():
        return False, None
    text = config_path.read_text(encoding="utf-8")
    cleaned = remove_managed_config_block(text)
    if cleaned == text:
        return False, None
    backup_path = backup_config(config_path)
    config_path.write_text(cleaned.rstrip() + "\n", encoding="utf-8")
    return True, backup_path


def desktop_config_status(config_path: Path) -> dict[str, object]:
    config_path = config_path.expanduser()
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    return {
        "config_path": str(config_path),
        "exists": config_path.exists(),
        "managed": BEGIN_MARKER in text and END_MARKER in text,
        "unmanaged_permission_hook": contains_unmanaged_permission_hook(
            remove_managed_config_block(text)
        ),
    }


def remove_managed_config_block(text: str) -> str:
    return MANAGED_BLOCK_RE.sub("\n", text).strip() + ("\n" if text.strip() else "")


def contains_unmanaged_permission_hook(text: str) -> bool:
    if re.search(r"(?m)^\s*hooks\.PermissionRequest\s*=", text):
        return True
    lines = text.splitlines()
    in_hooks = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped == "[hooks]":
                return True
            in_hooks = False
            if stripped.startswith("[hooks."):
                return True
            continue
        if in_hooks and stripped.startswith("PermissionRequest"):
            return True
    return False


def backup_config(config_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = config_path.with_name(f"{config_path.name}.codex-buddy-backup-{timestamp}")
    if config_path.exists():
        backup_path.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        backup_path.write_text("", encoding="utf-8")
    return backup_path


def toml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


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


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return Path.cwd() / expanded
