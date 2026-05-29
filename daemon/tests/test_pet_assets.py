from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from codex_buddy.pet_assets import load_pet_dir, load_selected_pet, validate_pet_asset


class PetAssetsTest(unittest.TestCase):
    def test_single_pet_is_used_when_no_selected_avatar_key_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            pet_dir = home / "pets" / "my-pet"
            pet_dir.mkdir(parents=True)
            (pet_dir / "pet.json").write_text(
                json.dumps(
                    {
                        "id": "my-pet",
                        "displayName": "My Pet",
                        "spritesheetPath": "spritesheet.webp",
                    }
                ),
                encoding="utf-8",
            )
            (pet_dir / "spritesheet.webp").write_bytes(b"")

            pet = load_selected_pet(home)

        self.assertIsNotNone(pet)
        self.assertEqual(pet.pet_id, "my-pet")
        self.assertEqual(pet.display_name, "My Pet")

    def test_pet_dir_validation_accepts_expected_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pet_dir = Path(tmp) / "custom-pet"
            pet_dir.mkdir(parents=True)
            (pet_dir / "pet.json").write_text(
                json.dumps(
                    {
                        "id": "custom-pet",
                        "displayName": "Custom Pet",
                        "spritesheetPath": "spritesheet.webp",
                    }
                ),
                encoding="utf-8",
            )
            (pet_dir / "spritesheet.webp").write_bytes(b"webp")

            with patch(
                "codex_buddy.pet_assets.probe_image_size",
                return_value=(1536, 1872),
            ):
                pet = load_pet_dir(pet_dir)

            self.assertIsNotNone(pet)
            self.assertEqual(validate_pet_asset(pet), [])

    def test_pet_dir_validation_reports_bad_id_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pet_dir = Path(tmp) / "bad"
            pet_dir.mkdir(parents=True)
            (pet_dir / "pet.json").write_text(
                json.dumps(
                    {
                        "id": "Bad Pet!",
                        "displayName": "Bad",
                        "spritesheetPath": "spritesheet.webp",
                    }
                ),
                encoding="utf-8",
            )
            (pet_dir / "spritesheet.webp").write_bytes(b"webp")

            with patch(
                "codex_buddy.pet_assets.probe_image_size",
                return_value=(100, 100),
            ):
                pet = load_pet_dir(pet_dir)

            self.assertIsNotNone(pet)
            problems = validate_pet_asset(pet)
            self.assertTrue(any("invalid pet id" in problem for problem in problems))
            self.assertTrue(any("unexpected spritesheet size" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
