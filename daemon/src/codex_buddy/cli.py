from __future__ import annotations

import argparse
from contextlib import suppress
import json
import math
import os
from pathlib import Path
import plistlib
import shutil
import shlex
import subprocess
import sys
import threading
import time
from typing import TextIO

from .codex_hook import hook_context_from_input, run_permission_request_hook
from .desktop_config import (
    AppServerError,
    DesktopConfigError,
    DesktopHookOptions,
    build_desktop_config_block,
    build_desktop_hook_command,
    build_inline_hooks_config,
    desktop_config_status,
    install_managed_config_block,
    probe_hook_info,
    uninstall_managed_config_block,
)
from .protocol import ApprovalRequest, Heartbeat, WifiConfigRequest
from .pet_assets import load_pet_dir, load_selected_pet, validate_pet_asset
from .session_tailer import default_codex_home, record_active_session, snapshot_latest_session
from .transport import (
    AutoStatusTransport,
    DEFAULT_BLE_DEVICE_NAME,
    LocalBridgeTransport,
    MacOSBleAppTransport,
    MacOSBleSocketTransport,
    resolve_ble_app,
    SerialTransport,
    StdoutTransport,
    Transport,
    WiFiServerTransport,
)
from .wifi_bridge import WifiBridgeServer


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BLE_APP = PROJECT_ROOT / "tools" / "CodexBuddyBridge.app"
DEFAULT_HOOK_RUNNER = PROJECT_ROOT / "tools" / "codex_with_buddy_hook.py"
DEFAULT_WATCH_LOG = Path("/tmp/codex-buddy-watch.log")
DEFAULT_START_STATUS = Path("/tmp/codex-buddy-start-status.json")
DEFAULT_LAUNCH_AGENT_LABEL = "com.codexbuddy.watch"
DEFAULT_LAUNCH_AGENT_LOG = Path("/tmp/codex-buddy-launch-agent.log")
DEFAULT_WATCH_LOG_MAX_BYTES = 1_000_000
DEFAULT_AUTO_PROBE_TIMEOUT = 20.0
DEFAULT_BACKGROUND_RESTART_DELAY = 1.0
DEFAULT_BACKGROUND_MONITOR_INTERVAL = 0.25
AUTO_WIFI_TRANSPORT = "wifi-server"
AUTO_FALLBACK_TRANSPORT = "ble-socket"
EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE = 2
EXIT_CONFIG = 78
EXIT_INTERRUPTED = 130


EXIT_CODE_ROWS = [
    (EXIT_OK, "ok", "command completed successfully"),
    (EXIT_RUNTIME_ERROR, "runtime-error", "transport, hook, or live command failed"),
    (EXIT_USAGE, "usage", "invalid CLI arguments"),
    (EXIT_CONFIG, "config-error", "local launcher configuration is invalid"),
    (EXIT_INTERRUPTED, "interrupted", "interrupted by Ctrl-C / SIGINT"),
]


