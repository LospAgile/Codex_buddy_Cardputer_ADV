# Codex Placeholder Example Pet

This is the redistributable example pet package for Codex Buddy.

Files:

- `pet.json`: Codex Desktop-compatible manifest.
- `spritesheet.webp`: 1536x1872 atlas with the same 8x9 layout documented in `docs/pets.md`.

Validate it from the repository root:

```bash
PYTHONPATH=daemon/src python3 -m codex_buddy.cli pet \
  --pet-dir examples/pets/codex-placeholder \
  --json
```

Regenerate the package from the repository root:

```bash
python3 tools/generate_example_pet_package.py
```
