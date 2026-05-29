# Release Checklist

This checklist separates local automation from checks that still need the real
M5 Cardputer ADV in normal boot.

## Local Gate

Run this before a merge or release candidate:

```bash
cd /path/to/Codex_buddy_Cardputer_ADV_Alice
./.venv/bin/python tools/release_check.py
```

The default gate covers:

- daemon unit tests.
- Python compile checks for `daemon/src` and `tools`.
- selected pet metadata validation through `codex-buddy pet`.
- release asset boundary check through `tools/check_release_assets.py`, including
  the redistributable example pet package.
- host-side firmware keymap check through `tools/check_firmware_keymap.py`,
  including Cardputer ADV `Fn+,` / `Fn+/` left-right actions.
- `git diff --check`.
- PlatformIO firmware compile for `cardputer-adv`.

For machine-readable output:

```bash
./.venv/bin/python tools/release_check.py --json
```

For a terminal summary plus an auditable JSON file:

```bash
./.venv/bin/python tools/release_check.py --report-json /tmp/codex-buddy-release-check.json
```

For a human-readable Markdown release note:

```bash
./.venv/bin/python tools/release_check.py --report-md /tmp/codex-buddy-release-check.md
```

For both JSON and Markdown from one run:

```bash
./.venv/bin/python tools/release_check.py --report-dir /tmp/codex-buddy-release-check
```

Generated JSON and Markdown reports include the UTC timestamp, project root,
Git branch, short commit, and `git status --short` dirty files.

If the firmware build is already covered elsewhere:

```bash
./.venv/bin/python tools/release_check.py --skip-firmware
```

## Artifact Packaging

Build the release artifacts locally before attaching files to a GitHub Release:

```bash
tools/package_firmware_release.sh
tools/package_menu_bar_app.sh
```

Expected outputs:

- `dist/release/firmware/codex-buddy-cardputer-adv-v<firmware-version>-merged.bin`
- `dist/release/apps/CodexBuddyMenu-v<version>-macos-<arch>.zip`
- `SHA256SUMS.txt` and JSON manifests in both release directories

The menu bar app zip includes the bundled `CodexBuddyBridge.app`, standalone
`codex-buddy-daemon`, and daemon source. Normal Mac users do not need to find or
launch the BLE bridge helper manually, and the app / Desktop hook can use the
embedded daemon helper without requiring a local Python environment.

Current public preview builds are ad-hoc signed and not notarized. Release
notes and README must tell users to clear macOS quarantine after unzipping:

```bash
unzip CodexBuddyMenu-v0.1.0-macos-arm64.zip
xattr -dr com.apple.quarantine CodexBuddyMenu.app
open CodexBuddyMenu.app
```

GitHub Actions can build the same bundle from `.github/workflows/release-artifacts.yml`
on manual dispatch or `v*` tag pushes. Tag builds also attach the generated
firmware and app files to the GitHub Release. The first public macOS release can
use the ad-hoc signed zip, but a polished release still needs Developer ID
signing and notarization.

## Hardware Gate

Run these only when the device is in normal boot, not download mode:

```bash
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli doctor --timeout 8 --json
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli soak --transport auto --count 30
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli soak --transport auto --count 30 --json
PYTHONPATH=daemon/src ./.venv/bin/python -m codex_buddy.cli approval-demo \
  --transport auto \
  --id release-smoke-approval
```

Keep the JSON soak output when you need an auditable latency record for release notes.

The same checks can be invoked through the release helper:

```bash
./.venv/bin/python tools/release_check.py --with-hardware --with-soak
./.venv/bin/python tools/release_check.py --with-hardware --with-soak \
  --report-json /tmp/codex-buddy-hardware-release-check.json
./.venv/bin/python tools/release_check.py --with-hardware --with-soak \
  --report-md /tmp/codex-buddy-hardware-release-check.md
./.venv/bin/python tools/release_check.py --with-hardware --with-soak \
  --report-dir /tmp/codex-buddy-hardware-release-check
```

Hardware acceptance still needs visual confirmation for:

- BLE and WiFi approval cards.
- Sleep and IMU wake behavior.
- long Chinese approval hints.
- Settings, WiFi, Device, Help, and Sleep pages.
- screenshots or demo video for public release notes.

## Public Release Notes

- Public release firmware currently defaults to `Alice`; keep the attribution and
  licensing note with the release and preserve `Codex Placeholder` as the
  redistribution-safe fallback pet.
- Public example pet packages live under `examples/pets/alice/` and
  `examples/pets/codex-placeholder/`; both must validate as normal
  `1536x1872` Codex Desktop-compatible packages.
- macOS LaunchAgent is optional and must never be installed automatically. The
  menu bar app can toggle launch at login only after the user explicitly chooses
  it.
- The current macOS app zip is ad-hoc signed. A polished public release should
  add Developer ID signing and notarization.
