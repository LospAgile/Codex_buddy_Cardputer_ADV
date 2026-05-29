from __future__ import annotations

from argparse import Namespace
from contextlib import redirect_stderr
import io
import json
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_buddy import cli


class StartLauncherTest(unittest.TestCase):
    def test_open_watch_log_rotates_oversized_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "watch.log"
            log_path.write_text("old log\n" * 4, encoding="utf-8")

            handle = cli._open_watch_log(log_path, max_bytes=1)
            try:
                handle.write("new log\n")
            finally:
                handle.close()

            self.assertEqual(log_path.read_text(encoding="utf-8"), "new log\n")
            self.assertIn(
                "old log",
                (Path(tmp) / "watch.log.1").read_text(encoding="utf-8"),
            )

    def test_open_watch_log_can_disable_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "watch.log"
            log_path.write_text("old", encoding="utf-8")

            handle = cli._open_watch_log(log_path, max_bytes=0)
            try:
                handle.write("new")
            finally:
                handle.close()

            self.assertEqual(log_path.read_text(encoding="utf-8"), "oldnew")
            self.assertFalse((Path(tmp) / "watch.log.1").exists())

    def test_check_watch_startup_reports_early_exit_with_log_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "watch.log"
            log_path.write_text("line 1\nstartup failed\n", encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, "-c", "import sys; sys.exit(7)"],
                text=True,
            )
            try:
                with self.assertRaises(cli.LauncherError) as raised:
                    cli._check_watch_startup(proc, timeout=2.0, log_path=log_path)
            finally:
                proc.wait(timeout=5)

            message = str(raised.exception)
            self.assertIn("code 7", message)
            self.assertIn("startup failed", message)

    def test_stop_watch_process_terminates_running_child(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            text=True,
        )

        status = cli._stop_watch_process(proc)

        self.assertIn(status, {"terminated", "killed"})
        self.assertIsNotNone(proc.poll())

    def test_background_service_restarts_runtime_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            counter_path = tmp_path / "counter.txt"
            log_path = tmp_path / "watch.log"
            status_path = tmp_path / "status.json"
            script = (
                "import sys,time;"
                "from pathlib import Path;"
                "p=Path(sys.argv[1]);"
                "n=int(p.read_text()) if p.exists() and p.read_text() else 0;"
                "p.write_text(str(n+1));"
                "time.sleep(0.15);"
                "sys.exit(7)"
            )
            service = cli._BackgroundService(
                command=[sys.executable, "-c", script, str(counter_path)],
                label="watch",
                log_path=log_path,
                status_path=status_path,
                max_log_bytes=0,
                startup_timeout=0.05,
                restart_delay=0.05,
                monitor_interval=0.02,
            )

            stderr = io.StringIO()
            try:
                with redirect_stderr(stderr):
                    service.start()
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        if counter_path.exists() and int(counter_path.read_text()) >= 2:
                            break
                        time.sleep(0.02)
                    stop_status = service.stop()
            finally:
                service.stop()

            self.assertIn(stop_status, {"terminated", "killed", "already-exited:7"})
            self.assertGreaterEqual(service.restart_count, 1)
            self.assertGreaterEqual(int(counter_path.read_text()), 2)
            self.assertIn("exited (7); restarting", log_path.read_text(encoding="utf-8"))
            self.assertIn("restarting", stderr.getvalue())
            status = status_path.read_text(encoding="utf-8")
            self.assertIn('"label": "watch"', status)
            self.assertIn('"state": "stopped"', status)
            self.assertIn('"restart_count":', status)

    def test_validate_start_args_reports_missing_codex_binary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hook_runner = tmp_path / "hook.py"
            hook_runner.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            hook_runner.chmod(0o755)
            args = Namespace(
                watch_log_max_bytes=0,
                watch_startup_timeout=0,
                cwd=tmp_path,
                python=Path(sys.executable),
                codex_bin=str(tmp_path / "missing-codex"),
                hook_runner=hook_runner,
                transport="stdout",
                serial_port=None,
                ble_app=Path("/tmp/missing.app"),
            )

            with self.assertRaisesRegex(cli.LauncherError, "codex binary not found"):
                cli._validate_start_args(args)

    def test_validate_start_args_reports_missing_ble_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hook_runner = tmp_path / "hook.py"
            hook_runner.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            hook_runner.chmod(0o755)
            args = Namespace(
                watch_log_max_bytes=0,
                watch_startup_timeout=0,
                cwd=tmp_path,
                python=Path(sys.executable),
                codex_bin=sys.executable,
                hook_runner=hook_runner,
                transport="ble-socket",
                serial_port=None,
                ble_app=tmp_path / "missing.app",
            )

            with self.assertRaisesRegex(cli.LauncherError, "BLE helper app not found"):
                cli._validate_start_args(args)


