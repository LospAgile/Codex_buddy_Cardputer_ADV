#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "daemon" / "src"))

from codex_buddy.pet_assets import load_pet_dir, validate_pet_asset


DEFAULT_CONTACT_SHEET = PROJECT_ROOT / "tools" / "alice-firmware-contact-sheet.png"
EXAMPLE_PET_DIR = PROJECT_ROOT / "examples" / "pets" / "alice"
LEGACY_RESTRICTED_CONTACT_SHEET = PROJECT_ROOT / "tools" / "kidq-firmware-contact-sheet.png"
SPRITE_SOURCE = PROJECT_ROOT / "firmware" / "src" / "CodexPetSprite.cpp"
SPRITE_HEADER = PROJECT_ROOT / "firmware" / "include" / "CodexPetSprite.h"
RESTRICTED_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg", ".gif", ".bin"}


def main() -> int:
    problems: list[str] = []

    if LEGACY_RESTRICTED_CONTACT_SHEET.exists():
        problems.append(
            "remove restricted legacy asset: "
            f"{LEGACY_RESTRICTED_CONTACT_SHEET.relative_to(PROJECT_ROOT)}"
        )

    if not DEFAULT_CONTACT_SHEET.exists():
        problems.append(f"missing Alice contact sheet: {DEFAULT_CONTACT_SHEET.relative_to(PROJECT_ROOT)}")

    validate_example_pet_package(problems)

    for path in (SPRITE_SOURCE, SPRITE_HEADER):
        if not path.exists():
            problems.append(f"missing generated sprite file: {path.relative_to(PROJECT_ROOT)}")
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:240]
        if "Repository default pet: Alice" not in head:
            problems.append(f"default sprite is not marked as Alice: {path.relative_to(PROJECT_ROOT)}")

    for tracked in tracked_files():
        lower = tracked.lower()
        if "kidq" in lower and Path(tracked).suffix.lower() in RESTRICTED_SUFFIXES:
            problems.append(f"restricted legacy binary still tracked: {tracked}")

    if problems:
        print("\n".join(problems))
        return 1

    print("release assets ok: default pet is Alice")
    return 0


def validate_example_pet_package(problems: list[str]) -> None:
    asset = load_pet_dir(EXAMPLE_PET_DIR)
    if asset is None:
        problems.append(f"missing example pet package: {EXAMPLE_PET_DIR.relative_to(PROJECT_ROOT)}")
        return

    if asset.pet_id != "alice":
        problems.append(f"unexpected example pet id: {asset.pet_id}")
    if asset.display_name != "Alice":
        problems.append(f"unexpected example pet displayName: {asset.display_name}")
    for problem in validate_pet_asset(asset):
        problems.append(f"invalid example pet package: {problem}")


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
