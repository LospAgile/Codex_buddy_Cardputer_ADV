from __future__ import annotations

from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from codex_buddy.protocol import ApprovalRequest
from codex_buddy.transport import LocalBridgeTransport
from codex_buddy.wifi_bridge import WifiBridgeServer


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class WifiBridgeServerTest(unittest.TestCase):
    def test_bridge_forwards_approval_request_to_wifi_device(self) -> None:
        wifi_port = free_port()
        bridge_port = free_port()
        with tempfile.TemporaryDirectory() as codex_home:
            server = WifiBridgeServer(
                codex_home=Path(codex_home),
                wifi_host="127.0.0.1",
                wifi_port=wifi_port,
                wifi_timeout=5,
                bridge_host="127.0.0.1",
                bridge_port=bridge_port,
                enable_heartbeat=False,
            )
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.start()
            self.assertTrue(server.wait_until_ready(timeout=5))

            result: dict[str, str] = {}

            def run_local_client() -> None:
                transport = LocalBridgeTransport(
                    host="127.0.0.1",
                    port=bridge_port,
                    timeout=5,
                )
                result["line"] = transport.send_and_receive(
                    ApprovalRequest("req-1", "exec_command", "pwd").to_line(),
                    expected_type="approval_decision",
                )

            client_thread = threading.Thread(target=run_local_client)
            client_thread.start()

            try:
                with self._connect_with_retry("127.0.0.1", wifi_port) as conn:
                    forwarded = self._readline(conn)
                    self.assertIn('"type":"approval_request"', forwarded)
                    self.assertIn('"id":"req-1"', forwarded)
                    conn.sendall(
                        b'{"v":0,"type":"device_status",'
                        b'"status":"approval_request_applied"}\n'
                    )
                    conn.sendall(
                        b'{"v":0,"type":"approval_decision",'
                        b'"id":"req-1","decision":"approve_once"}\n'
                    )

                client_thread.join(timeout=5)
                self.assertFalse(client_thread.is_alive())
                self.assertIn('"type":"approval_decision"', result["line"])
            finally:
                server.close()
                server_thread.join(timeout=5)

    def test_bridge_keeps_local_request_waiting_across_wifi_reconnect(self) -> None:
        wifi_port = free_port()
        bridge_port = free_port()
        with tempfile.TemporaryDirectory() as codex_home:
            server = WifiBridgeServer(
                codex_home=Path(codex_home),
                wifi_host="127.0.0.1",
                wifi_port=wifi_port,
                wifi_timeout=5,
                bridge_host="127.0.0.1",
                bridge_port=bridge_port,
                enable_heartbeat=False,
            )
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.start()
            self.assertTrue(server.wait_until_ready(timeout=5))

            result: dict[str, str] = {}

            def run_local_client() -> None:
                transport = LocalBridgeTransport(
                    host="127.0.0.1",
                    port=bridge_port,
                    timeout=5,
                )
                result["line"] = transport.send_and_receive(
                    ApprovalRequest("req-reconnect", "exec_command", "pwd").to_line(),
                    expected_type="approval_decision",
                )

            client_thread = threading.Thread(target=run_local_client)
            client_thread.start()

            try:
                with self._connect_with_retry("127.0.0.1", wifi_port) as conn:
                    forwarded = self._readline(conn)
                    self.assertIn('"type":"approval_request"', forwarded)
                    self.assertIn('"id":"req-reconnect"', forwarded)

                with self._connect_with_retry("127.0.0.1", wifi_port) as conn:
                    forwarded = self._readline(conn)
                    self.assertIn('"type":"approval_request"', forwarded)
                    self.assertIn('"id":"req-reconnect"', forwarded)
                    conn.sendall(
                        b'{"v":0,"type":"approval_decision",'
                        b'"id":"req-reconnect","decision":"approve_once"}\n'
                    )

                client_thread.join(timeout=5)
                self.assertFalse(client_thread.is_alive())
                self.assertIn('"type":"approval_decision"', result["line"])
            finally:
                server.close()
                server_thread.join(timeout=5)

    def _connect_with_retry(self, host: str, port: int) -> socket.socket:
        deadline = time.monotonic() + 5
        while True:
            try:
                return socket.create_connection((host, port), timeout=5)
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

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
