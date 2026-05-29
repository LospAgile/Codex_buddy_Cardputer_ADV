from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_buddy.session_tailer import (
    latest_session_file,
    read_jsonl,
    record_active_session,
    snapshot_latest_session,
    today_token_total,
)


class SessionTailerTest(unittest.TestCase):
    def test_today_token_total_aggregates_today_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / "sessions" / "2026" / "05" / "25"
            sessions.mkdir(parents=True)
            self._write_jsonl(sessions / "one.jsonl", 40)
            self._write_jsonl(sessions / "two.jsonl", 60)

            self.assertEqual(today_token_total(home), 100)
            snapshot = snapshot_latest_session(home)
            self.assertEqual(snapshot.today_tokens, 100)

    def test_active_session_marker_takes_priority_over_latest_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / "sessions" / "2026" / "05" / "27"
            sessions.mkdir(parents=True)
            older = sessions / "rollout-older-session.jsonl"
            newer = sessions / "rollout-newer-session.jsonl"
            self._write_session(older, "session-older", "older answer")
            self._write_session(newer, "session-newer", "newer answer")
            os.utime(older, (time.time() - 10, time.time() - 10))
            os.utime(newer, (time.time(), time.time()))

            record_active_session(home, "session-older")
            snapshot = snapshot_latest_session(home)

            self.assertEqual(snapshot.source, older)
            self.assertEqual(snapshot.summary, "older answer")

    def test_newer_session_beats_stale_active_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / "sessions" / "2026" / "05" / "27"
            sessions.mkdir(parents=True)
            older = sessions / "rollout-older-session.jsonl"
            newer = sessions / "rollout-newer-session.jsonl"
            self._write_session(older, "session-older", "older answer")
            self._write_session(newer, "session-newer", "newer answer")

            record_active_session(home, "session-older")
            future = time.time() + 60
            os.utime(newer, (future, future))

            snapshot = snapshot_latest_session(home)

            self.assertEqual(snapshot.source, newer)
            self.assertEqual(snapshot.summary, "newer answer")

    def test_session_cwd_ignores_active_marker_from_other_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / "sessions" / "2026" / "05" / "27"
            sessions.mkdir(parents=True)
            other = sessions / "rollout-other-session.jsonl"
            project = sessions / "rollout-project-session.jsonl"
            self._write_session(other, "session-other", "other answer", cwd="/tmp/other")
            self._write_session(project, "session-project", "project answer")

            record_active_session(home, "session-other", cwd="/tmp/other")
            snapshot = snapshot_latest_session(home, session_cwd=Path("/tmp/project"))

            self.assertEqual(snapshot.source, project)
            self.assertEqual(snapshot.summary, "project answer")

    def test_session_source_filters_cli_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / "sessions" / "2026" / "05" / "27"
            sessions.mkdir(parents=True)
            desktop = sessions / "rollout-desktop-session.jsonl"
            cli = sessions / "rollout-cli-session.jsonl"
            self._write_session(
                desktop,
                "session-desktop",
                "desktop answer",
                source="vscode",
            )
            self._write_session(cli, "session-cli", "cli answer", source="cli")
            future = time.time() + 20
            os.utime(desktop, (future, future))

            snapshot = snapshot_latest_session(home, session_source="cli")

            self.assertEqual(snapshot.source, cli)
            self.assertEqual(snapshot.summary, "cli answer")

    def test_active_marker_must_match_session_source_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / "sessions" / "2026" / "05" / "27"
            sessions.mkdir(parents=True)
            desktop = sessions / "rollout-desktop-session.jsonl"
            cli = sessions / "rollout-cli-session.jsonl"
            self._write_session(
                desktop,
                "session-desktop",
                "desktop answer",
                source="vscode",
            )
            self._write_session(cli, "session-cli", "cli answer", source="cli")

            record_active_session(home, "session-desktop")
            path = latest_session_file(home, session_source="cli")

            self.assertEqual(path, cli)

    def test_session_id_can_pin_heartbeat_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / "sessions" / "2026" / "05" / "27"
            sessions.mkdir(parents=True)
            first = sessions / "rollout-first-session.jsonl"
            second = sessions / "rollout-second-session.jsonl"
            self._write_session(first, "session-first", "first answer")
            self._write_session(second, "session-second", "second answer")

            snapshot = snapshot_latest_session(home, session_id="session-first")

            self.assertEqual(snapshot.source, first)
            self.assertEqual(snapshot.summary, "first answer")

    def test_read_jsonl_tails_recent_lines_without_requiring_full_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.jsonl"
            old_event = {
                "type": "event_msg",
                "payload": {"type": "token_count", "total": 1},
            }
            new_event = {
                "type": "event_msg",
                "payload": {"type": "token_count", "total": 2},
            }
            path.write_bytes(
                json.dumps(old_event).encode("utf-8")
                + b"\n"
                + (b"x" * 512)
                + b"\n"
                + json.dumps(new_event).encode("utf-8")
                + b"\n"
            )

            with patch("codex_buddy.session_tailer.JSONL_TAIL_MAX_BYTES", 128):
                events = read_jsonl(path, max_lines=8)

            self.assertEqual(events, [new_event])

    def _write_jsonl(self, path: Path, total_tokens: int) -> None:
        event = {
            "type": "event_msg",
            "payload": {"type": "token_count", "total": total_tokens},
        }
        path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        now = time.time()
        os.utime(path, (now, now))

    def _write_session(
        self,
        path: Path,
        session_id: str,
        message: str,
        *,
        cwd: str = "/tmp/project",
        source: str = "cli",
    ) -> None:
        events = [
            {
                "type": "session_meta",
                "payload": {"id": session_id, "cwd": cwd, "source": source},
            },
            {
                "type": "response_item",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": message}],
                },
            },
        ]
        path.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )
        now = time.time()
        os.utime(path, (now, now))


if __name__ == "__main__":
    unittest.main()
