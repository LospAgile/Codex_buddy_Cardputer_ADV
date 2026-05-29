from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from .protocol import PetInfo
from .session_tailer import default_codex_home


EXPECTED_SPRITESHEET_SIZE = (1536, 1872)
PET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


@dataclass(frozen=True)
class PetAsset:
    pet_id: str
    display_name: str
    spritesheet: Path
    size: tuple[int, int] | None = None

    def to_protocol(self) -> PetInfo:
        return PetInfo(pet_id=self.pet_id, display_name=self.display_name)


def selected_avatar_id(codex_home: Path | None = None) -> str | None:
    home = codex_home or default_codex_home()
    state_path = home / ".codex-global-state.json"
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    value = data.get("selected-avatar-id")
    return value if isinstance(value, str) else None


def load_selected_pet(codex_home: Path | None = None) -> PetAsset | None:
    home = codex_home or default_codex_home()
    avatar_id = selected_avatar_id(home)
    if not avatar_id or not avatar_id.startswith("custom:"):
        return load_only_custom_pet(home)
    return load_pet(avatar_id.removeprefix("custom:"), home)


def load_only_custom_pet(codex_home: Path | None = None) -> PetAsset | None:
    home = codex_home or default_codex_home()
    pets_dir = home / "pets"
    if not pets_dir.exists():
        return None

    manifests = sorted(pets_dir.glob("*/pet.json"))
    if len(manifests) != 1:
        return None
    return load_pet(manifests[0].parent.name, home)


def load_pet(pet_id: str, codex_home: Path | None = None) -> PetAsset | None:
    home = codex_home or default_codex_home()
    pet_dir = home / "pets" / pet_id
    return load_pet_dir(pet_dir, fallback_id=pet_id)


def load_pet_dir(pet_dir: Path, fallback_id: str | None = None) -> PetAsset | None:
    manifest_path = pet_dir / "pet.json"
    if not manifest_path.exists():
        return None

    data = _read_json(manifest_path)
    if not data:
        return None

    spritesheet_name = data.get("spritesheetPath") or "spritesheet.webp"
    spritesheet = pet_dir / str(spritesheet_name)
    return PetAsset(
        pet_id=str(data.get("id") or fallback_id or pet_dir.name),
        display_name=str(data.get("displayName") or fallback_id or pet_dir.name),
        spritesheet=spritesheet,
        size=probe_image_size(spritesheet),
    )


def validate_pet_asset(asset: PetAsset) -> list[str]:
    problems: list[str] = []
    if not PET_ID_RE.fullmatch(asset.pet_id):
        problems.append(
            "invalid pet id: use lowercase letters, numbers, and hyphens, "
            "starting with a letter or number"
        )
    if not asset.display_name.strip():
        problems.append("displayName is empty")
    if not asset.spritesheet.exists():
        problems.append(f"spritesheet not found: {asset.spritesheet}")
    elif asset.size is None:
        problems.append(f"cannot read spritesheet size: {asset.spritesheet}")
    elif asset.size != EXPECTED_SPRITESHEET_SIZE:
        problems.append(
            "unexpected spritesheet size: "
            f"{asset.size[0]}x{asset.size[1]}, expected "
            f"{EXPECTED_SPRITESHEET_SIZE[0]}x{EXPECTED_SPRITESHEET_SIZE[1]}"
        )
    return problems


def probe_image_size(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    try:
        result = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    width: int | None = None
    height: int | None = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("pixelWidth:"):
            width = int(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("pixelHeight:"):
            height = int(stripped.split(":", 1)[1].strip())
    if width is None or height is None:
        return None
    return (width, height)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