class LauncherError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-buddy")
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=default_codex_home(),
        help="Codex home directory, defaults to CODEX_HOME or ~/.codex",
    )

    subparsers = parser.add_subparsers(dest="command")

    once = subparsers.add_parser("once", help="emit one heartbeat")
    _add_session_args(once)
    _add_transport_args(once)

    watch = subparsers.add_parser("watch", help="emit heartbeat repeatedly")
    watch.add_argument("--interval", type=float, default=2.0)
    _add_session_args(watch)
    _add_transport_args(watch)

    soak = subparsers.add_parser(
        "soak",
        help="run repeated heartbeat checks and print latency statistics",
    )
    soak.add_argument("--count", type=int, default=30)
    soak.add_argument("--interval", type=float, default=2.0)
    soak.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable results",
    )
    _add_transport_args(soak, default_transport="auto")

    approval_demo = subparsers.add_parser(
        "approval-demo",
        help="send a sample approval_request to the device",
    )
    approval_demo.add_argument("--id", default="demo-approval")
    approval_demo.add_argument("--tool", default="exec_command")
    approval_demo.add_argument("--hint", default="Demo approval from Codex Buddy")
    approval_demo.add_argument("--approval-timeout", type=float, default=120.0)
    _add_transport_args(approval_demo)

    approval_hook = subparsers.add_parser(
        "approval-hook",
        help="handle a Codex PermissionRequest hook via Codex Buddy hardware",
    )
    approval_hook.add_argument("--approval-timeout", type=float, default=120.0)
    _add_transport_args(approval_hook)

    wifi_config = subparsers.add_parser(
        "wifi-config",
        help="send WiFi provisioning settings to the device",
    )
    wifi_config.add_argument("--ssid")
    wifi_config.add_argument("--password")
    wifi_config.add_argument("--password-env")
    wifi_config.add_argument("--host")
    wifi_config.add_argument("--port", type=int)
    wifi_config.add_argument("--token")
    wifi_config.add_argument("--token-env")
    wifi_config.add_argument("--clear", action="store_true")
    wifi_config.add_argument("--no-connect", action="store_true")
    _add_transport_args(wifi_config, default_transport="ble-socket")

    wifi_bridge = subparsers.add_parser(
        "wifi-bridge",
        help="run a long-lived WiFi device bridge for local hook clients",
    )
    wifi_bridge.add_argument("--interval", type=float, default=2.0)
    wifi_bridge.add_argument("--no-heartbeat", action="store_true")
    _add_session_args(wifi_bridge)
    _add_wifi_args(wifi_bridge)
    _add_bridge_args(wifi_bridge)

    doctor = subparsers.add_parser(
        "doctor",
        help="run local helper and transport diagnostics",
    )
    doctor.add_argument("--timeout", type=float, default=8.0)
    doctor.add_argument("--status-file", type=Path, default=DEFAULT_START_STATUS)
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    _add_transport_args(doctor, default_transport="auto")

    logs = subparsers.add_parser(
        "logs",
        help="show the latest start status and background log tail",
    )
    logs.add_argument("--status-file", type=Path, default=DEFAULT_START_STATUS)
    logs.add_argument("--watch-log", type=Path, default=DEFAULT_WATCH_LOG)
    logs.add_argument("--lines", type=int, default=40)
    logs.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    exit_codes = subparsers.add_parser(
        "exit-codes",
        help="show codex-buddy exit code semantics",
    )
    exit_codes.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    launch_agent = subparsers.add_parser(
        "launch-agent",
        help="print or manage an optional macOS LaunchAgent for heartbeat watch",
    )
    launch_agent.add_argument(
        "action",
        choices=["print", "install", "uninstall", "status"],
        help="print plist, install it, uninstall it, or ask launchctl for status",
    )
    launch_agent.add_argument("--label", default=DEFAULT_LAUNCH_AGENT_LABEL)
    launch_agent.add_argument("--plist", type=Path)
    launch_agent.add_argument("--log", type=Path, default=DEFAULT_LAUNCH_AGENT_LOG)
    launch_agent.add_argument("--interval", type=float, default=2.0)
    launch_agent.add_argument("--python", type=Path, default=Path(sys.executable))
    launch_agent.add_argument("--working-directory", type=Path, default=PROJECT_ROOT)
    _add_transport_args(launch_agent, default_transport="auto")

    desktop = subparsers.add_parser(
        "desktop",
        help="print or manage the persistent Codex Desktop approval hook",
    )
    desktop.add_argument(
        "action",
        choices=["print", "install", "uninstall", "status"],
        help="print hook config, install it, uninstall it, or show config status",
    )
    desktop.add_argument("--config", type=Path)
    desktop.add_argument("--codex-bin", default="codex")
    desktop.add_argument("--cwd", type=Path, default=PROJECT_ROOT)
    desktop.add_argument("--python", type=Path, default=Path(sys.executable))
    desktop.add_argument(
        "--hook-binary",
        type=Path,
        help="standalone codex-buddy daemon binary to write into the Desktop hook",
    )
    desktop.add_argument("--hook-timeout", type=int, default=120)
    desktop.add_argument("--probe-timeout", type=float, default=20.0)
    desktop.add_argument("--force", action="store_true")
    desktop.add_argument(
        "--status-message",
        default="Waiting for Codex Buddy hardware approval",
    )
    desktop.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    _add_transport_args(desktop, default_transport="ble-socket")

    start = subparsers.add_parser(
        "start",
        help="start heartbeat watch and launch Codex with the hardware approval hook",
    )
    start.add_argument("--interval", type=float, default=2.0)
    start.add_argument("--codex-bin", default="codex")
    start.add_argument("--cwd", type=Path, default=PROJECT_ROOT)
    start.add_argument("--python", type=Path, default=Path(sys.executable))
    start.add_argument("--hook-runner", type=Path, default=DEFAULT_HOOK_RUNNER)
    start.add_argument("--hook-timeout", type=int, default=120)
    start.add_argument("--probe-timeout", type=float, default=20.0)
    start.add_argument("--approval-policy", default="untrusted")
    start.add_argument("--watch-log", type=Path, default=DEFAULT_WATCH_LOG)
    start.add_argument("--status-file", type=Path, default=DEFAULT_START_STATUS)
    start.add_argument("--watch-log-max-bytes", type=int, default=DEFAULT_WATCH_LOG_MAX_BYTES)
    start.add_argument("--watch-startup-timeout", type=float, default=2.0)
    start.add_argument("--no-heartbeat-watch", action="store_true")
    start.add_argument("--print-command", action="store_true")
    start.add_argument("--alt-screen", action="store_true")
    start.add_argument(
        "--status-message",
        default="Waiting for Codex Buddy hardware approval",
    )
    _add_transport_args(start, default_transport="ble-socket")
    start.add_argument(
        "prompt",
        nargs=argparse.REMAINDER,
        help="optional prompt passed to Codex; prefix with -- if needed",
    )

    pet = subparsers.add_parser("pet", help="show or validate Codex pet metadata")
    pet.add_argument(
        "--pet-dir",
        type=Path,
        help="validate a specific ~/.codex/pets/<pet-id> directory",
    )
    pet.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    subparsers.add_parser("ports", help="list local serial candidates")

    args = parser.parse_args(argv)
    command = args.command or "once"

    try:
        if command == "ports":
            return _ports()
        if command == "pet":
            return _pet(args.codex_home, args.pet_dir, args.json)
        if command == "watch":
            transport = _transport_from_args(args)
            while True:
                try:
                    _send_once(
                        args.codex_home,
                        transport,
                        session_id=args.session_id,
                        session_cwd=args.session_cwd,
                        session_source=args.session_source,
                    )
                except Exception as exc:
                    print(f"codex-buddy watch: {exc}", file=sys.stderr)
                time.sleep(max(0.25, args.interval))
        if command == "soak":
            return _soak(args)
        if command == "once":
            return _send_once(
                args.codex_home,
                _transport_from_args(args),
                session_id=args.session_id,
                session_cwd=args.session_cwd,
                session_source=args.session_source,
            )
        if command == "approval-demo":
            return _approval_demo(args)
        if command == "approval-hook":
            return _approval_hook(args)
        if command == "wifi-config":
            return _wifi_config(args)
        if command == "wifi-bridge":
            return _wifi_bridge(args)
        if command == "doctor":
            return _doctor(args)
        if command == "logs":
            return _logs(args)
        if command == "exit-codes":
            return _exit_codes(args)
        if command == "launch-agent":
            return _launch_agent(args)
        if command == "desktop":
            return _desktop(args)
        if command == "start":
            return _start(args)
    except RuntimeError as exc:
        print(f"codex-buddy: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR

    parser.error(f"unknown command: {command}")
    return EXIT_USAGE


def _add_transport_args(
    parser: argparse.ArgumentParser,
    *,
    default_transport: str = "stdout",
) -> None:
    parser.add_argument(
        "--transport",
        choices=[
            "stdout",
            "serial",
            "ble-app",
            "ble-socket",
            "wifi-server",
            "local-bridge",
            "auto",
        ],
        default=default_transport,
    )
    parser.add_argument("--serial-port", type=Path)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--ble-app", type=Path, default=DEFAULT_BLE_APP)
    parser.add_argument("--ble-port", type=int, default=47391)
    parser.add_argument("--ble-timeout", type=float, default=30.0)
    parser.add_argument("--ble-device-name", default="Codex-Buddy")
    parser.add_argument("--ble-pair-code", default="")
    parser.add_argument(
        "--auto-probe-timeout",
        type=float,
        default=DEFAULT_AUTO_PROBE_TIMEOUT,
        help="seconds to wait for WiFi before falling back to BLE in auto mode",
    )
    _add_wifi_args(parser)
    _add_bridge_args(parser)


def _add_session_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--session-id",
        help="pin heartbeat updates to a specific Codex session id",
    )
    parser.add_argument(
        "--session-cwd",
        type=Path,
        help="only consider Codex session files whose session_meta.cwd matches this path",
    )
    parser.add_argument(
        "--session-source",
        help="only consider Codex session files whose session_meta.source matches this value",
    )


def _add_wifi_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--wifi-host", default="0.0.0.0")
    parser.add_argument("--wifi-port", type=int, default=47392)
    parser.add_argument("--wifi-token", default=os.environ.get("CODEX_BUDDY_WIFI_TOKEN", ""))
    parser.add_argument("--wifi-timeout", type=float, default=30.0)


def _add_bridge_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bridge-host", default="127.0.0.1")
    parser.add_argument("--bridge-port", type=int, default=47393)
    parser.add_argument("--bridge-timeout", type=float, default=120.0)