class CliCommandTest(unittest.TestCase):
    def test_main_reports_runtime_errors_without_traceback(self) -> None:
        stderr = io.StringIO()
        with patch.object(cli, "_send_once", side_effect=RuntimeError("wifi down")):
            with redirect_stderr(stderr):
                code = cli.main(["once"])

        self.assertEqual(code, cli.EXIT_RUNTIME_ERROR)
        self.assertIn("codex-buddy: wifi down", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_exit_codes_json_outputs_known_semantics(self) -> None:
        stdout = io.StringIO()

        with patch("sys.stdout", stdout):
            code = cli.main(["exit-codes", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        codes = {row["name"]: row["code"] for row in payload["exit_codes"]}
        self.assertEqual(codes["ok"], cli.EXIT_OK)
        self.assertEqual(codes["config-error"], cli.EXIT_CONFIG)
        self.assertEqual(codes["interrupted"], cli.EXIT_INTERRUPTED)

    def test_launch_agent_print_outputs_watch_plist(self) -> None:
        stdout = io.StringIO()

        with patch("sys.stdout", stdout):
            code = cli.main(
                [
                    "--codex-home",
                    "/tmp/codex-home",
                    "launch-agent",
                    "print",
                    "--python",
                    sys.executable,
                    "--interval",
                    "3",
                    "--transport",
                    "auto",
                    "--wifi-port",
                    "47392",
                    "--ble-port",
                    "47391",
                ]
            )

        payload = plistlib.loads(stdout.getvalue().encode("utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(payload["Label"], cli.DEFAULT_LAUNCH_AGENT_LABEL)
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])
        self.assertIn("PYTHONPATH", payload["EnvironmentVariables"])
        arguments = payload["ProgramArguments"]
        self.assertIn("watch", arguments)
        self.assertIn("--transport", arguments)
        self.assertIn("auto", arguments)
        self.assertIn("--auto-probe-timeout", arguments)
        self.assertIn("/tmp/codex-home", arguments)

    def test_launch_agent_install_writes_plist_and_bootstraps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plist_path = Path(tmp) / "agent.plist"
            stdout = io.StringIO()

            with patch.object(cli, "_launchctl") as launchctl:
                with patch("sys.stdout", stdout):
                    code = cli.main(
                        [
                            "launch-agent",
                            "install",
                            "--plist",
                            str(plist_path),
                            "--label",
                            "com.example.codex-buddy",
                        ]
                    )

            self.assertEqual(code, 0)
            self.assertTrue(plist_path.exists())
            payload = plistlib.loads(plist_path.read_bytes())
            self.assertEqual(payload["Label"], "com.example.codex-buddy")
            calls = [call.args[0][0] for call in launchctl.call_args_list]
            self.assertEqual(calls, ["bootout", "bootstrap", "enable"])
            self.assertIn("installed com.example.codex-buddy", stdout.getvalue())

    def test_desktop_print_outputs_managed_hook_block(self) -> None:
        stdout = io.StringIO()

        with patch.object(
            cli,
            "probe_hook_info",
            return_value={"key": "hook-key", "currentHash": "hash-123"},
        ):
            with patch("sys.stdout", stdout):
                code = cli.main(
                    [
                        "desktop",
                        "print",
                        "--python",
                        sys.executable,
                        "--transport",
                        "ble-socket",
                    ]
                )

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn("BEGIN CODEX BUDDY DESKTOP HOOK", output)
        self.assertIn("[hooks]", output)
        self.assertIn("PermissionRequest", output)
        self.assertIn('[hooks.state."hook-key"]', output)
        self.assertIn('trusted_hash = "hash-123"', output)

    def test_desktop_print_can_use_hook_binary(self) -> None:
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmp:
            hook_binary = Path(tmp) / "codex-buddy-daemon"
            hook_binary.write_text("#!/bin/sh\n", encoding="utf-8")
            with patch.object(
                cli,
                "probe_hook_info",
                return_value={"key": "hook-key", "currentHash": "hash-123"},
            ) as probe:
                with patch("sys.stdout", stdout):
                    code = cli.main(
                        [
                            "desktop",
                            "print",
                            "--hook-binary",
                            str(hook_binary),
                            "--transport",
                            "local-bridge",
                        ]
                    )

        self.assertEqual(code, 0)
        output = stdout.getvalue()
        self.assertIn(str(hook_binary), output)
        self.assertIn("approval-hook", output)
        self.assertNotIn("PYTHONPATH=", output)
        self.assertIn("--transport local-bridge", output)
        self.assertIn('trusted_hash = "hash-123"', output)
        self.assertIn(str(hook_binary), probe.call_args.kwargs["hook_command"])

    def test_desktop_status_reports_managed_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "\n".join(
                    [
                        "# BEGIN CODEX BUDDY DESKTOP HOOK",
                        "hooks.PermissionRequest = []",
                        "# END CODEX BUDDY DESKTOP HOOK",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch("sys.stdout", stdout):
                code = cli.main(
                    [
                        "desktop",
                        "status",
                        "--config",
                        str(config_path),
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("managed-hook: yes", stdout.getvalue())

    def test_pet_dir_json_outputs_validation_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pet_dir = Path(tmp) / "my-pet"
            pet_dir.mkdir(parents=True)
            (pet_dir / "pet.json").write_text(
                json.dumps(
                    {
                        "id": "my-pet",
                        "displayName": "My Pet",
                        "spritesheetPath": "spritesheet.webp",
                    }
                ),
                encoding="utf-8",
            )
            (pet_dir / "spritesheet.webp").write_bytes(b"webp")
            stdout = io.StringIO()

            with patch(
                "codex_buddy.pet_assets.probe_image_size",
                return_value=(1536, 1872),
            ):
                with patch("sys.stdout", stdout):
                    code = cli.main(["pet", "--pet-dir", str(pet_dir), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["id"], "my-pet")
        self.assertEqual(payload["size"], [1536, 1872])

    def test_start_config_error_returns_config_exit_code(self) -> None:
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hook_runner = tmp_path / "hook.py"
            hook_runner.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            hook_runner.chmod(0o755)

            with redirect_stderr(stderr):
                code = cli.main(
                    [
                        "start",
                        "--transport",
                        "stdout",
                        "--cwd",
                        str(tmp_path),
                        "--python",
                        sys.executable,
                        "--hook-runner",
                        str(hook_runner),
                        "--codex-bin",
                        str(tmp_path / "missing-codex"),
                    ]
                )

        self.assertEqual(code, cli.EXIT_CONFIG)
        self.assertIn("codex binary not found", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_soak_reports_latency_summary(self) -> None:
        class RecordingTransport:
            closed = False

            def send_and_receive(
                self,
                line: str,
                expected_type: str = "device_status",
            ) -> str:
                self.line = line
                self.expected_type = expected_type
                return '{"v":0,"type":"device_status","status":"heartbeat_applied"}\n'

            def close(self) -> None:
                self.closed = True

        transport = RecordingTransport()
        stdout = io.StringIO()

        with patch.object(cli, "_transport_from_args", return_value=transport):
            with patch("sys.stdout", stdout):
                code = cli.main(["soak", "--count", "2", "--interval", "0"])

        output = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertTrue(transport.closed)
        self.assertEqual(transport.expected_type, "device_status")
        self.assertIn('"type":"heartbeat"', transport.line)
        self.assertIn("001 ok", output)
        self.assertIn("002 ok", output)
        self.assertIn("summary ok=2 fail=0", output)

    def test_soak_returns_nonzero_on_failures(self) -> None:
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

        transport = FailingTransport()
        stdout = io.StringIO()

        with patch.object(cli, "_transport_from_args", return_value=transport):
            with patch("sys.stdout", stdout):
                code = cli.main(["soak", "--count", "1", "--interval", "0"])

        output = stdout.getvalue()
        self.assertEqual(code, 1)
        self.assertTrue(transport.closed)
        self.assertIn("001 fail", output)
        self.assertIn("summary ok=0 fail=1", output)

    def test_soak_json_outputs_rounds_and_latency_stats(self) -> None:
        class RecordingTransport:
            closed = False

            def send_and_receive(
                self,
                line: str,
                expected_type: str = "device_status",
            ) -> str:
                return '{"v":0,"type":"device_status","status":"heartbeat_applied"}\n'

            def close(self) -> None:
                self.closed = True

        transport = RecordingTransport()
        stdout = io.StringIO()

        with patch.object(cli, "_transport_from_args", return_value=transport):
            with patch("sys.stdout", stdout):
                code = cli.main(["soak", "--count", "2", "--interval", "0", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(transport.closed)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["ok_count"], 2)
        self.assertEqual(payload["fail_count"], 0)
        self.assertEqual(len(payload["rounds"]), 2)
        self.assertTrue(payload["rounds"][0]["ok"])
        self.assertIn("avg_seconds", payload)
        self.assertIn("p95_seconds", payload)
        self.assertIn("max_seconds", payload)

    def test_soak_json_reports_failures(self) -> None:
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

        transport = FailingTransport()
        stdout = io.StringIO()

        with patch.object(cli, "_transport_from_args", return_value=transport):
            with patch("sys.stdout", stdout):
                code = cli.main(["soak", "--count", "1", "--interval", "0", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertTrue(transport.closed)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["ok_count"], 0)
        self.assertEqual(payload["fail_count"], 1)
        self.assertFalse(payload["rounds"][0]["ok"])
        self.assertEqual(payload["rounds"][0]["error"], "wifi down")

    def test_doctor_transport_reports_success_and_closes(self) -> None:
        class RecordingTransport:
            closed = False

            def send_and_receive(
                self,
                line: str,
                expected_type: str = "device_status",
            ) -> str:
                self.line = line
                self.expected_type = expected_type
                return '{"v":0,"type":"device_status","status":"ok"}\n'

            def close(self) -> None:
                self.closed = True

        transport = RecordingTransport()

        ok, detail = cli._doctor_transport(
            "fake",
            transport,
            '{"v":0,"type":"heartbeat"}\n',
        )

        self.assertTrue(ok)
        self.assertTrue(transport.closed)
        self.assertIn('"status":"ok"', detail)
        self.assertEqual(transport.expected_type, "device_status")

    def test_doctor_transport_reports_failure(self) -> None:
        class FailingTransport:
            def send_and_receive(
                self,
                line: str,
                expected_type: str = "device_status",
            ) -> str:
                raise RuntimeError("wifi unavailable")

        ok, detail = cli._doctor_transport(
            "fake",
            FailingTransport(),
            '{"v":0,"type":"heartbeat"}\n',
        )

        self.assertFalse(ok)
        self.assertEqual(detail, "wifi unavailable")

    def test_doctor_auto_result_prefers_wifi(self) -> None:
        ok, detail = cli._doctor_auto_result(
            wifi_ok=True,
            wifi_detail="wifi ok",
            ble_ok=True,
            ble_detail="ble ok",
        )

        self.assertTrue(ok)
        self.assertEqual(detail, "wifi-server: wifi ok")

    def test_doctor_auto_result_falls_back_to_ble(self) -> None:
        ok, detail = cli._doctor_auto_result(
            wifi_ok=False,
            wifi_detail="wifi down",
            ble_ok=True,
            ble_detail="ble ok",
        )

        self.assertTrue(ok)
        self.assertEqual(detail, "ble-socket fallback: ble ok")

    def test_doctor_exits_zero_when_auto_is_usable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "CodexBuddyBridge.app"
            helper.touch()
            status_file = Path(tmp) / "status.json"
            stdout = io.StringIO()

            with patch.object(cli, "resolve_ble_app", return_value=helper):
                with patch.object(cli.shutil, "which", return_value="/usr/bin/codex"):
                    with patch.object(
                        cli,
                        "_doctor_transport",
                        side_effect=[
                            (False, "wifi down"),
                            (True, "ble ok"),
                        ],
                    ):
                        with patch("sys.stdout", stdout):
                            code = cli.main(
                                [
                                    "doctor",
                                    "--timeout",
                                    "0.1",
                                    "--status-file",
                                    str(status_file),
                                ]
                            )

        output = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("ok ble-helper", output)
        self.assertIn("fail wifi-server: wifi down", output)
        self.assertIn("ok auto: ble-socket fallback: ble ok", output)
        self.assertIn("ok start-status: not started yet", output)
        self.assertIn("summary: usable", output)

    def test_doctor_json_outputs_machine_readable_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "CodexBuddyBridge.app"
            helper.touch()
            status_file = Path(tmp) / "status.json"
            stdout = io.StringIO()

            with patch.object(cli, "resolve_ble_app", return_value=helper):
                with patch.object(cli.shutil, "which", return_value="/usr/bin/codex"):
                    with patch.object(
                        cli,
                        "_doctor_transport",
                        side_effect=[
                            (True, "wifi ok"),
                            (True, "ble ok"),
                        ],
                    ):
                        with patch("sys.stdout", stdout):
                            code = cli.main(
                                [
                                    "doctor",
                                    "--json",
                                    "--timeout",
                                    "0.1",
                                    "--status-file",
                                    str(status_file),
                                ]
                            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["summary"], "usable")
        self.assertTrue(payload["usable"])
        checks = {check["name"]: check for check in payload["checks"]}
        self.assertTrue(checks["wifi-server"]["ok"])
        self.assertEqual(checks["auto"]["detail"], "wifi-server: wifi ok")
        self.assertIn("start-status", checks)

    def test_logs_outputs_start_status_and_log_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "status.json"
            log_path = tmp_path / "watch.log"
            status_path.write_text(
                json.dumps(
                    {
                        "label": "bridge",
                        "state": "running",
                        "pid": 123,
                        "restart_count": 2,
                        "last_exit_code": 7,
                        "log_path": str(log_path),
                        "updated_at": "2026-05-23 20:00:00 +0800",
                    }
                ),
                encoding="utf-8",
            )
            log_path.write_text("old\nrecent line\n", encoding="utf-8")
            stdout = io.StringIO()

            with patch("sys.stdout", stdout):
                code = cli.main(
                    [
                        "logs",
                        "--status-file",
                        str(status_path),
                        "--watch-log",
                        str(log_path),
                        "--lines",
                        "1",
                    ]
                )

        output = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("bridge state=running restarts=2", output)
        self.assertIn("recent line", output)
        self.assertEqual(output.rstrip().splitlines()[-1], "recent line")

    def test_logs_json_outputs_machine_readable_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            status_path = tmp_path / "status.json"
            log_path = tmp_path / "watch.log"
            status_path.write_text(
                json.dumps({"label": "watch", "state": "running"}),
                encoding="utf-8",
            )
            log_path.write_text("line\n", encoding="utf-8")
            stdout = io.StringIO()

            with patch("sys.stdout", stdout):
                code = cli.main(
                    [
                        "logs",
                        "--status-file",
                        str(status_path),
                        "--watch-log",
                        str(log_path),
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["status_ok"])
        self.assertEqual(payload["status"]["label"], "watch")
        self.assertEqual(payload["tail"], ["line"])

    def test_doctor_start_status_reads_restart_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_file = Path(tmp) / "status.json"
            status_file.write_text(
                (
                    '{"label":"bridge","state":"running","pid":123,'
                    '"restart_count":2,"last_exit_code":7,'
                    '"updated_at":"2026-05-23 10:00:00 +0800",'
                    '"log_path":"/tmp/codex-buddy-watch.log"}'
                ),
                encoding="utf-8",
            )

            ok, detail = cli._doctor_start_status(status_file)

        self.assertTrue(ok)
        self.assertIn("bridge state=running", detail)
        self.assertIn("restarts=2", detail)
        self.assertIn("last_exit=7", detail)

    def test_doctor_start_status_reports_restart_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_file = Path(tmp) / "status.json"
            status_file.write_text(
                '{"label":"bridge","state":"restart-failed","restart_count":1}',
                encoding="utf-8",
            )

            ok, detail = cli._doctor_start_status(status_file)

        self.assertFalse(ok)
        self.assertIn("state=restart-failed", detail)

    def test_doctor_exits_nonzero_when_auto_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            helper = Path(tmp) / "CodexBuddyBridge.app"
            helper.touch()
            stdout = io.StringIO()

            with patch.object(cli, "resolve_ble_app", return_value=helper):
                with patch.object(cli.shutil, "which", return_value="/usr/bin/codex"):
                    with patch.object(
                        cli,
                        "_doctor_transport",
                        side_effect=[
                            (False, "wifi down"),
                            (False, "ble down"),
                        ],
                    ):
                        with patch("sys.stdout", stdout):
                            code = cli.main(["doctor", "--timeout", "0.1"])

        output = stdout.getvalue()
        self.assertEqual(code, 1)
        self.assertIn(
            "fail auto: wifi-server: wifi down; ble-socket: ble down",
            output,
        )
        self.assertIn("summary: unavailable", output)

    def test_wifi_server_defaults_to_lan_listener(self) -> None:
        captured = {}

        def fake_send_once(codex_home: Path, transport: object, **kwargs: object) -> int:
            captured["transport"] = transport
            return 0

        with patch.object(cli, "_send_once", side_effect=fake_send_once):
            code = cli.main(["once", "--transport", "wifi-server"])

        self.assertEqual(code, 0)
        self.assertEqual(captured["transport"].host, "0.0.0.0")

    def test_auto_status_default_probe_timeout_covers_wifi_jitter(self) -> None:
        captured = {}

        def fake_send_once(codex_home: Path, transport: object, **kwargs: object) -> int:
            captured["transport"] = transport
            return 0

        with patch.object(cli, "_send_once", side_effect=fake_send_once):
            code = cli.main(["once", "--transport", "auto"])

        self.assertEqual(code, 0)
        self.assertEqual(captured["transport"].status_timeout, 20.0)

    def test_wifi_start_uses_bridge_for_background_and_hook(self) -> None:
        args = self._start_args(transport="wifi-server")

        background = cli._build_start_background_command(args)
        hook_command = cli._build_codex_hook_command(args, ["hello"])

        self.assertIn("wifi-bridge", background)
        self.assertNotIn("watch", background)
        self.assertIn("--session-cwd", background)
        self.assertIn("/tmp/project", background)
        self.assertNotIn("--session-source", background)
        self.assertIn("--wifi-token", background)
        transport_index = hook_command.index("--transport")
        self.assertEqual(hook_command[transport_index + 1], "local-bridge")
        self.assertIn("--bridge-port", hook_command)
        self.assertNotIn("--wifi-port", hook_command)

    def test_auto_start_selects_wifi_when_probe_succeeds(self) -> None:
        args = self._start_args(transport="auto")
        stderr = io.StringIO()

        with patch.object(cli, "_probe_wifi_transport") as probe:
            with redirect_stderr(stderr):
                resolved = cli._resolve_auto_transport_args(args)

        background = cli._build_start_background_command(resolved)
        hook_command = cli._build_codex_hook_command(resolved, ["hello"])

        probe.assert_called_once_with(args)
        self.assertEqual(args.transport, "auto")
        self.assertEqual(resolved.transport, "wifi-server")
        self.assertIn("auto selected wifi-server", stderr.getvalue())
        self.assertIn("wifi-bridge", background)
        transport_index = hook_command.index("--transport")
        self.assertEqual(hook_command[transport_index + 1], "local-bridge")

    def test_auto_start_falls_back_to_ble_when_probe_fails(self) -> None:
        args = self._start_args(transport="auto")
        stderr = io.StringIO()

        with patch.object(
            cli,
            "_probe_wifi_transport",
            side_effect=RuntimeError("no wifi device"),
        ):
            with redirect_stderr(stderr):
                resolved = cli._resolve_auto_transport_args(args)

        background = cli._build_start_background_command(resolved)
        hook_command = cli._build_codex_hook_command(resolved, ["hello"])

        self.assertEqual(resolved.transport, "ble-socket")
        self.assertTrue(resolved.auto_fallback_from_wifi)
        self.assertIn("auto selected ble-socket", stderr.getvalue())
        self.assertIn("watch", background)
        self.assertIn("--session-cwd", background)
        self.assertIn("/tmp/project", background)
        self.assertNotIn("--session-source", background)
        transport_index = background.index("--transport")
        self.assertEqual(background[transport_index + 1], "auto")
        self.assertIn("--wifi-token", background)
        self.assertIn("pair-token", background)
        self.assertIn("--auto-probe-timeout", background)
        self.assertNotIn("wifi-bridge", background)
        transport_index = hook_command.index("--transport")
        self.assertEqual(hook_command[transport_index + 1], "ble-socket")
        self.assertIn("--ble-port", hook_command)

    def test_auto_fallback_background_watch_keeps_wifi_recovery_probe(self) -> None:
        args = self._start_args(transport="ble-socket")
        args.auto_fallback_from_wifi = True

        background = cli._build_start_background_command(args)

        transport_index = background.index("--transport")
        self.assertEqual(background[transport_index + 1], "auto")
        self.assertIn("--wifi-host", background)
        self.assertIn("0.0.0.0", background)
        self.assertIn("--wifi-port", background)
        self.assertIn("47392", background)
        self.assertIn("--ble-port", background)
        self.assertIn("47391", background)
        self.assertIn("--auto-probe-timeout", background)

    def _start_args(self, transport: str) -> Namespace:
        return Namespace(
            codex_home=Path("/tmp/codex-home"),
            python=Path("/usr/bin/python3"),
            transport=transport,
            interval=2.0,
            serial_port=None,
            baud=115200,
            ble_app=Path("/tmp/CodexBuddyBridge.app"),
            ble_port=47391,
            ble_timeout=30.0,
            auto_probe_timeout=4.0,
            wifi_host="0.0.0.0",
            wifi_port=47392,
            wifi_token="pair-token",
            wifi_timeout=30.0,
            bridge_host="127.0.0.1",
            bridge_port=47393,
            bridge_timeout=120.0,
            no_heartbeat_watch=False,
            hook_runner=Path("/tmp/codex_with_buddy_hook.py"),
            codex_bin="codex",
            cwd=Path("/tmp/project"),
            hook_timeout=120,
            probe_timeout=20.0,
            approval_policy="untrusted",
            status_message="Waiting",
            alt_screen=False,
            status_file=Path("/tmp/codex-buddy-start-status.json"),
        )


if __name__ == "__main__":
    unittest.main()
