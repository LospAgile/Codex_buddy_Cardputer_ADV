#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one Codex Buddy heartbeat over serial.")
    parser.add_argument("--port", type=Path, required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    try:
      import serial  # type: ignore[import-not-found]
    except ImportError:
      print("pyserial is required in the active Python environment.", file=sys.stderr)
      return 2

    from codex_buddy.pet_assets import load_selected_pet
    from codex_buddy.session_tailer import snapshot_latest_session

    snapshot = snapshot_latest_session()
    pet = load_selected_pet()
    line = snapshot.to_heartbeat(pet.to_protocol() if pet else None).to_line()

    with serial.Serial(str(args.port), args.baud, timeout=0.2) as conn:
        conn.dtr = False
        conn.rts = False
        time.sleep(2.5)
        conn.reset_input_buffer()

        deadline = time.monotonic() + args.timeout
        next_send = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                conn.write(line.encode("utf-8"))
                conn.flush()
                next_send = now + 1.0

            response = conn.readline().decode("utf-8", errors="replace").strip()
            if response:
                print(response)
                if '"type":"device_status"' in response:
                    return 0

    print("No device_status ack received.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
