from __future__ import annotations

import unittest

from codex_buddy.codex_state import snapshot_from_events


class CodexStateTest(unittest.TestCase):
    def test_function_call_maps_to_running(self) -> None:
        snapshot = snapshot_from_events(
            [
                {"type": "event_msg", "payload": {"type": "task_started"}},
                {
                    "type": "response_item",
                    "item": {"type": "function_call", "name": "exec_command"},
                },
            ]
        )

        self.assertEqual(snapshot.state, "running")
        self.assertEqual(snapshot.animation, "running")
        self.assertEqual(snapshot.entries[0].text, "exec_command")

    def test_assistant_message_maps_to_review(self) -> None:
        snapshot = snapshot_from_events(
            [
                {
                    "type": "response_item",
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "完成了"}],
                    },
                }
            ]
        )

        self.assertEqual(snapshot.state, "review")
        self.assertEqual(snapshot.animation, "review")
        self.assertEqual(snapshot.summary, "完成了")
        self.assertEqual(snapshot.entries[0].kind, "assistant")
        self.assertEqual(snapshot.entries[0].text, "完成了")

    def test_user_and_assistant_messages_flow_to_entries(self) -> None:
        snapshot = snapshot_from_events(
            [
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "帮我检查构建"},
                },
                {
                    "type": "event_msg",
                    "payload": {"type": "agent_message", "message": "构建已经通过"},
                },
            ]
        )

        self.assertEqual(snapshot.state, "review")
        self.assertEqual(snapshot.summary, "构建已经通过")
        self.assertEqual(
            [(entry.kind, entry.text) for entry in snapshot.entries],
            [("user", "帮我检查构建"), ("assistant", "构建已经通过")],
        )

    def test_boilerplate_user_messages_are_not_displayed(self) -> None:
        snapshot = snapshot_from_events(
            [
                {
                    "type": "response_item",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "# AGENTS.md instructions for /tmp/project",
                            }
                        ],
                    },
                },
                {
                    "type": "response_item",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "真实问题"}],
                    },
                },
            ]
        )

        self.assertEqual(snapshot.summary, "真实问题")
        self.assertEqual(len(snapshot.entries), 1)
        self.assertEqual(snapshot.entries[0].text, "真实问题")

    def test_permission_event_maps_to_waiting(self) -> None:
        snapshot = snapshot_from_events(
            [{"type": "permission_request", "payload": {"tool": "exec_command"}}]
        )

        self.assertEqual(snapshot.state, "waiting")
        self.assertEqual(snapshot.animation, "waving")

    def test_token_count_flows_to_heartbeat(self) -> None:
        snapshot = snapshot_from_events(
            [
                {
                    "type": "event_msg",
                    "payload": {"type": "token_count", "total": 1234},
                }
            ]
        )
        heartbeat = snapshot.to_heartbeat()

        self.assertEqual(snapshot.total_tokens, 1234)
        self.assertEqual(heartbeat.total_tokens, 1234)

    def test_codex_desktop_token_count_envelope_flows_to_heartbeat(self) -> None:
        snapshot = snapshot_from_events(
            [
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 50,
                                "output_tokens": 20,
                                "total_tokens": 120,
                            },
                            "last_token_usage": {
                                "total_tokens": 12,
                            },
                        },
                    },
                }
            ]
        )
        heartbeat = snapshot.to_heartbeat()

        self.assertEqual(snapshot.total_tokens, 120)
        self.assertEqual(heartbeat.total_tokens, 120)


if __name__ == "__main__":
    unittest.main()
