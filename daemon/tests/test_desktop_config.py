from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from codex_buddy.desktop_config import (
    BEGIN_MARKER,
    DesktopConfigError,
    DesktopHookOptions,
    build_desktop_config_block,
    build_desktop_hook_command,
    contains_unmanaged_permission_hook,
    desktop_config_status,
    install_managed_config_block,
    remove_managed_config_block,
    uninstall_managed_config_block,
)


class DesktopConfigTest(unittest.TestCase):
    def test_build_hook_command_uses_ble_socket(self) -> None:
        command = build_desktop_hook_command(
            DesktopHookOptions(
                codex_bin="codex",
                cwd=Path("/tmp/project"),
                python=Path("/tmp/project/.venv/bin/python"),
                daemon_src=Path("/tmp/project/daemon/src"),
                transport="ble-socket",
                ble_app=Path("/tmp/project/tools/CodexBuddyBridge.app"),
                ble_port=47391,
                ble_pair_code="123456",
            )
        )

        self.assertIn("PYTHONPATH=/tmp/project/daemon/src", command)
        self.assertIn("codex_buddy.cli approval-hook", command)
        self.assertIn("--transport ble-socket", command)
        self.assertIn("--approval-timeout 120", command)
        self.assertIn("--ble-port 47391", command)
        self.assertIn("--ble-device-name Codex-Buddy", command)
        self.assertIn("--ble-pair-code 123456", command)

    def test_build_hook_command_can_use_standalone_binary(self) -> None:
        command = build_desktop_hook_command(
            DesktopHookOptions(
                codex_bin="codex",
                cwd=Path("/tmp/project"),
                python=Path("/tmp/project/.venv/bin/python"),
                daemon_src=Path("/tmp/project/daemon/src"),
                transport="local-bridge",
                hook_binary=Path("/Applications/CodexBuddyMenu.app/Contents/Resources/codex-buddy-daemon"),
                bridge_port=47393,
            )
        )

        self.assertNotIn("PYTHONPATH=", command)
        self.assertIn("codex-buddy-daemon approval-hook", command)
        self.assertIn("--transport local-bridge", command)
        self.assertIn("--bridge-port 47393", command)

    def test_config_block_uses_dotted_hook_keys(self) -> None:
        block = build_desktop_config_block(
            hook_command="PYTHONPATH=/tmp/src python -m codex_buddy.cli approval-hook",
            timeout_sec=120,
            status_message="Waiting",
            trusted_key="hook-key",
            trusted_hash="abc123",
        )

        self.assertIn(BEGIN_MARKER, block)
        self.assertIn("[hooks]", block)
        self.assertIn("PermissionRequest", block)
        self.assertIn('[hooks.state."hook-key"]', block)
        self.assertIn('trusted_hash = "abc123"', block)

    def test_install_and_uninstall_managed_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text('model = "gpt-5.5"\n', encoding="utf-8")
            block = build_desktop_config_block(
                hook_command="cmd",
                timeout_sec=120,
                status_message="Waiting",
                trusted_key="key",
                trusted_hash="hash",
            )

            backup = install_managed_config_block(config, block)
            self.assertTrue(backup.exists())
            status = desktop_config_status(config)
            self.assertTrue(status["managed"])
            self.assertIn("model", config.read_text(encoding="utf-8"))

            changed, uninstall_backup = uninstall_managed_config_block(config)
            self.assertTrue(changed)
            self.assertIsNotNone(uninstall_backup)
            self.assertNotIn(BEGIN_MARKER, config.read_text(encoding="utf-8"))

    def test_install_refuses_unmanaged_permission_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text('hooks.PermissionRequest = []\n', encoding="utf-8")

            with self.assertRaises(DesktopConfigError):
                install_managed_config_block(config, "block\n")

    def test_unmanaged_hook_detection_ignores_managed_block(self) -> None:
        block = build_desktop_config_block(
            hook_command="cmd",
            timeout_sec=120,
            status_message="Waiting",
            trusted_key="key",
            trusted_hash="hash",
        )

        self.assertFalse(contains_unmanaged_permission_hook(remove_managed_config_block(block)))


if __name__ == "__main__":
    unittest.main()
