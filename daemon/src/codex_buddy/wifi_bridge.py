from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import socket
import sys
import threading

from .pet_assets import load_selected_pet
from .session_tailer import snapshot_latest_session
from .transport import WiFiServerTransport


@dataclass
class WifiBridgeServer:
    codex_home: Path
    wifi_host: str = "0.0.0.0"
    wifi_port: int = 47392
    wifi_token: str = ""
    wifi_timeout: float = 30.0
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 47393
    bridge_timeout: float = 120.0
    interval: float = 2.0
    enable_heartbeat: bool = True
    session_id: str | None = None
    session_cwd: Path | None = None
    session_source: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _ready: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _listener: socket.socket | None = field(default=None, init=False, repr=False)
    _transport: WiFiServerTransport = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._transport = WiFiServerTransport(
            host=self.wifi_host,
            port=self.wifi_port,
            token=self.wifi_token,
            timeout=self.wifi_timeout,
        )

    def serve_forever(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.bridge_host, self.bridge_port))
        listener.listen(8)
        listener.settimeout(0.5)
        self._listener = listener
        self._ready.set()

        heartbeat_thread: threading.Thread | None = None
        if self.enable_heartbeat:
            heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name="codex-buddy-wifi-heartbeat",
                daemon=True,
            )
            heartbeat_thread.start()

        try:
            while not self._stop.is_set():
                try:
                    conn, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
                self._handle_client(conn)
        finally:
            self.close()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1)

    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        return self._ready.wait(timeout)

    def close(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            finally:
                self._listener = None
        self._transport.close()

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._send_heartbeat()
            except Exception as exc:
                print(f"wifi-bridge heartbeat error: {exc}", file=sys.stderr, flush=True)
            if self._stop.wait(max(0.25, self.interval)):
                break

    def _send_heartbeat(self) -> None:
        snapshot = snapshot_latest_session(
            self.codex_home,
            session_id=self.session_id,
            session_cwd=self.session_cwd,
            session_source=self.session_source,
        )
        pet = load_selected_pet(self.codex_home)
        heartbeat = snapshot.to_heartbeat(pet.to_protocol() if pet else None)
        response = self._forward(heartbeat.to_line(), "device_status")
        if response:
            sys.stdout.write(response)
            if not response.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()

    def _handle_client(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(self.bridge_timeout)
            try:
                request = json.loads(self._readline(conn))
                if request.get("type") != "forward":
                    raise ValueError("unsupported bridge request")
                line = request.get("line")
                if not isinstance(line, str) or not line:
                    raise ValueError("bridge request missing line")
                expected_type = request.get("expected_type") or "device_status"
                if not isinstance(expected_type, str):
                    raise ValueError("bridge request expected_type must be a string")
                timeout = request.get("timeout")
                request_timeout = (
                    float(timeout)
                    if isinstance(timeout, int | float) and float(timeout) > 0
                    else None
                )
                response = self._forward(line, expected_type, timeout=request_timeout)
                self._write_json(conn, {"type": "forward_result", "line": response})
            except Exception as exc:
                self._write_json(conn, {"type": "forward_error", "message": str(exc)})

    def _forward(
        self,
        line: str,
        expected_type: str,
        timeout: float | None = None,
    ) -> str:
        with self._lock:
            return self._transport.send_and_receive(
                line,
                expected_type=expected_type,
                timeout=timeout,
            )

    def _readline(self, conn: socket.socket) -> str:
        chunks: list[bytes] = []
        while True:
            chunk = conn.recv(1)
            if not chunk:
                raise RuntimeError("local client closed the connection")
            chunks.append(chunk)
            if chunk == b"\n":
                break
        return b"".join(chunks).decode("utf-8", errors="replace")

    def _write_json(self, conn: socket.socket, payload: dict[str, object]) -> None:
        conn.sendall(
            (
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
        )
