from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
import io
from pathlib import Path
import types
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOOK_RUNNER = PROJECT_ROOT / "tools" / "codex_with_buddy_hook.py"


def load_hook_runner() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("codex_with_buddy_hook", HOOK_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load hook runner module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HookRunnerToolTest(unittest.TestCase):
    def test_missing_codex_binary_reports_clean_error(self) -> None:
        hook_runner = load_hook_runner()
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            code = hook_runner.main(
                [
                    "--codex-bin",
                    "/definitely/missing/codex",
                    "--probe-timeout",
                    "0.1",
                    "--print-command",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("failed to launch process", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