def _transport_from_args(args: argparse.Namespace) -> Transport:
    if args.transport == "auto":
        return AutoStatusTransport(
            primary=WiFiServerTransport(
                host=args.wifi_host,
                port=args.wifi_port,
                token=args.wifi_token,
                timeout=args.wifi_timeout,
            ),
            fallback=MacOSBleSocketTransport(
                app=args.ble_app,
                port=args.ble_port,
                timeout=args.ble_timeout,
                device_name=_ble_device_name(args),
                pair_code=_ble_pair_code(args),
            ),
            status_timeout=_auto_probe_timeout(args),
        )
    if args.transport == "stdout":
        return StdoutTransport()
    if args.transport == "ble-app":
        return MacOSBleAppTransport(
            app=args.ble_app,
            timeout=args.ble_timeout,
            device_name=_ble_device_name(args),
            pair_code=_ble_pair_code(args),
        )
    if args.transport == "ble-socket":
        return MacOSBleSocketTransport(
            app=args.ble_app,
            port=args.ble_port,
            timeout=args.ble_timeout,
            device_name=_ble_device_name(args),
            pair_code=_ble_pair_code(args),
        )
    if args.transport == "wifi-server":
        return WiFiServerTransport(
            host=args.wifi_host,
            port=args.wifi_port,
            token=args.wifi_token,
            timeout=args.wifi_timeout,
        )
    if args.transport == "local-bridge":
        return LocalBridgeTransport(
            host=args.bridge_host,
            port=args.bridge_port,
            timeout=args.bridge_timeout,
        )
    if not args.serial_port:
        raise SystemExit("--serial-port is required when --transport serial is used")
    return SerialTransport(port=args.serial_port, baud=args.baud)


def _ble_device_name(args: argparse.Namespace) -> str:
    return getattr(args, "ble_device_name", DEFAULT_BLE_DEVICE_NAME)


def _ble_pair_code(args: argparse.Namespace) -> str:
    return getattr(args, "ble_pair_code", "")


def _resolve_auto_transport_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.transport != "auto":
        return args
    try:
        _probe_wifi_transport(args)
    except Exception as exc:
        print(
            "codex-buddy: auto selected ble-socket "
            f"(wifi-server unavailable: {_short_error(exc)})",
            file=sys.stderr,
        )
        fallback_args = _copy_args_with_transport(args, AUTO_FALLBACK_TRANSPORT)
        fallback_args.auto_fallback_from_wifi = True
        return fallback_args
    print("codex-buddy: auto selected wifi-server", file=sys.stderr)
    wifi_args = _copy_args_with_transport(args, AUTO_WIFI_TRANSPORT)
    wifi_args.auto_fallback_from_wifi = False
    return wifi_args


def _copy_args_with_transport(
    args: argparse.Namespace,
    transport: str,
) -> argparse.Namespace:
    copied = argparse.Namespace(**vars(args))
    copied.transport = transport
    return copied


def _probe_wifi_transport(args: argparse.Namespace) -> None:
    timeout = _auto_probe_timeout(args)
    transport = WiFiServerTransport(
        host=args.wifi_host,
        port=args.wifi_port,
        token=args.wifi_token,
        timeout=timeout,
    )
    try:
        heartbeat = Heartbeat(
            state="running",
            animation="running",
            summary="Codex Buddy auto probe",
        )
        transport.send_and_receive(
            heartbeat.to_line(),
            expected_type="device_status",
            timeout=timeout,
        )
    finally:
        transport.close()


def _auto_probe_timeout(args: argparse.Namespace) -> float:
    configured = float(getattr(args, "auto_probe_timeout", DEFAULT_AUTO_PROBE_TIMEOUT))
    wifi_timeout = float(getattr(args, "wifi_timeout", configured))
    return max(0.1, min(configured, wifi_timeout))


def _short_error(exc: Exception) -> str:
    raw = str(exc).strip()
    message = raw.splitlines()[0] if raw else exc.__class__.__name__
    if len(message) > 160:
        return message[:157] + "..."
    return message


def _send_once(
    codex_home: Path,
    transport: Transport,
    *,
    session_id: str | None = None,
    session_cwd: Path | None = None,
    session_source: str | None = None,
) -> int:
    snapshot = snapshot_latest_session(
        codex_home,
        session_id=session_id,
        session_cwd=session_cwd,
        session_source=session_source,
    )
    pet = load_selected_pet(codex_home)
    heartbeat = snapshot.to_heartbeat(pet.to_protocol() if pet else None)
    transport.send(heartbeat.to_line())
    return 0


