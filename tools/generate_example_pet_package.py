#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from generate_pet_sprite_asset import (
    ATLAS_COLUMNS,
    ATLAS_ROWS,
    CELL_HEIGHT,
    CELL_WIDTH,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    Image,
    ROWS,
    generate_placeholder_frames,
    swap565_to_rgba,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "examples" / "pets" / "codex-placeholder"
PET_ID = "codex-placeholder"
DISPLAY_NAME = "Codex Placeholder"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the redistributable Codex Placeholder pet package.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Directory that will receive pet.json, spritesheet.webp, and README.md.",
    )
    args = parser.parse_args(argv)

    if Image is None:
        raise SystemExit(
            "Pillow is required to generate the example pet package. "
            "Install it with: python3 -m pip install Pillow"
        )

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    write_manifest(output / "pet.json")
    write_spritesheet(output / "spritesheet.webp")
    write_readme(output / "README.md")
    print(f"generated example pet package: {output}")
    return 0


def write_manifest(path: Path) -> None:
    manifest = {
        "id": PET_ID,
        "displayName": DISPLAY_NAME,
        "spritesheetPath": "spritesheet.webp",
    }
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_spritesheet(path: Path) -> None:
    frames, sequences = generate_placeholder_frames()
    atlas = Image.new(
        "RGBA",
        (CELL_WIDTH * ATLAS_COLUMNS, CELL_HEIGHT * ATLAS_ROWS),
        (0, 0, 0, 0),
    )

    for row_spec in ROWS:
        sequence = sequences[row_spec.name]
        for column, frame_index in enumerate(sequence):
            frame_image = Image.new("RGBA", (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0, 0))
            frame_image.putdata([swap565_to_rgba(value) for value in frames[frame_index]])
            x = column * CELL_WIDTH + (CELL_WIDTH - FRAME_WIDTH) // 2
            y = row_spec.row * CELL_HEIGHT + (CELL_HEIGHT - FRAME_HEIGHT) // 2
            atlas.alpha_composite(frame_image, (x, y))

    atlas.save(path, "WEBP", lossless=True, quality=100, method=6)


def write_readme(path: Path) -> None:
    path.write_text(
        """# Codex Placeholder Example Pet

This is the redistributable example pet package for Codex Buddy.

Files:

- `pet.json`: Codex Desktop-compatible manifest.
- `spritesheet.webp`: 1536x1872 atlas with the same 8x9 layout documented in `docs/pets.md`.

Validate it from the repository root:

```bash
PYTHONPATH=daemon/src python3 -m codex_buddy.cli pet \\
  --pet-dir examples/pets/codex-placeholder \\
  --json
```

Regenerate the package from the repository root:

```bash
python3 tools/generate_example_pet_package.py
```
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
