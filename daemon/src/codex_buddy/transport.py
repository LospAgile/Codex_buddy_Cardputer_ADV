from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import socket
import subprocess
import sys
import time


DEVICE_STATUS_RESPONSE_TIMEOUT = 1.5
MAX_TRANSPORT_LINE_BYTES = 32 * 1024
MAX_IGNORED_RESPONSE_LINES = 64
WIFI_RETRY_BACKOFF_SECONDS = 0.05


DEFAULT_BLE_BRIDGE_APP = Path("tools/CodexBuddyBridge.app")
LEGACY_BLE_SMOKE_APP = Path("tools/CodexBuddyBLESmoke.app")
DEFAULT_BLE_BRIDGE_LOG = Path("/tmp/codex-buddy-ble-bridge.log")
LEGACY_BLE_SMOKE_LOG = Path("/tmp/codex-buddy-ble-smoke.log")
DEFAULT_BLE_DEVICE_NAME = "Codex-Buddy"


class TransportFatalError(RuntimeError):
    pass


def resolve_ble_app(app: Path) -> Path:
    if app.exists():
        return app
    if app.name == DEFAULT_BLE_BRIDGE_APP.name:
        legacy_next_to_app = app.parent / LEGACY_BLE_SMOKE_APP.name
        if legacy_next_to_app.exists():
            return legacy_next_to_app
        if LEGACY_BLE_SMOKE_APP.exists():
            return LEGACY_BLE_SMOKE_APP
    return app


class Transport:
    def send(self, line: str) -> None:
        raise NotImplementedError

    def send_and_receive(self, line: str, expected_type: str = "device_status") -> str:
        self.send(line)
        return ""


class StdoutTransport(Transport):
    def send(self, line: str) -> None:
        sys.stdout.write(line)
        sys.stdout.flush()


@dataclass
class AutoStatusTransport(Transport):
    primary: Transport
    fallback: Transport
    primary_name: str = "wifi-server"
    fallback_name: str = "ble-socket"
    status_timeout: float | None = None

    def send(self, line: str) -> None:
        response = self.send_and_receive(line, expected_type="device_status")
        sys.stdout.write(response)
        if not response.endswith("\n"):
            sys.stdout.write("\n")

    def send_and_receive(self, line: str, expected_type: str = "device_status") -> str:
        try:
            return self._primary_send_and_receive(line, expected_type)
        except Exception as exc:
            self._close_primary()
            if expected_type != "device_status":
                raise
            print(
                f"codex-buddy: auto selected {self.fallback_name} "
                f"({self.primary_name} unavailable: {self._short_error(exc)})",
                file=sys.stderr,
            )
            return self.fallback.send_and_receive(line, expected_type=expected_type)

    def _primary_send_and_receive(self, line: str, expected_type: str) -> str:
        if expected_type != "device_status" or self.status_timeout is None:
            return self.primary.send_and_receive(line, expected_type=expected_type)
        try:
            return self.primary.send_and_receive(
                line,
                expected_type=expected_type,
                timeout=self.status_timeout,
            )
        except TypeError:
            return self.primary.send_and_receive(line, expected_type=expected_type)

    def _close_primary(self) -> None:
        close = getattr(self.primary, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass

    def _short_error(self, exc: Exception) -> str:
        raw = str(exc).strip()
        message = raw.splitlines()[0] if raw else exc.__class__.__name__
        if len(message) > 160:
            return message[:157] + "..."
        return message


@dataclass
class SerialTransport(Transport):
    port: Path
    baud: int = 115200

    def __post_init__(self) -> None:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "serial transport requires pyserial in the active Python environment"
            ) from exc
        self._serial = serial.Serial(str(self.port), self.baud, timeout=1)

    def send(self, line: str) -> None:
        self._serial.write(line.encode("utf-8"))
        self._serial.flush()


