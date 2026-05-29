from __future__ import annotations

from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
import unittest
from unittest.mock import patch

from codex_buddy.transport import (
    AutoStatusTransport,
    LocalBridgeTransport,
    MacOSBleSocketTransport,
    WiFiServerTransport,
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def connect_with_retry(port: int, *, timeout: float = 5.0) -> socket.socket:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=timeout)
        except OSError as exc:
            last_error = exc
            time.sleep(0.01)
    if last_error is not None:
        raise last_error
    return socket.create_connection(("127.0.0.1", port), timeout=timeout)


class WiFiServerTransportTest(unittest.TestCase):
    def test_auto_status_transport_falls_back_for_device_status(self) -> None:
        class FailingTransport:
            closed = False

            def send_and_receive(
                self,
                line: str,
                expected_type: str = "device_status",
            ) -> str:
                raise RuntimeError("wifi down")

            def close(self) -> None:
                self.closed = True

        class RecordingTransport:
            line = ""
            expected_type = ""

            def send_and_receive(
                self,
                line: str,
                expected_type: str = "device_status",
            ) -> str:
                self.line = line
                self.expected_type = expected_type
                return '{"v":0,"type":"device_status","status":"ok"}\n'

        primary = FailingTransport()
        fallback = RecordingTransport()
        transport = AutoStatusTransport(primary=primary, fallback=fallback)
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            response = transport.send_and_receive(
                '{"v":0,"type":"heartbeat","state":"idle"}\n'
            )

        self.assertTrue(primary.closed)
        self.assertIn('"status":"ok"', response)
        self.assertIn('"type":"heartbeat"', fallback.line)
        self.assertEqual(fallback.expected_type, "device_status")
        self.assertIn("auto selected ble-socket", stderr.getvalue())

    def test_auto_status_transport_does_not_fallback_for_approval(self) -> None:
        class FailingTransport:
            def send_and_receive(
                self,
                line: str,
                expected_type: str = "device_status",
            ) -> str:
                raise RuntimeError("wifi approval failed")

        class UnexpectedFallback:
            def send_and_receive(
                self,
                line: str,
                expected_type: str = "device_status",
            ) -> str:
                raise AssertionError("approval requests must not be duplicated")

        transport = AutoStatusTransport(
            primary=FailingTransport(),
            fallback=UnexpectedFallback(),
        )

        with self.assertRaisesRegex(RuntimeError, "wifi approval failed"):
            transport.send_and_receive(
                '{"v":0,"type":"approval_request","id":"req"}\n',
                expected_type="approval_decision",
            )

    def test_wifi_server_transport_sends_and_receives_json_lines(self) -> None:
        port = free_port()
        transport = WiFiServerTransport(host="127.0.0.1", port=port, timeout=5)
        result: dict[str, str] = {}

        def run_server() -> None:
            try:
                result["line"] = transport.send_and_receive(
                    '{"v":0,"type":"heartbeat","state":"idle"}\n'
                )
            finally:
                transport.close()

        thread = threading.Thread(target=run_server)
        thread.start()

        with connect_with_retry(port, timeout=5) as conn:
            request = self._readline(conn)
            self.assertEqual(request, '{"v":0,"type":"heartbeat","state":"idle"}')
            conn.sendall(
                b'{"v":0,"type":"device_status","status":"heartbeat_applied"}\n'
            )

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn('"status":"heartbeat_applied"', result["line"])

    def test_wifi_server_transport_validates_token(self) -> None:
        port = free_port()
        transport = WiFiServerTransport(
            host="127.0.0.1",
            port=port,
            token="pair-token",
            timeout=5,
        )
        result: dict[str, str] = {}

        def run_server() -> None:
            try:
                result["line"] = transport.send_and_receive(
                    '{"v":0,"type":"heartbeat","state":"idle"}\n'
                )
            finally:
                transport.close()

        thread = threading.Thread(target=run_server)
        thread.start()

        with connect_with_retry(port, timeout=5) as conn:
            conn.sendall(b'{"v":0,"type":"hello","token":"pair-token"}\n')
            request = self._readline(conn)
            self.assertEqual(request, '{"v":0,"type":"heartbeat","state":"idle"}')
            conn.sendall(
                b'{"v":0,"type":"device_status","status":"heartbeat_applied"}\n'
            )

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn('"status":"heartbeat_applied"', result["line"])

    def test_wifi_server_transport_reports_token_mismatch_hint(self) -> None:
        port = free_port()
        transport = WiFiServerTransport(
            host="127.0.0.1",
            port=port,
            token="pair-token",
            timeout=5,
        )
        error: dict[str, str] = {}

        def run_server() -> None:
            try:
                transport.send_and_receive('{"v":0,"type":"heartbeat"}\n')
            except RuntimeError as exc:
                error["message"] = str(exc)
            finally:
                transport.close()

        thread = threading.Thread(target=run_server)
        thread.start()

        with connect_with_retry(port, timeout=5) as conn:
            conn.sendall(b'{"v":0,"type":"hello","token":"wrong"}\n')

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn("token mismatch", error["message"])
        self.assertIn("device WiFi page", error["message"])

    def test_wifi_server_transport_reports_port_in_use_hint(self) -> None:
        port = free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            occupied.bind(("127.0.0.1", port))
            occupied.listen(1)
            transport = WiFiServerTransport(host="127.0.0.1", port=port, timeout=0.1)

            try:
                with self.assertRaisesRegex(RuntimeError, "could not listen"):
                    transport.send_and_receive('{"v":0,"type":"heartbeat"}\n')
            finally:
                transport.close()

    def test_wifi_server_transport_waits_for_expected_response_type(self) -> None:
        port = free_port()
        transport = WiFiServerTransport(host="127.0.0.1", port=port, timeout=5)
        result: dict[str, str] = {}

        def run_server() -> None:
            try:
                result["line"] = transport.send_and_receive(
                    '{"v":0,"type":"approval_request","id":"req"}\n',
                    expected_type="approval_decision",
                )
            finally:
                transport.close()

        thread = threading.Thread(target=run_server)
        thread.start()

        with connect_with_retry(port, timeout=5) as conn:
            request = self._readline(conn)
            self.assertEqual(request, '{"v":0,"type":"approval_request","id":"req"}')
            conn.sendall(
                b'{"v":0,"type":"device_status","status":"approval_request_applied"}\n'
            )
            conn.sendall(
                b'{"v":0,"type":"approval_decision","id":"req","decision":"approve_once"}\n'
            )

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn('"type":"approval_decision"', result["line"])

    def test_wifi_server_transport_retries_after_device_disconnect(self) -> None:
        port = free_port()
        transport = WiFiServerTransport(host="127.0.0.1", port=port, timeout=5)
        result: dict[str, str] = {}

        def run_server() -> None:
            try:
                result["line"] = transport.send_and_receive(
                    '{"v":0,"type":"approval_request","id":"req-reconnect"}\n',
                    expected_type="approval_decision",
                )
            finally:
                transport.close()

        thread = threading.Thread(target=run_server)
        thread.start()

        with connect_with_retry(port, timeout=5) as conn:
            request = self._readline(conn)
            self.assertIn('"id":"req-reconnect"', request)

        with connect_with_retry(port, timeout=5) as conn:
            request = self._readline(conn)
            self.assertIn('"id":"req-reconnect"', request)
            conn.sendall(
                b'{"v":0,"type":"approval_decision",'
                b'"id":"req-reconnect","decision":"approve_once"}\n'
            )

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn('"type":"approval_decision"', result["line"])

    def test_wifi_server_transport_keeps_status_connection_during_short_stall(self) -> None:
        port = free_port()
        transport = WiFiServerTransport(host="127.0.0.1", port=port, timeout=2)
        result: dict[str, str] = {}

        def run_server() -> None:
            try:
                result["line"] = transport.send_and_receive(
                    '{"v":0,"type":"heartbeat","state":"idle"}\n',
                    expected_type="device_status",
                )
            finally:
                transport.close()

        with patch("codex_buddy.transport.DEVICE_STATUS_RESPONSE_TIMEOUT", 0.1):
            thread = threading.Thread(target=run_server)
            thread.start()

            with connect_with_retry(port, timeout=5) as conn:
                request = self._readline(conn)
                self.assertEqual(request, '{"v":0,"type":"heartbeat","state":"idle"}')
                time.sleep(0.2)
                conn.sendall(
                    b'{"v":0,"type":"device_status",'
                    b'"status":"heartbeat_applied"}\n'
                )

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn('"status":"heartbeat_applied"', result["line"])

    def test_wifi_server_transport_rejects_oversized_response_line(self) -> None:
        transport = WiFiServerTransport(host="127.0.0.1", port=0, timeout=1)
        left, right = socket.socketpair()
        try:
            with patch("codex_buddy.transport.MAX_TRANSPORT_LINE_BYTES", 8):
                right.sendall(b"012345678\n")
                with self.assertRaisesRegex(RuntimeError, "too large"):
                    transport._readline(left)
        finally:
            left.close()
            right.close()

    def test_wifi_server_transport_limits_unexpected_response_lines(self) -> None:
        transport = WiFiServerTransport(host="127.0.0.1", port=0, timeout=1)
        left, right = socket.socketpair()
        try:
            with patch("codex_buddy.transport.MAX_IGNORED_RESPONSE_LINES", 2):
                right.sendall(
                    b"not-json\n"
                    b'{"v":0,"type":"device_status"}\n'
                    b'{"v":0,"type":"device_status"}\n'
                )
                with self.assertRaisesRegex(RuntimeError, "expected approval_decision"):
                    transport._read_expected(left, "approval_decision")
        finally:
            left.close()
            right.close()

    def test_local_bridge_transport_forwards_expected_type(self) -> None:
        port = free_port()
        result: dict[str, str] = {}

        def run_bridge() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
                listener.listen(1)
                conn, _ = listener.accept()
                with conn:
                    request = self._readline(conn)
                    result["request"] = request
                    conn.sendall(
                        b'{"type":"forward_result","line":"{'
                        b'\\"v\\":0,\\"type\\":\\"approval_decision\\",'
                        b'\\"id\\":\\"req\\",\\"decision\\":\\"approve_once\\"}\\n"}\n'
                    )

        thread = threading.Thread(target=run_bridge)
        thread.start()

        transport = LocalBridgeTransport(host="127.0.0.1", port=port, timeout=5)
        response = transport.send_and_receive(
            '{"v":0,"type":"approval_request","id":"req"}\n',
            expected_type="approval_decision",
        )

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn('"expected_type":"approval_decision"', result["request"])
        self.assertIn('"type":"approval_decision"', response)

    def test_local_bridge_transport_reports_unavailable_hint(self) -> None:
        port = free_port()
        transport = LocalBridgeTransport(host="127.0.0.1", port=port, timeout=0.1)

        with self.assertRaisesRegex(RuntimeError, "local bridge unavailable") as raised:
            transport.send_and_receive(
                '{"v":0,"type":"approval_request","id":"req"}\n',
                expected_type="approval_decision",
            )

        self.assertIn("codex-buddy logs", str(raised.exception))

    def test_ble_socket_transport_fails_fast_on_helper_error(self) -> None:
        port = free_port()
        ready = threading.Event()

        def run_bridge() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
                listener.listen(1)
                ready.set()
                conn, _ = listener.accept()
                with conn:
                    self._readline(conn)
                    conn.sendall(
                        b'{"v":0,"type":"error","error":"approval pending"}\n'
                    )

        thread = threading.Thread(target=run_bridge)
        thread.start()
        self.assertTrue(ready.wait(timeout=5))

        class RunningBleSocketTransport(MacOSBleSocketTransport):
            def _ensure_server(self) -> None:
                return None

        transport = RunningBleSocketTransport(port=port, timeout=5)
        with self.assertRaisesRegex(RuntimeError, "approval pending"):
            transport.send_and_receive('{"v":0,"type":"heartbeat","state":"idle"}\n')

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())

    def test_ble_socket_transport_sends_per_request_timeout(self) -> None:
        port = free_port()
        captured: list[str] = []
        ready = threading.Event()

        def run_bridge() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
                listener.listen(1)
                ready.set()
                conn, _ = listener.accept()
                with conn:
                    captured.append(self._readline(conn))
                    conn.sendall(
                        b'{"v":0,"type":"approval_decision","decision":"approve_once"}\n'
                    )

        thread = threading.Thread(target=run_bridge)
        thread.start()
        self.assertTrue(ready.wait(timeout=5))

        class RunningBleSocketTransport(MacOSBleSocketTransport):
            def _ensure_server(self) -> None:
                return None

        transport = RunningBleSocketTransport(port=port, timeout=5)
        response = transport.send_and_receive(
            '{"v":0,"type":"approval_request","id":"demo","tool":"exec_command"}\n',
            expected_type="approval_decision",
            timeout=42,
        )

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn('"approval_decision"', response)
        self.assertEqual(json.loads(captured[0])["timeout"], 42)

    def test_ble_socket_transport_restarts_after_timeout(self) -> None:
        port = free_port()
        first_ready = threading.Event()
        second_ready = threading.Event()

        def run_stalled_bridge() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
                listener.listen(1)
                first_ready.set()
                conn, _ = listener.accept()
                listener.close()
                with conn:
                    self._readline(conn)
                    time.sleep(0.5)

        def run_working_bridge() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
                listener.listen(1)
                second_ready.set()
                conn, _ = listener.accept()
                with conn:
                    self._readline(conn)
                    conn.sendall(
                        b'{"v":0,"type":"device_status",'
                        b'"status":"heartbeat_applied"}\n'
                    )

        first_thread = threading.Thread(target=run_stalled_bridge)
        first_thread.start()
        self.assertTrue(first_ready.wait(timeout=5))

        class RestartingBleSocketTransport(MacOSBleSocketTransport):
            restarted = False

            def _ensure_server(self) -> None:
                return None

            def _restart_server(self) -> None:
                self.restarted = True
                second_thread = threading.Thread(target=run_working_bridge)
                second_thread.start()
                self.second_thread = second_thread
                self.assert_second_ready()

            def assert_second_ready(self) -> None:
                if not second_ready.wait(timeout=5):
                    raise RuntimeError("second bridge did not start")

        transport = RestartingBleSocketTransport(port=port, timeout=0.2)
        response = transport.send_and_receive(
            '{"v":0,"type":"heartbeat","state":"idle"}\n'
        )

        first_thread.join(timeout=5)
        self.assertFalse(first_thread.is_alive())
        transport.second_thread.join(timeout=5)  # type: ignore[attr-defined]
        self.assertFalse(transport.second_thread.is_alive())  # type: ignore[attr-defined]
        self.assertTrue(transport.restarted)
        self.assertIn('"status":"heartbeat_applied"', response)

    def test_ble_socket_transport_passes_device_name_when_starting_server(self) -> None:
        calls = 0

        class StartingBleSocketTransport(MacOSBleSocketTransport):
            def _is_listening(self) -> bool:
                nonlocal calls
                calls += 1
                return calls > 1

        transport = StartingBleSocketTransport(
            app=Path("/tmp/CodexBuddyBridge.app"),
            port=47391,
            timeout=1,
            device_name="Custom-Buddy",
        )

        with patch("codex_buddy.transport.resolve_ble_app", return_value=transport.app):
            with patch.object(Path, "exists", return_value=True):
                with patch("codex_buddy.transport.subprocess.run") as run:
                    run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                    transport._ensure_server()

        command = run.call_args.args[0]
        self.assertIn("--device-name", command)
        self.assertIn("Custom-Buddy", command)

    def test_ble_socket_transport_sends_pair_before_payload(self) -> None:
        port = free_port()
        captured: list[str] = []
        ready = threading.Event()

        def run_bridge() -> None:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
                listener.listen(2)
                ready.set()

                conn, _ = listener.accept()
                with conn:
                    captured.append(self._readline(conn))
                    conn.sendall(b'{"v":0,"type":"device_status","status":"pair_ok"}\n')

                conn, _ = listener.accept()
                with conn:
                    captured.append(self._readline(conn))
                    conn.sendall(
                        b'{"v":0,"type":"device_status",'
                        b'"status":"heartbeat_applied"}\n'
                    )

        thread = threading.Thread(target=run_bridge)
        thread.start()
        self.assertTrue(ready.wait(timeout=5))

        class RunningBleSocketTransport(MacOSBleSocketTransport):
            def _ensure_server(self) -> None:
                return None

        transport = RunningBleSocketTransport(
            port=port,
            timeout=5,
            pair_code="123456",
        )
        response = transport.send_and_receive(
            '{"v":0,"type":"heartbeat","state":"idle"}\n'
        )

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(json.loads(captured[0])["type"], "pair_request")
        self.assertEqual(json.loads(captured[0])["code"], "123456")
        self.assertEqual(json.loads(captured[1])["type"], "heartbeat")
        self.assertIn('"status":"heartbeat_applied"', response)

    def _readline(self, conn: socket.socket) -> str:
        data = bytearray()
        while not data.endswith(b"\n"):
            chunk = conn.recv(1)
            if not chunk:
                break
            data.extend(chunk)
        return data.decode("utf-8").strip()


if __name__ == "__main__":
    unittest.main()
