from __future__ import annotations

import json
import unittest

from codex_buddy.protocol import (
    ApprovalRequest,
    Entry,
    Heartbeat,
    PetInfo,
    WifiConfigRequest,
    build_approval_decision,
)
from codex_buddy.codex_hook import (
    approval_request_from_hook_input,
    hook_context_from_input,
    hook_decision_output,
    parse_approval_decision_line,
    run_permission_request_hook,
)


class ProtocolTest(unittest.TestCase):
    def test_heartbeat_keeps_chinese_text(self) -> None:
        line = Heartbeat(
            state="running",
            summary="正在处理中文消息",
            entries=[Entry("tool", "执行命令")],
            total_tokens=42,
            today_tokens=7,
            pet=PetInfo("codex-placeholder", "Codex Placeholder"),
        ).to_line()

        self.assertTrue(line.endswith("\n"))
        self.assertIn("正在处理中文消息", line)
        payload = json.loads(line)
        self.assertEqual(payload["state"], "running")
        self.assertEqual(payload["animation"], "running")
        self.assertEqual(payload["entries"][0]["text"], "执行命令")
        self.assertEqual(payload["tokens"]["total"], 42)
        self.assertEqual(payload["tokens"]["today"], 7)

    def test_invalid_state_falls_back_to_idle(self) -> None:
        payload = json.loads(Heartbeat(state="unknown").to_line())
        self.assertEqual(payload["state"], "idle")
        self.assertEqual(payload["animation"], "idle")

    def test_waiting_state_maps_to_waving_animation(self) -> None:
        payload = json.loads(Heartbeat(state="waiting").to_line())
        self.assertEqual(payload["state"], "waiting")
        self.assertEqual(payload["animation"], "waving")

    def test_explicit_valid_animation_is_kept(self) -> None:
        payload = json.loads(Heartbeat(state="review", animation="jumping").to_line())
        self.assertEqual(payload["animation"], "jumping")

    def test_explicit_waiting_animation_is_supported(self) -> None:
        payload = json.loads(Heartbeat(state="waiting", animation="waiting").to_line())
        self.assertEqual(payload["animation"], "waiting")

    def test_approval_decision_validates_decision(self) -> None:
        payload = json.loads(build_approval_decision("abc", "deny"))
        self.assertEqual(payload["type"], "approval_decision")
        self.assertEqual(payload["decision"], "deny")
        with self.assertRaises(ValueError):
            build_approval_decision("abc", "maybe")

    def test_approval_request_contains_choices(self) -> None:
        payload = json.loads(
            ApprovalRequest("req-1", "exec_command", "需要运行命令").to_line()
        )

        self.assertEqual(payload["type"], "approval_request")
        self.assertEqual(payload["id"], "req-1")
        self.assertEqual(payload["tool"], "exec_command")
        self.assertEqual(payload["choices"], ["approve_once", "deny"])

    def test_wifi_config_request_keeps_secret_spacing(self) -> None:
        payload = json.loads(
            WifiConfigRequest(
                ssid="Office WiFi",
                password=" pass with spaces ",
                host="192.168.1.10",
                port=47392,
                token=" token ",
            ).to_line()
        )

        self.assertEqual(payload["type"], "wifi_config")
        self.assertEqual(payload["ssid"], "Office WiFi")
        self.assertEqual(payload["password"], " pass with spaces ")
        self.assertEqual(payload["host"], "192.168.1.10")
        self.assertEqual(payload["port"], 47392)
        self.assertEqual(payload["token"], " token ")
        self.assertTrue(payload["connect"])

    def test_wifi_config_clear(self) -> None:
        payload = json.loads(WifiConfigRequest(clear=True, connect=False).to_line())

        self.assertEqual(payload["type"], "wifi_config")
        self.assertTrue(payload["clear"])
        self.assertFalse(payload["connect"])

    def test_hook_builds_approval_request_from_permission_request(self) -> None:
        request = approval_request_from_hook_input(
            json.dumps(
                {
                    "session_id": "session-123456",
                    "turn_id": "turn-abcdef",
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "exec_command",
                    "tool_input": {"command": "ls -la"},
                }
            )
        )

        self.assertEqual(request.tool, "exec_command")
        self.assertEqual(request.hint, "ls -la")
        self.assertTrue(request.request_id.startswith("session--turn-ab"))

    def test_hook_hint_includes_workdir_for_command(self) -> None:
        request = approval_request_from_hook_input(
            json.dumps(
                {
                    "session_id": "s",
                    "turn_id": "t",
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "exec_command",
                    "tool_input": {
                        "command": "python3 tools/release_check.py",
                        "workdir": "/tmp/codex-buddy",
                    },
                }
            )
        )

        self.assertEqual(
            request.hint,
            "python3 tools/release_check.py @ /tmp/codex-buddy",
        )

    def test_hook_context_extracts_session_for_heartbeat_focus(self) -> None:
        context = hook_context_from_input(
            json.dumps(
                {
                    "session_id": "session-123456",
                    "turn_id": "turn-abcdef",
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "exec_command",
                    "tool_input": {"command": "pwd", "workdir": "/tmp/project"},
                }
            )
        )

        self.assertEqual(context.session_id, "session-123456")
        self.assertEqual(context.cwd, "/tmp/project")

    def test_hook_hint_redacts_inline_secret_assignments(self) -> None:
        request = approval_request_from_hook_input(
            json.dumps(
                {
                    "session_id": "s",
                    "turn_id": "t",
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "exec_command",
                    "tool_input": {
                        "command": "OPENAI_API_KEY=sk-test curl https://example.com"
                    },
                }
            )
        )

        self.assertNotIn("sk-test", request.hint)
        self.assertIn("OPENAI_API_KEY=[redacted]", request.hint)

    def test_hook_hint_summarizes_and_redacts_structured_input(self) -> None:
        request = approval_request_from_hook_input(
            json.dumps(
                {
                    "session_id": "s",
                    "turn_id": "t",
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "web_request",
                    "tool_input": {
                        "url": "https://api.example.com/items",
                        "token": "secret-token",
                        "method": "POST",
                    },
                }
            )
        )

        self.assertIn("url=https://api.example.com/items", request.hint)
        self.assertIn("token=[redacted]", request.hint)
        self.assertNotIn("secret-token", request.hint)

    def test_hook_maps_hardware_approval_to_codex_allow(self) -> None:
        def send_request(request: ApprovalRequest) -> str:
            return json.dumps(
                {
                    "v": 0,
                    "type": "approval_decision",
                    "id": request.request_id,
                    "decision": "approve_once",
                }
            )

        output = run_permission_request_hook(
            json.dumps(
                {
                    "session_id": "s",
                    "turn_id": "t",
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "exec_command",
                    "tool_input": {"command": "pwd"},
                }
            ),
            send_request,
        )

        payload = json.loads(output)
        decision = payload["hookSpecificOutput"]["decision"]
        self.assertEqual(decision["behavior"], "allow")

    def test_hook_maps_hardware_deny_to_codex_deny(self) -> None:
        decision = parse_approval_decision_line(
            '{"v":0,"type":"approval_decision","id":"req","decision":"deny"}'
        )

        self.assertEqual(decision.decision, "deny")
        payload = json.loads(hook_decision_output("deny", "no"))
        self.assertEqual(
            payload["hookSpecificOutput"]["decision"],
            {"behavior": "deny", "message": "no"},
        )


if __name__ == "__main__":
    unittest.main()
