# Firmware Release Files

This folder contains the ready-to-flash Alice firmware build.

Use this single file for normal users:

```text
codex-buddy-cardputer-adv-v0.3.27-ble-pair-merged.bin
```

It contains the bootloader, partition table, boot app, and firmware app in one
image and can be flashed at offset `0x0` with M5Burner or `esptool.py`.

This public release folder intentionally does not include an app-partition-only
binary, because that file is useful only for developer flashing workflows and
confuses normal users.

Checksums are in `SHA256SUMS.txt`.
