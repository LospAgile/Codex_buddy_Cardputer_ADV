#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIRMWARE_DIR = PROJECT_ROOT / "firmware"
DEFAULT_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
DEFAULT_PIO = PROJECT_ROOT / ".venv" / "bin" / "pio"


@dataclass
class CheckResult:
    name: str
    ok: bool
    skipped: bool
    elapsed_seconds: float
    command: list[str]
    cwd: str
    detail: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="release_check.py",
        description="Run local Codex Buddy release checks.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=DEFAULT_PYTHON if DEFAULT_PYTHON.exists() else Path(sys.executable),
        help="Python executable used for daemon checks.",
    )
    parser.add_argument(
        "--pio",
        type=Path,
        default=DEFAULT_PIO if DEFAULT_PIO.exists() else Path(shutil.which("pio") or "pio"),
        help="PlatformIO executable used for firmware compile.",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--firmware-timeout", type=float, default=180.0)
    parser.add_argument("--skip-firmware", action="store_true")
    parser.add_argument(
        "--with-hardware",
        action="store_true",
        help="Also run live hardware diagnostics. Requires normal boot and BLE/WiFi.",
    )
    parser.add_argument(
        "--with-soak",
        action="store_true",
        help="Run auto transport heartbeat soak. Implies --with-hardware.",
    )
    parser.add_argument("--soak-count", type=int, default=30)
    parser.add_argument("--wifi-port", type=int, default=47392)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results.")
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Write machine-readable results to this JSON file.",
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        help="Write human-readable results to this Markdown file.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        help="Write release-check.json and release-check.md into this directory.",
    )
    args = parser.parse_args(argv)

    results: list[CheckResult] = []
    env = os.environ.copy()
    env["PYTHONPATH"] = "daemon/src"

    python = str(args.python)
    pio = str(args.pio)
    has_git = _is_git_repo()

    checks = [
        (
            "daemon-unittest",
            [python, "-m", "unittest", "discover", "-s", "daemon/tests"],
            PROJECT_ROOT,
            args.timeout,
            False,
        ),
        (
            "python-compileall",
            [python, "-m", "compileall", "daemon/src", "tools"],
            PROJECT_ROOT,
            args.timeout,
            False,
        ),
        (
            "pet-cli",
            [
                python,
                "-m",
                "codex_buddy.cli",
                "pet",
                "--pet-dir",
                "examples/pets/alice",
            ],
            PROJECT_ROOT,
            args.timeout,
            False,
        ),
        (
            "release-assets",
            [python, "tools/check_release_assets.py"],
            PROJECT_ROOT,
            args.timeout,
            False,
        ),
        (
            "firmware-keymap",
            [python, "tools/check_firmware_keymap.py"],
            PROJECT_ROOT,
            args.timeout,
            False,
        ),
        (
            "git-diff-check",
            ["git", "diff", "--check"],
            PROJECT_ROOT,
            args.timeout,
            not has_git,
        ),
        (
            "firmware-compile",
            [pio, "run", "-e", "cardputer-adv"],
            FIRMWARE_DIR,
            args.firmware_timeout,
            args.skip_firmware,
        ),
    ]

    for name, command, cwd, timeout, skipped in checks:
        results.append(
            _run_check(name, command, cwd=cwd, timeout=timeout, env=env, skipped=skipped)
        )

    run_hardware = args.with_hardware or args.with_soak
    results.append(
        _run_check(
            "hardware-doctor",
            [
                python,
                "-m",
                "codex_buddy.cli",
                "doctor",
                "--timeout",
                "8",
                "--wifi-port",
                str(args.wifi_port),
            ],
            cwd=PROJECT_ROOT,
            timeout=max(args.timeout, 20.0),
            env=env,
            skipped=not run_hardware,
        )
    )
    results.append(
        _run_check(
            "hardware-soak",
            [
                python,
                "-m",
                "codex_buddy.cli",
                "soak",
                "--transport",
                "auto",
                "--wifi-port",
                str(args.wifi_port),
                "--count",
                str(args.soak_count),
                "--json",
            ],
            cwd=PROJECT_ROOT,
            timeout=max(args.timeout, args.soak_count * 25.0),
            env=env,
            skipped=not args.with_soak,
        )
    )

    metadata = _report_metadata()
    if args.report_json:
        _write_report_json(args.report_json, results, metadata=metadata)
    if args.report_md:
        _write_report_md(args.report_md, results, metadata=metadata)
    if args.report_dir:
        _write_report_dir(args.report_dir, results, metadata=metadata)

    if args.json:
        _print_json(results, metadata=metadata)
    else:
        _print_text(results)

    return 0 if all(result.ok or result.skipped for result in results) else 1


