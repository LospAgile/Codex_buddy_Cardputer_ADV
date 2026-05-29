#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        print("missing C++ compiler for firmware keymap check", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="codex-buddy-keymap-") as temp_name:
      temp_dir = Path(temp_name)
      test_cpp = temp_dir / "keymap_test.cpp"
      binary = temp_dir / "keymap_test"
      test_cpp.write_text(TEST_SOURCE, encoding="utf-8")
      compile_result = subprocess.run(
          [
              compiler,
              "-std=c++17",
              "-Wall",
              "-Wextra",
              "-Werror",
              f"-I{PROJECT_ROOT / 'firmware' / 'include'}",
              str(PROJECT_ROOT / "firmware" / "src" / "KeyMap.cpp"),
              str(test_cpp),
              "-o",
              str(binary),
          ],
          cwd=PROJECT_ROOT,
          text=True,
          stdout=subprocess.PIPE,
          stderr=subprocess.STDOUT,
          timeout=20,
          check=False,
      )
      if compile_result.returncode != 0:
          print(compile_result.stdout.strip())
          return compile_result.returncode

      run_result = subprocess.run(
          [str(binary)],
          cwd=PROJECT_ROOT,
          text=True,
          stdout=subprocess.PIPE,
          stderr=subprocess.STDOUT,
          timeout=10,
          check=False,
      )
      if run_result.returncode != 0:
          print(run_result.stdout.strip())
          return run_result.returncode

    print("firmware keymap ok")
    return 0


TEST_SOURCE = textwrap.dedent(
    r'''
    #include "KeyMap.h"

    #include <cstdlib>
    #include <iostream>

    void expect(bool condition, const char* label) {
      if (!condition) {
        std::cerr << "failed: " << label << "\n";
        std::exit(1);
      }
    }

    void expect_action(bool ok, KeyAction actual, KeyAction expected, const char* label) {
      expect(ok, label);
      expect(actual == expected, label);
    }

    int main() {
      KeyAction action = KeyAction::Select;

      expect_action(fnLayerActionForChar(';', &action), action, KeyAction::Up, "Fn+; up");
      expect_action(fnLayerActionForChar(':', &action), action, KeyAction::Up, "Fn+: up");
      expect_action(fnLayerActionForChar('.', &action), action, KeyAction::Down, "Fn+. down");
      expect_action(fnLayerActionForChar('>', &action), action, KeyAction::Down, "Fn+> down");
      expect_action(fnLayerActionForChar(',', &action), action, KeyAction::Left, "Fn+, left");
      expect_action(fnLayerActionForChar('<', &action), action, KeyAction::Left, "Fn+< left");
      expect_action(fnLayerActionForChar('/', &action), action, KeyAction::Right, "Fn+/ right");
      expect_action(fnLayerActionForChar('?', &action), action, KeyAction::Right, "Fn+? right");
      expect_action(fnLayerActionForChar('\\', &action), action, KeyAction::Back, "Fn+backslash back");
      expect_action(fnLayerActionForChar('`', &action), action, KeyAction::Back, "Fn+backtick back");
      expect(!fnLayerActionForChar('x', &action), "Fn+x ignored");

      expect(isFnLayerActionChar(','), "Fn comma is action char");
      expect(isFnLayerActionChar('/'), "Fn slash is action char");
      expect(!isFnLayerActionChar('a'), "Fn a is not action char");

      expect_action(hidKeyAction(0x52, &action), action, KeyAction::Up, "HID up");
      expect_action(hidKeyAction(0x51, &action), action, KeyAction::Down, "HID down");
      expect_action(hidKeyAction(0x50, &action), action, KeyAction::Left, "HID left");
      expect_action(hidKeyAction(0x4F, &action), action, KeyAction::Right, "HID right");
      expect_action(hidKeyAction(0xD0, &action), action, KeyAction::Left, "HID modifier masked left");
      expect(!hidKeyAction(0x04, &action), "HID non-arrow ignored");

      expect_action(wordKeyAction('w', &action), action, KeyAction::Up, "WASD up");
      expect_action(wordKeyAction('s', &action), action, KeyAction::Down, "WASD down");
      expect_action(wordKeyAction('a', &action), action, KeyAction::Left, "WASD left");
      expect_action(wordKeyAction('d', &action), action, KeyAction::Right, "WASD right");
      expect_action(wordKeyAction(',', &action), action, KeyAction::Left, "word comma left");
      expect_action(wordKeyAction('.', &action), action, KeyAction::Down, "word dot down");
      expect_action(wordKeyAction('/', &action), action, KeyAction::Right, "word slash right");
      expect_action(wordKeyAction('Y', &action), action, KeyAction::Approve, "Y approve");
      expect_action(wordKeyAction('N', &action), action, KeyAction::Deny, "N deny");
      expect(!wordKeyAction('x', &action), "word x ignored");

      return 0;
    }
    '''
).lstrip()


if __name__ == "__main__":
    raise SystemExit(main())
