#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def main() -> int:
    candidates = sorted(Path("/dev").glob("cu.*"))
    if not candidates:
        print("No /dev/cu.* ports found.")
        return 1

    for path in candidates:
        print(path)

    usb_candidates = [
        path
        for path in candidates
        if any(token in path.name.lower() for token in ("usb", "wch", "slab", "modem"))
    ]
    if not usb_candidates:
        print()
        print("No obvious USB serial device found.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

