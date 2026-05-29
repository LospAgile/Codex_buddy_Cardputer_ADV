# Alice pet package

This directory contains the default Codex Buddy pet used by the open-source
firmware build.

Files:

- `pet.json`: Codex Desktop-compatible pet metadata.
- `spritesheet.webp`: `1536x1872` Codex Desktop-style 8 x 9 atlas.

To regenerate the firmware sprite arrays from this package:

```bash
python3 tools/generate_pet_sprite_asset.py \
  --spritesheet examples/pets/alice/spritesheet.webp \
  --label Alice \
  --contact-sheet tools/alice-firmware-contact-sheet.png
```

