# Jumper EZpad Max15 Working OEM unlock Bundle (2026-02-11)

Known-good bring-up bundle for `EZpad_Max15` (`MT8781/MT6789`).
This is the curated set of images, scripts, and docs that produced a booting system with root.

Primary objective: make it possible to boot custom ROMs (including LineageOS 23.x)
by bypassing AVB enforcement in the LK/vbmeta/vendor_boot boot chain.

## Upstream Base

This work is built on top of the original `mtkclient` project:

- https://github.com/bkerler/mtkclient

## Status Snapshot

Validated on Wednesday, February 11, 2026:

- Android boots with:
  - patched `lk_a`/`lk_b`
  - custom `vbmeta_a`
  - patched `vendor_boot_a` (fstab AVB/verify flags stripped)
- Root works:
  - `adb shell su -c id` returned `uid=0(root)` and `context=u:r:magisk:s0`
- Runtime boot state observed:
  - `ro.boot.flash.locked=0`
  - `ro.boot.verifiedbootstate=orange`
  - fastboot reported `unlocked:yes`

## What This Bundle Solves

- Reproducible fix path for the boot panic path where init exited with `127`
- Reproducible root path using a known Magisk-patched `boot` image
- AVB bypass flow required to boot custom ROM stacks such as LineageOS 23.x
- Safe rollback to stock core partitions

## Technical Patch Matrix

- `lk_a` / `lk_b` (`v16` baseline):
  - Replaces embedded AVB public key with custom vbmeta key material.
  - NOPs duplicated image-auth failure branches (`Image Auth Fail` path) so LK does not halt there.
  - Forces verified-boot state selector to orange path.
  - Rewrites selected LK cmdline literals to `androidboot.selinux=permissive`.
  - Skips one lock-restore callsite in `boot_linux_fdt` (`0xC59C`).
  - Purpose: keep early boot chain permissive enough for custom vbmeta and custom-ROM bring-up.
- `vbmeta_a_custom_v2.img`:
  - Keeps stock descriptor structure (not empty vbmeta).
  - Uses custom AVB key and flags (`flags=3`).
  - Purpose: satisfy boot chain expectations while allowing non-stock trust configuration.
- `vendor_boot_a_noavb_fstab.bin`:
  - First-stage fstab entries are patched to remove `avb`/`avb=*`/`verify*` fs_mgr flags.
  - Purpose: avoid first-stage mount/exec path failures that produced init exit `127`.
- `boot_*` (Magisk-patched image):
  - Provides runtime root (`su`) on top of the working boot chain.
  - Purpose: debugging, device bring-up, and custom ROM post-boot operations.
- Stock partitions intentionally left stock in this flow:
  - `super`, `vbmeta_system_a`, `vbmeta_vendor_a`, `boot_a` content base (before Magisk patch), `dtbo_a`, `init_boot_a`.
  - Purpose: minimize moving parts and isolate changes to AVB/boot-chain gating.

## Prerequisites

- `python3`
- `mtk.py` from this repo
- `fastboot` and `adb`
- `magiskboot` (for rebuilding vendor boot from stock)
- Device access to:
  - BROM/DA mode for `mtk.py w ...`
  - fastboot mode for `fastboot flash ...`

## Bundle Layout

- `images/working/`
  - known-good images used in successful boot/root flow
- `images/stock_restore/`
  - stock backups for rollback
- `images/experimental/`
  - experimental LK lockstate patch set (`v18`), not baseline
- `scripts/`
  - patch/rebuild scripts and helper tooling
- `docs/`
  - focused playbooks and forensic notes
- `manifests/`
  - `SHA256SUMS.txt` and `FILE_SIZES.tsv`

## Integrity Verification

```bash
cd working_bundle_20260211
./scripts/verify_bundle.sh
```

Equivalent direct check:

```bash
shasum -a 256 -c manifests/SHA256SUMS.txt
```

## Fast Start

Use these in order:

1. Apply known-good images:
  - `docs/WORKING_PLAYBOOK.md` (section: flash known-good boot chain)
2. Flash rooted boot image (active slot):
  - `docs/WORKING_PLAYBOOK.md` (section: flash rooted boot)
3. Validate root:
  - `adb shell su -c id`

If you prefer generating images instead of using prebuilt files:

- `docs/BUILD_FROM_SCRATCH.md`

## Rebuilding the Vendor Boot 127 Fix

This bundle includes a direct MagiskBoot reproducer:

- Script: `scripts/rebuild_vendor_boot_noavb_magiskboot.sh`
- Full details: `docs/MAGISKBOOT_VENDOR_BOOT_FIX.md`

Example:

```bash
cd working_bundle_20260211
./scripts/rebuild_vendor_boot_noavb_magiskboot.sh \
  images/stock_restore/vendor_boot_a.bin \
  images/working/vendor_boot_a_noavb_fstab.bin
```

## Rollback

Rollback commands are documented in:

- `docs/WORKING_PLAYBOOK.md` (stock restore section)

At minimum, restore:

- `images/stock_restore/lk_a.bin`
- `images/stock_restore/lk_b.bin`
- `images/stock_restore/vbmeta_a.bin`
- `images/stock_restore/vendor_boot_a.bin`
- `images/stock_restore/boot_a.bin`
- `images/stock_restore/boot_b.bin`

## Known Caveats

- Persistent `seccfg` behavior:
  - `seccfg` readback remained `lock_state=0x4` (stock-locked) in this session
  - runtime orange/unlocked indicators came from boot-chain behavior
  - details: `docs/SECCFG_NOTES.md`
- `v16` vs `v18`:
  - `v18` is `v16` plus additional lock-state-force patches
  - in testing, persistent lock state still resets to locked (likely secure-world/TEE re-assertion)
  - therefore `v18` is kept experimental; `v16` remains baseline
  - this does not prevent fastbootd-based flashing workflows used for custom-ROM setup
- `lk_a` vs `lk_b`:
  - for normal boot while active slot is `a`, patching `lk_a` is sufficient
  - patching `lk_b` is still recommended for slot-switch/OTA safety
- `init_boot_a/bin` backups here are zero-filled placeholders on this device.
  - patch `boot_*` for Magisk root, not `init_boot_*`
- Never flash unrelated images into `boot_*` unless intentionally testing write path.

## Recommended Operational Safety

- Verify `current-slot` before flashing slot-specific partitions.
- Keep a full backup of all stock images before trying experimental patches.
- Re-run `./scripts/verify_bundle.sh` after moving/copying the bundle.