@dataclass
class MacOSBleAppTransport(Transport):
    app: Path = DEFAULT_BLE_BRIDGE_APP
    log_path: Path = DEFAULT_BLE_BRIDGE_LOG
    timeout: float = 30.0
    device_name: str = DEFAULT_BLE_DEVICE_NAME
    pair_code: str = ""

    def send(self, line: str) -> None:
        log = self.send_and_receive(line, expected_type="device_status")
        if log:
            sys.stdout.write(log)
            if not log.endswith("\n"):
                sys.stdout.write("\n")

    def send_and_receive(
        self,
        line: str,
        expected_type: str = "device_status",
        timeout: float | None = None,
    ) -> str:
        effective_timeout = timeout if timeout is not None else self.timeout
        app = resolve_ble_app(self.app)
        if not app.exists():
            raise RuntimeError(
                f"BLE helper app not found: {app}. "
                "Run tools/build_ble_bridge_app.sh first."
            )

        self.log_path.unlink(missing_ok=True)
        LEGACY_BLE_SMOKE_LOG.unlink(missing_ok=True)
        result = subprocess.run(
            [
                "/usr/bin/open",
                "-W",
                str(app),
                "--args",
                "--line",
                line.rstrip("\n"),
                "--request-timeout",
                str(effective_timeout),
                "--device-name",
                self.device_name,
                "--pair-code",
                self.pair_code,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
        log = self._read_log()
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "BLE helper failed")
        if expected_type and f'"type":"{expected_type}"' not in log:
            raise RuntimeError(f"BLE helper did not receive {expected_type}")
        return log

    def _read_log(self) -> str:
        if self.log_path.exists():
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        if LEGACY_BLE_SMOKE_LOG.exists():
            return LEGACY_BLE_SMOKE_LOG.read_text(encoding="utf-8", errors="replace")
        return ""


@dataclass
class MacOSBleSocketTransport(Transport):
    app: Path = DEFAULT_BLE_BRIDGE_APP
    host: str = "127.0.0.1"
    port: int = 47391
    timeout: float = 30.0
    device_name: str = DEFAULT_BLE_DEVICE_NAME
    pair_code: str = ""

    def send(self, line: str) -> None:
        response = self.send_and_receive(line, expected_type="device_status")
        sys.stdout.write(response)
        if not response.endswith("\n"):
            sys.stdout.write("\n")

    def send_and_receive(
        self,
        line: str,
        expected_type: str = "device_status",
        timeout: float | None = None,
    ) -> str:
        effective_timeout = timeout if timeout is not None else self.timeout
        self._ensure_server()
        try:
            self._pair_if_needed(effective_timeout)
            response = self._send_once(line, effective_timeout)
        except (OSError, RuntimeError, TimeoutError) as exc:
            if not self._should_restart_after(exc):
                raise
            self._restart_server()
            self._pair_if_needed(effective_timeout)
            response = self._send_once(line, effective_timeout)
        if '"type":"error"' in response:
            raise RuntimeError(f"BLE socket helper returned error: {response.strip()}")
        if expected_type and f'"type":"{expected_type}"' not in response:
            raise RuntimeError(f"BLE socket helper did not receive {expected_type}")
        return response

    def _send_once(self, line: str, timeout: float) -> str:
        with socket.create_connection(
            (self.host, self.port),
            timeout=timeout,
        ) as conn:
            conn.sendall(self._line_with_request_timeout(line, timeout).encode("utf-8"))
            return self._readline(conn, timeout=timeout)

    def _pair_if_needed(self, timeout: float) -> None:
        pair_code = self.pair_code.strip()
        if not pair_code:
            return
        response = self._send_once(
            json.dumps(
                {
                    "v": 0,
                    "type": "pair_request",
                    "code": pair_code,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n",
            timeout,
        )
        if '"type":"error"' in response:
            raise RuntimeError(f"BLE socket helper returned error: {response.strip()}")
        try:
            payload = json.loads(response)
        except json.JSONDecodeError as exc:
            raise RuntimeError("BLE socket helper returned invalid pair response") from exc
        if payload.get("type") != "device_status" or payload.get("status") != "pair_ok":
            raise RuntimeError(f"BLE pairing failed: {response.strip()}")

    def _ensure_server(self) -> None:
        if self._is_listening():
            return
        app = resolve_ble_app(self.app)
        if not app.exists():
            raise RuntimeError(
                f"BLE helper app not found: {app}. "
                "Run tools/build_ble_bridge_app.sh first."
            )

        subprocess.run(
            [
                "/usr/bin/open",
                "-g",
                str(app),
                "--args",
                "--server",
                "--port",
                str(self.port),
                "--request-timeout",
                str(self.timeout),
                "--device-name",
                self.device_name,
                "--pair-code",
                self.pair_code,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self._is_listening():
                return
            time.sleep(0.2)
        raise RuntimeError("BLE socket helper did not start listening")

    def _restart_server(self) -> None:
        self._stop_server()
        deadline = time.monotonic() + min(3.0, self.timeout)
        while time.monotonic() < deadline and self._is_listening():
            time.sleep(0.1)
        self._ensure_server()

    def _stop_server(self) -> None:
        subprocess.run(
            ["/usr/bin/pkill", "-x", "codex_buddy_ble_bridge"],
            check=False,
            capture_output=True,
            text=True,
        )

    def _should_restart_after(self, exc: BaseException) -> bool:
        message = str(exc).lower()
        return (
            isinstance(exc, (OSError, TimeoutError))
            or "timed out" in message
            or "ble disconnected" in message
            or "did not receive device_status" in message
        )

    def _is_listening(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=0.2):
                return True
        except OSError:
            return False

    def _line_with_request_timeout(self, line: str, timeout: float) -> str:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return line
        if not isinstance(payload, dict):
            return line
        payload["timeout"] = max(1.0, float(timeout))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"

    def _readline(self, conn: socket.socket, *, timeout: float | None = None) -> str:
        conn.settimeout(timeout if timeout is not None else self.timeout)
        chunks: list[bytes] = []
        while True:
            chunk = conn.recv(1)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk == b"\n":
                break
        return b"".join(chunks).decode("utf-8", errors="replace")


@dataclass
class WiFiServerTransport(Transport):
    host: str = "0.0.0.0"
    port: int = 47392
    token: str = ""
    timeout: float = 30.0
    _listener: socket.socket | None = field(default=None, init=False, repr=False)
    _conn: socket.socket | None = field(default=None, init=False, repr=False)

    def send(self, line: str) -> None:
        response = self.send_and_receive(line, expected_type="device_status")
        sys.stdout.write(response)
        if not response.endswith("\n"):
            sys.stdout.write("\n")

    def send_and_receive(
        self,
        line: str,
        expected_type: str = "device_status",
        timeout: float | None = None,
    ) -> str:
        effective_timeout = timeout if timeout is not None else self.timeout
        deadline = time.monotonic() + max(0.01, effective_timeout)
        last_error: BaseException | None = None
        line_sent = False

        while True:
            remaining = max(0.01, deadline - time.monotonic())
            response_timeout = remaining
            if expected_type == "device_status":
                response_timeout = min(remaining, DEVICE_STATUS_RESPONSE_TIMEOUT)
            try:
                conn = self._connection(timeout=remaining)
                conn.settimeout(response_timeout)
                if not line_sent:
                    conn.sendall(line.encode("utf-8"))
                    line_sent = True
                return self._read_expected(conn, expected_type)
            except TransportFatalError:
                raise
            except TimeoutError as exc:
                last_error = exc
                if time.monotonic() >= deadline:
                    self._drop_connection()
                    target = expected_type or "response"
                    raise RuntimeError(
                        f"WiFi device did not return {target} within "
                        f"{effective_timeout:g}s"
                    ) from last_error
                time.sleep(
                    min(
                        WIFI_RETRY_BACKOFF_SECONDS,
                        max(0.0, deadline - time.monotonic()),
                    )
                )
            except (OSError, RuntimeError) as exc:
                last_error = exc
                self._drop_connection()
                line_sent = False
                if time.monotonic() >= deadline:
                    target = expected_type or "response"
                    raise RuntimeError(
                        f"WiFi device did not return {target} within "
                        f"{effective_timeout:g}s"
                    ) from last_error
                time.sleep(
                    min(
                        WIFI_RETRY_BACKOFF_SECONDS,
                        max(0.0, deadline - time.monotonic()),
                    )
                )

    def _connection(self, *, timeout: float | None = None) -> socket.socket:
        if self._conn is not None:
            return self._conn
        self._ensure_listener()
        assert self._listener is not None
        self._listener.settimeout(timeout if timeout is not None else self.timeout)
        conn, _ = self._listener.accept()
        conn.settimeout(timeout if timeout is not None else self.timeout)
        if self.token:
            self._validate_token(conn)
        self._conn = conn
        return conn

    def _ensure_listener(self) -> None:
        if self._listener is not None:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.host, self.port))
        except OSError as exc:
            listener.close()
            raise TransportFatalError(
                f"WiFi server could not listen on {self.host}:{self.port}; "
                "another codex-buddy process may already be using this port. "
                "Run `codex-buddy logs` or change --wifi-port."
            ) from exc
        listener.listen(1)
        self._listener = listener

    def _validate_token(self, conn: socket.socket) -> None:
        line = self._readline(conn)
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            conn.close()
            raise RuntimeError("WiFi device sent invalid hello JSON") from exc
        if payload.get("type") != "hello" or payload.get("token") != self.token:
            conn.close()
            raise TransportFatalError(
                "WiFi device token mismatch; set the same token on the device "
                "WiFi page and daemon --wifi-token / CODEX_BUDDY_WIFI_TOKEN."
            )

    def _drop_connection(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def close(self) -> None:
        self._drop_connection()
        if self._listener is not None:
            try:
                self._listener.close()
            finally:
                self._listener = None

    def _readline(self, conn: socket.socket) -> str:
        chunks = bytearray()
        while True:
            chunk = conn.recv(1)
            if not chunk:
                raise RuntimeError("WiFi device closed the connection")
            chunks.extend(chunk)
            if len(chunks) > MAX_TRANSPORT_LINE_BYTES:
                raise RuntimeError("WiFi device response line is too large")
            if chunk == b"\n":
                break
        return bytes(chunks).decode("utf-8", errors="replace")

    def _read_expected(self, conn: socket.socket, expected_type: str) -> str:
        ignored = 0
        while True:
            response = self._readline(conn)
            if not expected_type:
                return response
            try:
                payload = json.loads(response)
            except json.JSONDecodeError:
                ignored += 1
                if ignored > MAX_IGNORED_RESPONSE_LINES:
                    raise RuntimeError("WiFi device sent too many non-JSON responses")
                continue
            if payload.get("type") == expected_type:
                return response
            ignored += 1
            if ignored > MAX_IGNORED_RESPONSE_LINES:
                raise RuntimeError(
                    f"WiFi device did not send expected {expected_type} response"
                )


@dataclass
class LocalBridgeTransport(Transport):
    host: str = "127.0.0.1"
    port: int = 47393
    timeout: float = 120.0

    def send(self, line: str) -> None:
        response = self.send_and_receive(line, expected_type="device_status")
        sys.stdout.write(response)
        if not response.endswith("\n"):
            sys.stdout.write("\n")

    def send_and_receive(
        self,
        line: str,
        expected_type: str = "device_status",
        timeout: float | None = None,
    ) -> str:
        effective_timeout = timeout if timeout is not None else self.timeout
        request = json.dumps(
            {
                "type": "forward",
                "expected_type": expected_type,
                "line": line,
                "timeout": effective_timeout,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            conn = socket.create_connection(
                (self.host, self.port),
                timeout=effective_timeout,
            )
        except OSError as exc:
            raise RuntimeError(
                f"local bridge unavailable at {self.host}:{self.port}; "
                "`codex-buddy start --transport wifi-server/auto` must keep "
                "wifi-bridge running. Run `codex-buddy logs` for the last "
                "bridge status."
            ) from exc
        with conn:
            conn.settimeout(effective_timeout)
            conn.sendall((request + "\n").encode("utf-8"))
            response = self._readline(conn)

        try:
            payload = json.loads(response)
        except json.JSONDecodeError as exc:
            raise RuntimeError("local bridge returned invalid JSON") from exc
        if payload.get("type") == "forward_error":
            message = payload.get("message") or "local bridge failed"
            raise RuntimeError(str(message))
        if payload.get("type") != "forward_result":
            raise RuntimeError(f"local bridge returned unexpected response: {payload}")
        forwarded = payload.get("line")
        if not isinstance(forwarded, str):
            raise RuntimeError("local bridge response is missing forwarded line")
        return forwarded

    def _readline(self, conn: socket.socket) -> str:
        chunks: list[bytes] = []
        while True:
            chunk = conn.recv(1)
            if not chunk:
                raise RuntimeError("local bridge closed the connection")
            chunks.append(chunk)
            if chunk == b"\n":
                break
        return b"".join(chunks).decode("utf-8", errors="replace")