def _run_check(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: dict[str, str],
    skipped: bool,
) -> CheckResult:
    start = time.monotonic()
    if skipped:
        return CheckResult(
            name=name,
            ok=True,
            skipped=True,
            elapsed_seconds=0.0,
            command=command,
            cwd=str(cwd),
            detail="skipped",
        )

    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return CheckResult(
            name=name,
            ok=False,
            skipped=False,
            elapsed_seconds=time.monotonic() - start,
            command=command,
            cwd=str(cwd),
            detail=f"missing executable: {exc.filename}",
        )
    except subprocess.TimeoutExpired as exc:
        return CheckResult(
            name=name,
            ok=False,
            skipped=False,
            elapsed_seconds=time.monotonic() - start,
            command=command,
            cwd=str(cwd),
            detail=f"timed out after {timeout:.0f}s\n{_tail(exc.output or '')}",
        )

    detail = _tail(completed.stdout)
    return CheckResult(
        name=name,
        ok=completed.returncode == 0,
        skipped=False,
        elapsed_seconds=time.monotonic() - start,
        command=command,
        cwd=str(cwd),
        detail=detail or f"exit {completed.returncode}",
    )


def _tail(text: str, *, limit: int = 4000) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[-limit:]


def _print_text(results: list[CheckResult]) -> None:
    print("Codex Buddy release check")
    print()
    for result in results:
        if result.skipped:
            status = "skip"
        else:
            status = "ok" if result.ok else "fail"
        print(f"[{status}] {result.name} ({result.elapsed_seconds:.1f}s)")
        if not result.ok:
            print(result.detail)
            print()
    failed = [result.name for result in results if not result.ok and not result.skipped]
    skipped = [result.name for result in results if result.skipped]
    print()
    print(f"summary: {'pass' if not failed else 'fail'}")
    if failed:
        print(f"failed: {', '.join(failed)}")
    if skipped:
        print(f"skipped: {', '.join(skipped)}")


def _print_json(
    results: list[CheckResult],
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    print(json.dumps(_results_payload(results, metadata=metadata), ensure_ascii=False, indent=2))


def _write_report_json(
    path: Path,
    results: list[CheckResult],
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    report_path = path.expanduser()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(_results_payload(results, metadata=metadata), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def _write_report_md(
    path: Path,
    results: list[CheckResult],
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    report_path = path.expanduser()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_results_markdown(results, metadata=metadata), encoding="utf-8")


def _write_report_dir(
    path: Path,
    results: list[CheckResult],
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    report_dir = path.expanduser()
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_report_json(report_dir / "release-check.json", results, metadata=metadata)
    _write_report_md(report_dir / "release-check.md", results, metadata=metadata)


def _results_payload(
    results: list[CheckResult],
    *,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    failed = [result.name for result in results if not result.ok and not result.skipped]
    skipped = [result.name for result in results if result.skipped]
    return {
        "metadata": metadata if metadata is not None else _report_metadata(),
        "summary": "pass" if not failed else "fail",
        "ok": not failed,
        "failed": failed,
        "skipped": skipped,
        "checks": [asdict(result) for result in results],
    }


def _report_metadata() -> dict[str, object]:
    status_short = _git_output(["git", "status", "--short"])
    status_lines = status_short.splitlines() if status_short else []
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(PROJECT_ROOT),
        "git": {
            "branch": _git_output(["git", "branch", "--show-current"]),
            "commit": _git_output(["git", "rev-parse", "--short", "HEAD"]),
            "dirty": bool(status_lines),
            "status_short": status_lines,
        },
    }


def _is_git_repo() -> bool:
    return bool(_git_output(["git", "rev-parse", "--is-inside-work-tree"]))


def _git_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _results_markdown(
    results: list[CheckResult],
    *,
    metadata: dict[str, object] | None = None,
) -> str:
    payload = _results_payload(results, metadata=metadata)
    metadata = payload["metadata"]
    git = metadata["git"]
    lines = [
        "# Codex Buddy Release Check",
        "",
        f"Generated: `{metadata['generated_at']}`",
        f"Project: `{metadata['project_root']}`",
        f"Git: `{git['branch'] or 'unknown'}` @ `{git['commit'] or 'unknown'}`",
        f"Dirty: `{'yes' if git['dirty'] else 'no'}`",
        "",
        f"Summary: **{payload['summary']}**",
        "",
    ]
    status_short = git["status_short"]
    if status_short:
        lines.extend(["## Git Dirty Files", ""])
        for item in status_short:
            lines.append(f"- `{item}`")
        lines.append("")

    lines.extend([
        "## Checks",
        "",
    ])
    for result in results:
        status = _markdown_status(result)
        elapsed = f"{result.elapsed_seconds:.1f}s"
        lines.append(f"- {status} `{result.name}` ({elapsed})")
        lines.append(f"  - cwd: `{result.cwd}`")
        lines.append(f"  - command: `{shlex.join(result.command)}`")
        if result.skipped:
            lines.append("  - detail: skipped")
        elif not result.ok:
            lines.append("  - detail:")
            lines.append("")
            lines.append("```text")
            lines.append(result.detail)
            lines.append("```")
        lines.append("")

    failed = payload["failed"]
    skipped = payload["skipped"]
    if failed:
        lines.append(f"Failed: {', '.join(f'`{name}`' for name in failed)}")
    if skipped:
        lines.append(f"Skipped: {', '.join(f'`{name}`' for name in skipped)}")
    lines.append("")
    return "\n".join(lines)


def _markdown_status(result: CheckResult) -> str:
    if result.skipped:
        return "[skip]"
    if result.ok:
        return "[ok]"
    return "[fail]"


if __name__ == "__main__":
    raise SystemExit(main())
