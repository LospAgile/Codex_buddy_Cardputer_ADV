from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RELEASE_CHECK_PATH = PROJECT_ROOT / "tools" / "release_check.py"


def _load_release_check_module():
    spec = importlib.util.spec_from_file_location("codex_buddy_release_check", RELEASE_CHECK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {RELEASE_CHECK_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release_check = _load_release_check_module()


class ReleaseCheckToolTest(unittest.TestCase):
    def test_results_payload_summarizes_failures_and_skips(self) -> None:
        results = [
            release_check.CheckResult(
                name="ok-check",
                ok=True,
                skipped=False,
                elapsed_seconds=0.1,
                command=["true"],
                cwd=str(PROJECT_ROOT),
                detail="ok",
            ),
            release_check.CheckResult(
                name="failed-check",
                ok=False,
                skipped=False,
                elapsed_seconds=0.2,
                command=["false"],
                cwd=str(PROJECT_ROOT),
                detail="fail",
            ),
            release_check.CheckResult(
                name="skipped-check",
                ok=True,
                skipped=True,
                elapsed_seconds=0.0,
                command=["skip"],
                cwd=str(PROJECT_ROOT),
                detail="skipped",
            ),
        ]

        payload = release_check._results_payload(results)

        self.assertEqual(payload["summary"], "fail")
        self.assertFalse(payload["ok"])
        self.assertIn("generated_at", payload["metadata"])
        self.assertEqual(payload["metadata"]["project_root"], str(PROJECT_ROOT))
        self.assertIn("git", payload["metadata"])
        self.assertEqual(payload["failed"], ["failed-check"])
        self.assertEqual(payload["skipped"], ["skipped-check"])
        self.assertEqual(len(payload["checks"]), 3)

    def test_write_report_json_creates_parent_directory(self) -> None:
        result = release_check.CheckResult(
            name="ok-check",
            ok=True,
            skipped=False,
            elapsed_seconds=0.1,
            command=["true"],
            cwd=str(PROJECT_ROOT),
            detail="ok",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "nested" / "release-check.json"
            release_check._write_report_json(report_path, [result])

            payload = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"], "pass")
        self.assertIn("metadata", payload)
        self.assertEqual(payload["checks"][0]["name"], "ok-check")

    def test_write_report_md_creates_human_summary(self) -> None:
        results = [
            release_check.CheckResult(
                name="ok-check",
                ok=True,
                skipped=False,
                elapsed_seconds=0.1,
                command=["python3", "-m", "unittest"],
                cwd=str(PROJECT_ROOT),
                detail="ok",
            ),
            release_check.CheckResult(
                name="skipped-check",
                ok=True,
                skipped=True,
                elapsed_seconds=0.0,
                command=["skip"],
                cwd=str(PROJECT_ROOT),
                detail="skipped",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "nested" / "release-check.md"
            release_check._write_report_md(report_path, results)

            report = report_path.read_text(encoding="utf-8")

        self.assertIn("# Codex Buddy Release Check", report)
        self.assertIn("Generated: `", report)
        self.assertIn("Git: `", report)
        self.assertIn("Dirty: `", report)
        self.assertIn("Summary: **pass**", report)
        self.assertIn("- [ok] `ok-check`", report)
        self.assertIn("command: `python3 -m unittest`", report)
        self.assertIn("Skipped: `skipped-check`", report)

    def test_write_report_dir_creates_json_and_markdown(self) -> None:
        result = release_check.CheckResult(
            name="ok-check",
            ok=True,
            skipped=False,
            elapsed_seconds=0.1,
            command=["true"],
            cwd=str(PROJECT_ROOT),
            detail="ok",
        )
        metadata = {
            "generated_at": "2026-05-24T00:00:00+00:00",
            "project_root": str(PROJECT_ROOT),
            "git": {
                "branch": "test-branch",
                "commit": "abc1234",
                "dirty": False,
                "status_short": [],
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            report_dir = Path(tmpdir) / "bundle"
            release_check._write_report_dir(report_dir, [result], metadata=metadata)

            json_payload = json.loads(
                (report_dir / "release-check.json").read_text(encoding="utf-8")
            )
            markdown = (report_dir / "release-check.md").read_text(encoding="utf-8")

        self.assertTrue(json_payload["ok"])
        self.assertEqual(json_payload["metadata"], metadata)
        self.assertIn("Git: `test-branch` @ `abc1234`", markdown)
        self.assertIn("Summary: **pass**", markdown)


if __name__ == "__main__":
    unittest.main()