def _soak(args: argparse.Namespace) -> int:
    count = int(args.count)
    if count <= 0:
        raise SystemExit("--count must be > 0")
    interval = max(0.0, float(args.interval))
    transport = _transport_from_args(args)
    heartbeat = Heartbeat(
        state="running",
        animation="running",
        summary="Codex Buddy soak",
    ).to_line()
    latencies: list[float] = []
    failures: list[str] = []
    rounds: list[dict[str, object]] = []
    try:
        for index in range(1, count + 1):
            started = time.monotonic()
            try:
                response = transport.send_and_receive(
                    heartbeat,
                    expected_type="device_status",
                )
            except Exception as exc:
                elapsed = time.monotonic() - started
                message = _short_error(exc)
                failures.append(message)
                rounds.append(
                    {
                        "index": index,
                        "ok": False,
                        "latency_seconds": elapsed,
                        "error": message,
                    }
                )
                if not args.json:
                    print(f"{index:03d} fail {elapsed:.3f}s {message}", flush=True)
            else:
                elapsed = time.monotonic() - started
                latencies.append(elapsed)
                rounds.append(
                    {
                        "index": index,
                        "ok": True,
                        "latency_seconds": elapsed,
                        "response": response.strip(),
                    }
                )
                if not args.json:
                    print(
                        f"{index:03d} ok {elapsed:.3f}s {response.strip()}",
                        flush=True,
                    )
            if index < count and interval:
                time.sleep(interval)
    finally:
        close = getattr(transport, "close", None)
        if close is not None:
            with suppress(Exception):
                close()

    ok_count = len(latencies)
    fail_count = len(failures)
    if args.json:
        print(
            json.dumps(
                _soak_payload(latencies, ok_count, fail_count, rounds),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        summary = _soak_summary(latencies, ok_count, fail_count)
        print(summary)
    return 0 if fail_count == 0 else 1


def _soak_payload(
    latencies: list[float],
    ok_count: int,
    fail_count: int,
    rounds: list[dict[str, object]],
) -> dict[str, object]:
    summary: dict[str, object] = {
        "ok": fail_count == 0,
        "ok_count": ok_count,
        "fail_count": fail_count,
        "rounds": rounds,
    }
    if latencies:
        summary.update(
            {
                "avg_seconds": sum(latencies) / len(latencies),
                "p95_seconds": _percentile(latencies, 95),
                "max_seconds": max(latencies),
            }
        )
    return summary


def _soak_summary(latencies: list[float], ok_count: int, fail_count: int) -> str:
    if not latencies:
        return f"summary ok={ok_count} fail={fail_count}"
    avg = sum(latencies) / len(latencies)
    p95 = _percentile(latencies, 95)
    max_latency = max(latencies)
    return (
        f"summary ok={ok_count} fail={fail_count} "
        f"avg={avg:.3f}s p95={p95:.3f}s max={max_latency:.3f}s"
    )


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = math.ceil((percentile / 100.0) * len(ordered)) - 1
    return ordered[min(max(rank, 0), len(ordered) - 1)]


def _approval_demo(args: argparse.Namespace) -> int:
    request = ApprovalRequest(args.id, args.tool, args.hint)
    response = _send_approval_request(
        _transport_from_args(args),
        request,
        timeout=getattr(args, "approval_timeout", None),
    )
    if response:
        sys.stdout.write(response)
        if not response.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def _approval_hook(args: argparse.Namespace) -> int:
    transport = _transport_from_args(args)
    raw_input = sys.stdin.read()
    context = hook_context_from_input(raw_input)
    if context.session_id:
        record_active_session(args.codex_home, context.session_id, cwd=context.cwd)

    def send_request(request: ApprovalRequest) -> str:
        return _send_approval_request(
            transport,
            request,
            timeout=args.approval_timeout,
        )

    sys.stdout.write(run_permission_request_hook(raw_input, send_request))
    sys.stdout.flush()
    return 0


def _send_approval_request(
    transport: Transport,
    request: ApprovalRequest,
    *,
    timeout: float | None = None,
) -> str:
    try:
        return transport.send_and_receive(
            request.to_line(),
            expected_type="approval_decision",
            timeout=timeout,
        )
    except TypeError:
        return transport.send_and_receive(
            request.to_line(),
            expected_type="approval_decision",
        )


def _wifi_config(args: argparse.Namespace) -> int:
    password = _secret_arg(args.password, args.password_env, "password")
    token = _secret_arg(args.token, args.token_env, "token")
    if not args.clear and not any(
        value is not None
        for value in (args.ssid, password, args.host, args.port, token)
    ):
        raise SystemExit(
            "wifi-config needs at least one setting, or use --clear"
        )

    request = WifiConfigRequest(
        ssid=args.ssid,
        password=password,
        host=args.host,
        port=args.port,
        token=token,
        clear=args.clear,
        connect=not args.no_connect,
    )
    response = _transport_from_args(args).send_and_receive(
        request.to_line(),
        expected_type="device_status",
    )
    if response:
        sys.stdout.write(response)
        if not response.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def _wifi_bridge(args: argparse.Namespace) -> int:
    server = WifiBridgeServer(
        codex_home=args.codex_home,
        wifi_host=args.wifi_host,
        wifi_port=args.wifi_port,
        wifi_token=args.wifi_token,
        wifi_timeout=args.wifi_timeout,
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
        bridge_timeout=args.bridge_timeout,
        interval=max(0.25, args.interval),
        enable_heartbeat=not args.no_heartbeat,
        session_id=args.session_id,
        session_cwd=args.session_cwd,
        session_source=args.session_source,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.close()
    return 0


def _doctor(args: argparse.Namespace) -> int:
    results: list[dict[str, object]] = []
    if not args.json:
        print("codex-buddy doctor", flush=True)
    timeout = max(0.1, float(args.timeout))
    auto_args = _copy_args_with_timeouts(args, timeout)
    heartbeat = Heartbeat(
        state="running",
        animation="running",
        summary="Codex Buddy doctor",
    ).to_line()

    helper = resolve_ble_app(auto_args.ble_app)
    _record_doctor_result(
        results,
        "ble-helper",
        helper.exists(),
        str(helper),
        emit=not args.json,
    )
    _record_doctor_result(
        results,
        "hook-runner",
        auto_args.hook_runner.exists() and os.access(auto_args.hook_runner, os.X_OK)
        if hasattr(auto_args, "hook_runner")
        else DEFAULT_HOOK_RUNNER.exists() and os.access(DEFAULT_HOOK_RUNNER, os.X_OK),
        str(getattr(auto_args, "hook_runner", DEFAULT_HOOK_RUNNER)),
        emit=not args.json,
    )
    codex_bin = getattr(auto_args, "codex_bin", "codex")
    resolved_codex = shutil.which(codex_bin) if os.sep not in codex_bin else codex_bin
    _record_doctor_result(
        results,
        "codex-bin",
        bool(resolved_codex),
        str(resolved_codex or codex_bin),
        emit=not args.json,
    )

    wifi_ok, wifi_detail = _doctor_transport(
        "wifi-server",
        WiFiServerTransport(
            host=auto_args.wifi_host,
            port=auto_args.wifi_port,
            token=auto_args.wifi_token,
            timeout=timeout,
        ),
        heartbeat,
        timeout=timeout,
    )
    _record_doctor_result(results, "wifi-server", wifi_ok, wifi_detail, emit=not args.json)

    ble_ok, ble_detail = _doctor_transport(
        "ble-socket",
        MacOSBleSocketTransport(
            app=auto_args.ble_app,
            port=auto_args.ble_port,
            timeout=timeout,
            device_name=_ble_device_name(auto_args),
            pair_code=_ble_pair_code(auto_args),
        ),
        heartbeat,
    )
    _record_doctor_result(results, "ble-socket", ble_ok, ble_detail, emit=not args.json)

    auto_ok, auto_detail = _doctor_auto_result(
        wifi_ok,
        wifi_detail,
        ble_ok,
        ble_detail,
    )
    _record_doctor_result(results, "auto", auto_ok, auto_detail, emit=not args.json)

    status_ok, status_detail = _doctor_start_status(auto_args.status_file)
    _record_doctor_result(
        results,
        "start-status",
        status_ok,
        status_detail,
        emit=not args.json,
    )

    summary = "usable" if auto_ok else "unavailable"
    if args.json:
        print(
            json.dumps(
                {
                    "summary": summary,
                    "usable": auto_ok,
                    "checks": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if auto_ok else 1
    if auto_ok:
        print("summary: usable")
        return 0
    print("summary: unavailable")
    return 1


def _copy_args_with_timeouts(args: argparse.Namespace, timeout: float) -> argparse.Namespace:
    copied = argparse.Namespace(**vars(args))
    copied.ble_timeout = timeout
    copied.wifi_timeout = timeout
    copied.auto_probe_timeout = timeout
    return copied


def _doctor_auto_result(
    wifi_ok: bool,
    wifi_detail: str,
    ble_ok: bool,
    ble_detail: str,
) -> tuple[bool, str]:
    if wifi_ok:
        return True, f"wifi-server: {wifi_detail}"
    if ble_ok:
        return True, f"ble-socket fallback: {ble_detail}"
    return False, f"wifi-server: {wifi_detail}; ble-socket: {ble_detail}"


def _doctor_transport(
    name: str,
    transport: Transport,
    line: str,
    *,
    timeout: float | None = None,
) -> tuple[bool, str]:
    try:
        if timeout is None:
            response = transport.send_and_receive(line, expected_type="device_status")
        else:
            try:
                response = transport.send_and_receive(
                    line,
                    expected_type="device_status",
                    timeout=timeout,
                )
            except TypeError:
                response = transport.send_and_receive(line, expected_type="device_status")
        return True, _doctor_response_detail(response)
    except Exception as exc:
        return False, _short_error(exc)
    finally:
        close = getattr(transport, "close", None)
        if close is not None:
            with suppress(Exception):
                close()


def _doctor_response_detail(response: str) -> str:
    text = response.strip()
    if not text:
        return "ok"
    if len(text) > 180:
        return text[:177] + "..."
    return text


def _print_doctor_result(name: str, ok: bool, detail: str) -> None:
    status = "ok" if ok else "fail"
    print(f"{status} {name}: {detail}")


def _record_doctor_result(
    results: list[dict[str, object]],
    name: str,
    ok: bool,
    detail: str,
    *,
    emit: bool,
) -> None:
    results.append({"name": name, "ok": bool(ok), "detail": detail})
    if emit:
        _print_doctor_result(name, ok, detail)


def _doctor_start_status(path: Path) -> tuple[bool, str]:
    path = path.expanduser()
    if not path.exists():
        return True, f"not started yet; status file missing: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"cannot read {path}: {_short_error(exc)}"

    state = str(data.get("state") or "unknown")
    label = str(data.get("label") or "background")
    restart_count = int(data.get("restart_count") or 0)
    pid = data.get("pid")
    last_exit_code = data.get("last_exit_code")
    log_path = str(data.get("log_path") or "")
    updated_at = str(data.get("updated_at") or "")
    detail = (
        f"{label} state={state} restarts={restart_count} pid={pid} "
        f"last_exit={last_exit_code} updated={updated_at} log={log_path}"
    )
    return state != "restart-failed", detail


def _logs(args: argparse.Namespace) -> int:
    status_path = args.status_file.expanduser()
    log_path = args.watch_log.expanduser()
    lines = max(1, int(args.lines))
    status_ok, status_detail = _doctor_start_status(status_path)
    tail = _read_log_tail(log_path, max_lines=lines, max_chars=8000)

    if args.json:
        print(
            json.dumps(
                {
                    "status_file": str(status_path),
                    "status_ok": status_ok,
                    "status_detail": status_detail,
                    "status": _read_start_status_payload(status_path),
                    "log_path": str(log_path),
                    "log_exists": log_path.exists(),
                    "tail": tail.splitlines(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if status_ok else 1

    print("codex-buddy logs")
    print(f"status-file: {status_path}")
    print(f"status: {'ok' if status_ok else 'fail'} {status_detail}")
    print(f"log: {log_path}")
    if tail:
        print()
        print(f"last {lines} log lines:")
        print(tail)
    else:
        print("last log lines: none")
    return 0 if status_ok else 1


def _exit_codes(args: argparse.Namespace) -> int:
    if args.json:
        print(
            json.dumps(
                {
                    "exit_codes": [
                        {"code": code, "name": name, "meaning": meaning}
                        for code, name, meaning in EXIT_CODE_ROWS
                    ]
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK

    print("codex-buddy exit codes")
    for code, name, meaning in EXIT_CODE_ROWS:
        print(f"{code:>3} {name}: {meaning}")
    return EXIT_OK


def _launch_agent(args: argparse.Namespace) -> int:
    plist_path = _launch_agent_path(args)
    if args.action == "print":
        sys.stdout.write(_launch_agent_plist_text(args))
        return EXIT_OK
    if args.action == "install":
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(_launch_agent_plist_text(args), encoding="utf-8")
        _launchctl_bootout(args.label, check=False)
        _launchctl(["bootstrap", _launchctl_domain(), str(plist_path)])
        _launchctl(["enable", _launchctl_service(args.label)])
        print(f"installed {args.label}: {plist_path}")
        return EXIT_OK
    if args.action == "uninstall":
        _launchctl_bootout(args.label, check=False)
        with suppress(FileNotFoundError):
            plist_path.unlink()
        print(f"uninstalled {args.label}: {plist_path}")
        return EXIT_OK
    if args.action == "status":
        return _launch_agent_status(args.label)
    raise SystemExit(f"unsupported launch-agent action: {args.action}")


def _launch_agent_path(args: argparse.Namespace) -> Path:
    if args.plist is not None:
        return args.plist.expanduser()
    return Path.home() / "Library" / "LaunchAgents" / f"{args.label}.plist"


def _launch_agent_plist_text(args: argparse.Namespace) -> str:
    return plistlib.dumps(_launch_agent_payload(args), sort_keys=False).decode("utf-8")


def _launch_agent_payload(args: argparse.Namespace) -> dict[str, object]:
    log_path = args.log.expanduser()
    return {
        "Label": args.label,
        "ProgramArguments": _build_launch_agent_watch_command(args),
        "WorkingDirectory": str(args.working_directory.expanduser()),
        "EnvironmentVariables": {
            "PYTHONPATH": str(PROJECT_ROOT / "daemon" / "src"),
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def _build_launch_agent_watch_command(args: argparse.Namespace) -> list[str]:
    command = [
        str(args.python.expanduser()),
        "-m",
        "codex_buddy.cli",
        "--codex-home",
        str(args.codex_home.expanduser()),
        "watch",
        "--interval",
        str(max(0.25, args.interval)),
        "--transport",
        args.transport,
    ]
    _append_launch_agent_transport_args(command, args)
    return command


def _append_launch_agent_transport_args(
    command: list[str],
    args: argparse.Namespace,
) -> None:
    if args.transport in {"auto", "wifi-server"}:
        command.extend(["--wifi-host", args.wifi_host])
        command.extend(["--wifi-port", str(args.wifi_port)])
        command.extend(["--wifi-timeout", str(args.wifi_timeout)])
        if args.wifi_token:
            command.extend(["--wifi-token", args.wifi_token])
    if args.transport in {"auto", "ble-app", "ble-socket"}:
        command.extend(["--ble-app", str(args.ble_app.expanduser())])
        command.extend(["--ble-timeout", str(args.ble_timeout)])
        command.extend(["--ble-device-name", _ble_device_name(args)])
        if _ble_pair_code(args):
            command.extend(["--ble-pair-code", _ble_pair_code(args)])
    if args.transport in {"auto", "ble-socket"}:
        command.extend(["--ble-port", str(args.ble_port)])
    if args.transport == "auto":
        command.extend(["--auto-probe-timeout", str(args.auto_probe_timeout)])
    if args.transport == "serial":
        if not args.serial_port:
            raise SystemExit("--serial-port is required when --transport serial is used")
        command.extend(["--serial-port", str(args.serial_port.expanduser())])
        command.extend(["--baud", str(args.baud)])


def _launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl_service(label: str) -> str:
    return f"{_launchctl_domain()}/{label}"


def _launchctl_bootout(label: str, *, check: bool) -> subprocess.CompletedProcess[str]:
    return _launchctl(["bootout", _launchctl_service(label)], check=check)


def _launchctl(
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def _launch_agent_status(label: str) -> int:
    result = _launchctl(["print", _launchctl_service(label)], check=False)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


def _desktop(args: argparse.Namespace) -> int:
    config_path = _desktop_config_path(args)
    if args.action == "status":
        status = desktop_config_status(config_path)
        if args.json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
        else:
            print("codex-buddy desktop")
            print(f"config: {status['config_path']}")
            print(f"exists: {'yes' if status['exists'] else 'no'}")
            print(f"managed-hook: {'yes' if status['managed'] else 'no'}")
            print(
                "unmanaged-permission-hook: "
                f"{'yes' if status['unmanaged_permission_hook'] else 'no'}"
            )
        return EXIT_OK

    if args.action == "uninstall":
        changed, backup_path = uninstall_managed_config_block(config_path)
        if args.json:
            print(
                json.dumps(
                    {
                        "changed": changed,
                        "config_path": str(config_path.expanduser()),
                        "backup_path": str(backup_path) if backup_path else None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif changed:
            print(f"uninstalled Codex Buddy desktop hook: {config_path.expanduser()}")
            print(f"backup: {backup_path}")
        else:
            print(f"Codex Buddy desktop hook not installed: {config_path.expanduser()}")
        return EXIT_OK

    try:
        block, hook_info = _build_desktop_managed_block(args)
    except (AppServerError, DesktopConfigError, OSError) as exc:
        print(f"codex-buddy desktop: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if args.action == "print":
        if args.json:
            print(
                json.dumps(
                    {
                        "config_path": str(config_path.expanduser()),
                        "hook_key": hook_info["key"],
                        "current_hash": hook_info["currentHash"],
                        "block": block,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            sys.stdout.write(block)
        return EXIT_OK

    if args.action == "install":
        try:
            backup_path = install_managed_config_block(
                config_path,
                block,
                force=args.force,
            )
        except DesktopConfigError as exc:
            print(f"codex-buddy desktop: {exc}", file=sys.stderr)
            return EXIT_CONFIG
        if args.json:
            print(
                json.dumps(
                    {
                        "installed": True,
                        "config_path": str(config_path.expanduser()),
                        "backup_path": str(backup_path),
                        "hook_key": hook_info["key"],
                        "current_hash": hook_info["currentHash"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"installed Codex Buddy desktop hook: {config_path.expanduser()}")
            print(f"backup: {backup_path}")
            if args.transport == "local-bridge":
                print(
                    "note: local-bridge needs a running `codex-buddy wifi-bridge` "
                    "process before Codex Desktop sends an approval hook."
                )
        return EXIT_OK

    raise SystemExit(f"unsupported desktop action: {args.action}")


def _desktop_config_path(args: argparse.Namespace) -> Path:
    if args.config is not None:
        return args.config.expanduser()
    return args.codex_home.expanduser() / "config.toml"


def _build_desktop_managed_block(args: argparse.Namespace) -> tuple[str, dict[str, str]]:
    if args.transport in {"auto", "wifi-server"}:
        raise DesktopConfigError(
            "desktop hook cannot use auto or wifi-server directly; use ble-socket "
            "or local-bridge with a long-lived wifi-bridge"
        )
    options = DesktopHookOptions(
        codex_bin=args.codex_bin,
        cwd=args.cwd.expanduser().resolve(),
        python=args.python.expanduser(),
        daemon_src=PROJECT_ROOT / "daemon" / "src",
        transport=args.transport,
        hook_binary=args.hook_binary.expanduser() if args.hook_binary else None,
        hook_timeout=args.hook_timeout,
        status_message=args.status_message,
        serial_port=args.serial_port.expanduser() if args.serial_port else None,
        baud=args.baud,
        ble_app=args.ble_app.expanduser() if args.ble_app else None,
        ble_port=args.ble_port,
        ble_timeout=args.ble_timeout,
        ble_device_name=_ble_device_name(args),
        ble_pair_code=_ble_pair_code(args),
        bridge_host=args.bridge_host,
        bridge_port=args.bridge_port,
        bridge_timeout=args.bridge_timeout,
    )
    hook_command = build_desktop_hook_command(options)
    bare_config = build_inline_hooks_config(
        hook_command=hook_command,
        timeout_sec=args.hook_timeout,
        status_message=args.status_message,
    )
    hook_info = probe_hook_info(
        codex_bin=args.codex_bin,
        cwd=options.cwd,
        hooks_config=bare_config,
        hook_command=hook_command,
        timeout_sec=args.probe_timeout,
    )
    block = build_desktop_config_block(
        hook_command=hook_command,
        timeout_sec=args.hook_timeout,
        status_message=args.status_message,
        trusted_key=hook_info["key"],
        trusted_hash=hook_info["currentHash"],
    )
    return block, hook_info


def _read_start_status_payload(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _secret_arg(value: str | None, env_name: str | None, label: str) -> str | None:
    if value is not None and env_name:
        raise SystemExit(f"use either --{label} or --{label}-env, not both")
    if env_name:
        if env_name not in os.environ:
            raise SystemExit(f"environment variable not set: {env_name}")
        return os.environ[env_name]
    return value


def _start(args: argparse.Namespace) -> int:
    args = _resolve_auto_transport_args(args)
    prompt = list(args.prompt)
    if prompt and prompt[0] == "--":
        prompt = prompt[1:]

    background_command = _build_start_background_command(args)
    background_label = "bridge" if args.transport == "wifi-server" else "watch"
    codex_command = _build_codex_hook_command(args, prompt)

    if args.print_command:
        if background_command:
            print(f"{background_label}:", " ".join(_quote_args(background_command)))
        print("codex:", " ".join(_quote_args(codex_command)))
        return 0

    try:
        _validate_start_args(args)
    except LauncherError as exc:
        print(f"codex-buddy start: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    background_service: _BackgroundService | None = None
    watch_log = args.watch_log.expanduser()
    try:
        if background_command:
            background_service = _BackgroundService(
                command=background_command,
                label=background_label,
                log_path=watch_log,
                status_path=args.status_file.expanduser(),
                max_log_bytes=args.watch_log_max_bytes,
                startup_timeout=args.watch_startup_timeout,
            )
            print(f"codex-buddy: {background_label} log: {watch_log}", file=sys.stderr)
            background_service.start()
            print(f"codex-buddy: {background_label} started", file=sys.stderr)
        print("codex-buddy: launching Codex with hardware approval hook", file=sys.stderr)
        return subprocess.run(codex_command, check=False).returncode
    except KeyboardInterrupt:
        print(f"\ncodex-buddy: interrupted, cleaning up {background_label}", file=sys.stderr)
        return EXIT_INTERRUPTED
    except LauncherError as exc:
        print(f"codex-buddy start: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except OSError as exc:
        print(f"codex-buddy start: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    finally:
        if background_service is not None:
            stop_status = background_service.stop()
            print(
                f"codex-buddy: {background_label} stopped ({stop_status}); "
                f"restarts={background_service.restart_count}; log={watch_log}",
                file=sys.stderr,
            )


def _build_start_background_command(args: argparse.Namespace) -> list[str]:
    if args.transport == "wifi-server":
        command = [
            str(args.python),
            "-m",
            "codex_buddy.cli",
            "--codex-home",
            str(args.codex_home),
            "wifi-bridge",
            "--interval",
            str(max(0.25, args.interval)),
            "--session-cwd",
            str(args.cwd.expanduser()),
            "--wifi-host",
            args.wifi_host,
            "--wifi-port",
            str(args.wifi_port),
            "--wifi-timeout",
            str(args.wifi_timeout),
            "--bridge-host",
            args.bridge_host,
            "--bridge-port",
            str(args.bridge_port),
            "--bridge-timeout",
            str(args.bridge_timeout),
        ]
        if args.wifi_token:
            command.extend(["--wifi-token", args.wifi_token])
        if args.no_heartbeat_watch:
            command.append("--no-heartbeat")
        return command
    if getattr(args, "auto_fallback_from_wifi", False):
        return _build_watch_command(_copy_args_with_transport(args, "auto"))
    return _build_watch_command(args)


def _build_watch_command(args: argparse.Namespace) -> list[str]:
    if args.no_heartbeat_watch:
        return []
    command = [
        str(args.python),
        "-m",
        "codex_buddy.cli",
        "--codex-home",
        str(args.codex_home),
        "watch",
        "--interval",
        str(max(0.25, args.interval)),
        "--session-cwd",
        str(args.cwd.expanduser()),
        "--transport",
        args.transport,
    ]
    _append_transport_args(command, args)
    return command


def _build_codex_hook_command(args: argparse.Namespace, prompt: list[str]) -> list[str]:
    hook_transport = "local-bridge" if args.transport == "wifi-server" else args.transport
    command = [
        str(args.hook_runner),
        "--codex-bin",
        args.codex_bin,
        "--cwd",
        str(args.cwd),
        "--python",
        str(args.python),
        "--transport",
        hook_transport,
        "--hook-timeout",
        str(args.hook_timeout),
        "--probe-timeout",
        str(args.probe_timeout),
        "--approval-policy",
        args.approval_policy,
        "--status-message",
        args.status_message,
    ]
    if args.alt_screen:
        command.append("--alt-screen")
    _append_transport_args(command, args, transport=hook_transport)
    command.extend(prompt)
    return command


def _append_transport_args(
    command: list[str],
    args: argparse.Namespace,
    *,
    transport: str | None = None,
) -> None:
    selected_transport = transport or args.transport
    if selected_transport in {"ble-app", "ble-socket"}:
        command.extend(["--ble-app", str(args.ble_app)])
        command.extend(["--ble-timeout", str(args.ble_timeout)])
        command.extend(["--ble-device-name", _ble_device_name(args)])
        if _ble_pair_code(args):
            command.extend(["--ble-pair-code", _ble_pair_code(args)])
    if selected_transport == "ble-socket":
        command.extend(["--ble-port", str(args.ble_port)])
    if selected_transport == "auto":
        command.extend(["--wifi-host", args.wifi_host])
        command.extend(["--wifi-port", str(args.wifi_port)])
        if args.wifi_token:
            command.extend(["--wifi-token", args.wifi_token])
        command.extend(["--wifi-timeout", str(args.wifi_timeout)])
        command.extend(["--ble-app", str(args.ble_app)])
        command.extend(["--ble-timeout", str(args.ble_timeout)])
        command.extend(["--ble-port", str(args.ble_port)])
        command.extend(["--ble-device-name", _ble_device_name(args)])
        if _ble_pair_code(args):
            command.extend(["--ble-pair-code", _ble_pair_code(args)])
        command.extend(["--auto-probe-timeout", str(args.auto_probe_timeout)])
    if selected_transport == "serial":
        if not args.serial_port:
            raise SystemExit("--serial-port is required when --transport serial is used")
        command.extend(["--serial-port", str(args.serial_port)])
        command.extend(["--baud", str(args.baud)])
    if selected_transport == "wifi-server":
        command.extend(["--wifi-host", args.wifi_host])
        command.extend(["--wifi-port", str(args.wifi_port)])
        if args.wifi_token:
            command.extend(["--wifi-token", args.wifi_token])
        command.extend(["--wifi-timeout", str(args.wifi_timeout)])
    if selected_transport == "local-bridge":
        bridge_timeout = max(
            float(args.bridge_timeout),
            float(getattr(args, "hook_timeout", args.bridge_timeout)),
        )
        command.extend(["--bridge-host", args.bridge_host])
        command.extend(["--bridge-port", str(args.bridge_port)])
        command.extend(["--bridge-timeout", str(bridge_timeout)])


def _quote_args(args: list[str]) -> list[str]:
    return [shlex.quote(arg) for arg in args]


def _validate_start_args(args: argparse.Namespace) -> None:
    if args.watch_log_max_bytes < 0:
        raise LauncherError("--watch-log-max-bytes must be >= 0")
    if args.watch_startup_timeout < 0:
        raise LauncherError("--watch-startup-timeout must be >= 0")
    if not args.cwd.exists():
        raise LauncherError(f"working directory not found: {args.cwd}")
    _resolve_executable(args.python, "python")
    _resolve_executable(args.codex_bin, "codex binary")
    if not args.hook_runner.exists():
        raise LauncherError(f"hook runner not found: {args.hook_runner}")
    if not os.access(args.hook_runner, os.X_OK):
        raise LauncherError(f"hook runner is not executable: {args.hook_runner}")
    if args.transport == "serial" and not args.serial_port:
        raise LauncherError("--serial-port is required when --transport serial is used")
    if args.transport in {"ble-app", "ble-socket"}:
        ble_app = resolve_ble_app(args.ble_app)
        if not ble_app.exists():
            raise LauncherError(
                f"BLE helper app not found: {ble_app}. "
                "Run tools/build_ble_bridge_app.sh first."
            )


def _resolve_executable(value: str | Path, label: str) -> str:
    text = str(value)
    if not text:
        raise LauncherError(f"{label} is empty")
    path_like = os.sep in text or (os.altsep is not None and os.altsep in text)
    if path_like or Path(text).is_absolute():
        path = Path(text).expanduser()
        if not path.exists():
            raise LauncherError(f"{label} not found: {path}")
        if not os.access(path, os.X_OK):
            raise LauncherError(f"{label} is not executable: {path}")
        return str(path)
    resolved = shutil.which(text)
    if not resolved:
        raise LauncherError(f"{label} not found on PATH: {text}")
    return resolved


class _BackgroundService:
    def __init__(
        self,
        *,
        command: list[str],
        label: str,
        log_path: Path,
        max_log_bytes: int,
        startup_timeout: float,
        status_path: Path | None = None,
        restart_delay: float = DEFAULT_BACKGROUND_RESTART_DELAY,
        monitor_interval: float = DEFAULT_BACKGROUND_MONITOR_INTERVAL,
    ) -> None:
        self.command = command
        self.label = label
        self.log_path = log_path
        self.status_path = status_path
        self.max_log_bytes = max_log_bytes
        self.startup_timeout = startup_timeout
        self.restart_delay = max(0.05, restart_delay)
        self.monitor_interval = max(0.05, monitor_interval)
        self._log_handle: TextIO | None = None
        self._proc: subprocess.Popen[str] | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.restart_count = 0
        self.start_count = 0
        self.last_exit_code: int | None = None

    def start(self) -> None:
        self._log_handle = _open_watch_log(self.log_path, self.max_log_bytes)
        self._start_process("start")
        assert self._proc is not None
        _check_watch_startup(
            self._proc,
            self.startup_timeout,
            self.log_path,
            label=self.label,
        )
        self._thread = threading.Thread(
            target=self._monitor,
            name=f"codex-buddy-{self.label}-supervisor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> str:
        self._stop_event.set()
        stop_status = _stop_watch_process(self._proc)
        if self._proc is not None:
            self.last_exit_code = self._proc.returncode
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.startup_timeout + 0.5))
        if self._log_handle is not None:
            _write_background_log_event(
                self._log_handle,
                self.label,
                f"stop ({stop_status})",
            )
            self._log_handle.close()
            self._log_handle = None
        self._write_status("stop", "stopped")
        return stop_status

    def _monitor(self) -> None:
        while not self._stop_event.wait(self.monitor_interval):
            proc = self._proc
            if proc is None or proc.poll() is None:
                continue
            returncode = proc.returncode
            self.last_exit_code = returncode
            self.restart_count += 1
            self._write_event(f"exited ({returncode}); restarting")
            self._write_status("exited", "restarting")
            print(
                f"codex-buddy: {self.label} exited with code {returncode}; restarting",
                file=sys.stderr,
            )
            if self._stop_event.wait(self.restart_delay):
                return
            try:
                self._start_process("restart")
                assert self._proc is not None
                _check_watch_startup(
                    self._proc,
                    self.startup_timeout,
                    self.log_path,
                    label=self.label,
                )
                self._write_status("restart", "running")
                print(f"codex-buddy: {self.label} restarted", file=sys.stderr)
            except Exception as exc:
                self._write_event(f"restart failed: {_short_error(exc)}")
                self._write_status("restart failed", "restart-failed")
                print(
                    f"codex-buddy: {self.label} restart failed: {_short_error(exc)}",
                    file=sys.stderr,
                )

    def _start_process(self, event: str) -> None:
        if self._log_handle is None:
            raise LauncherError(f"{self.label} log is not open")
        _write_background_log_event(
            self._log_handle,
            self.label,
            event,
            self.command,
        )
        self.start_count += 1
        self._proc = subprocess.Popen(
            self.command,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=_watch_env(),
        )
        self._write_status(event, "running")

    def _write_event(self, event: str) -> None:
        if self._log_handle is not None:
            _write_background_log_event(self._log_handle, self.label, event)

    def _write_status(self, event: str, state: str) -> None:
        if self.status_path is None:
            return
        proc = self._proc
        payload = {
            "label": self.label,
            "state": state,
            "event": event,
            "pid": proc.pid if proc is not None and proc.poll() is None else None,
            "start_count": self.start_count,
            "restart_count": self.restart_count,
            "last_exit_code": self.last_exit_code,
            "log_path": str(self.log_path),
            "updated_at": _timestamp(),
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.status_path.with_suffix(f"{self.status_path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.status_path)


def _open_watch_log(path: Path, max_bytes: int) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_log_if_needed(path, max_bytes)
    return path.open("a", encoding="utf-8")


def _rotate_log_if_needed(path: Path, max_bytes: int) -> None:
    if max_bytes <= 0 or not path.exists():
        return
    if path.stat().st_size <= max_bytes:
        return
    backup = path.with_name(f"{path.name}.1")
    backup.unlink(missing_ok=True)
    path.replace(backup)


def _write_watch_log_event(
    log_handle: TextIO,
    event: str,
    command: list[str] | None = None,
) -> None:
    _write_background_log_event(log_handle, "watch", event, command)


def _write_background_log_event(
    log_handle: TextIO,
    label: str,
    event: str,
    command: list[str] | None = None,
) -> None:
    log_handle.write(f"\n--- codex-buddy {label} {event} {_timestamp()} ---\n")
    if command:
        log_handle.write(f"command: {shlex.join(command)}\n")
    log_handle.flush()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %z")


def _watch_env() -> dict[str, str]:
    env = os.environ.copy()
    daemon_src = PROJECT_ROOT / "daemon" / "src"
    if daemon_src.exists():
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{daemon_src}{os.pathsep}{existing}" if existing else str(daemon_src)
        )
    return env


def _check_watch_startup(
    proc: subprocess.Popen[str],
    timeout: float,
    log_path: Path,
    *,
    label: str = "heartbeat watch",
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        returncode = proc.poll()
        if returncode is not None:
            raise LauncherError(_watch_exit_message(returncode, log_path, label))
        time.sleep(0.05)
    returncode = proc.poll()
    if returncode is not None:
        raise LauncherError(_watch_exit_message(returncode, log_path, label))


def _watch_exit_message(
    returncode: int,
    log_path: Path,
    label: str = "heartbeat watch",
) -> str:
    tail = _read_log_tail(log_path)
    message = (
        f"{label} exited during startup with code {returncode}; "
        f"see {log_path}"
    )
    if tail:
        message += f"\nlast watch log lines:\n{tail}"
    return message


def _read_log_tail(path: Path, max_lines: int = 20, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-max_lines:])
    if len(tail) > max_chars:
        return tail[-max_chars:]
    return tail


def _stop_watch_process(proc: subprocess.Popen[str] | None) -> str:
    if proc is None:
        return "not-started"
    if proc.poll() is not None:
        return f"already-exited:{proc.returncode}"
    proc.terminate()
    with suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=3)
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=3)
        return "killed"
    return "terminated"


def _pet(codex_home: Path, pet_dir: Path | None = None, emit_json: bool = False) -> int:
    pet = load_pet_dir(pet_dir.expanduser()) if pet_dir is not None else load_selected_pet(codex_home)
    if pet is None:
        if emit_json:
            print(
                json.dumps(
                    {
                        "valid": False,
                        "problems": ["No custom Codex pet selected."],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        print("No custom Codex pet selected.")
        return 1

    problems = validate_pet_asset(pet)
    if emit_json:
        print(
            json.dumps(
                {
                    "id": pet.pet_id,
                    "displayName": pet.display_name,
                    "spritesheet": str(pet.spritesheet),
                    "size": list(pet.size) if pet.size else None,
                    "valid": not problems,
                    "problems": problems,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if not problems else 1

    print(f"id: {pet.pet_id}")
    print(f"displayName: {pet.display_name}")
    print(f"spritesheet: {pet.spritesheet}")
    if pet.size:
        print(f"size: {pet.size[0]}x{pet.size[1]}")
    if problems:
        print("problems:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("valid: yes")
    return 0


def _ports() -> int:
    for path in sorted(Path("/dev").glob("cu.*")):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
