# Working Playbook

This playbook is the operational path used to bypass AVB and enable custom ROM boot
(target use case: LineageOS 23.x on EZpad Max15).

Base tooling upstream: https://github.com/bkerler/mtkclient

## 0) Rebuild `vendor_boot_a` with MagiskBoot (127 Fix Reproducer)

Use this when you want to regenerate the known `vendor_boot` fix from stock input.

```bash
cd working_bundle_20260211
./scripts/rebuild_vendor_boot_noavb_magiskboot.sh \
  images/stock_restore/vendor_boot_a.bin \
  images/working/vendor_boot_a_noavb_fstab.bin
```

This strips `avb` / `verify*` fs_mgr flags from first-stage fstab entries and repacks with `magiskboot`.
The patched fstab copies are saved under:

- `images/working/vendor_boot_a_noavb_fstab.fstab_dump/`

## 1) Flash Known-Good Boot Chain

Prereq: device in BROM/DA mode for `mtk.py` writes.

```bash
python3 mtk.py w lk_a images/working/lk_a_patched_v16_force_orange_allselectors_selinux_skiprestore.img --preloader mtkclient/Loader/MTK_DA_V6.bin
python3 mtk.py w lk_b images/working/lk_b_patched_v16_force_orange_allselectors_selinux_skiprestore_from_lka.img --preloader mtkclient/Loader/MTK_DA_V6.bin
python3 mtk.py w vbmeta_a images/working/vbmeta_a_custom_v2.img --preloader mtkclient/Loader/MTK_DA_V6.bin
python3 mtk.py w vendor_boot_a images/working/vendor_boot_a_noavb_fstab.bin --preloader mtkclient/Loader/MTK_DA_V6.bin
```

## 2) Flash Rooted Boot (Magisk)

Prereq: fastboot mode.

```bash
"/Users/nick/Downloads/platform-tools 3/fastboot" getvar current-slot
```

If slot is `a`:

```bash
"/Users/nick/Downloads/platform-tools 3/fastboot" flash boot_a images/working/magisk_patched-30600_dlNzO.img
```

If slot is `b`:

```bash
"/Users/nick/Downloads/platform-tools 3/fastboot" flash boot_b images/working/magisk_patched-30600_dlNzO.img
```

Then reboot and verify:

```bash
"/Users/nick/Downloads/platform-tools 3/fastboot" reboot
"/Users/nick/Downloads/platform-tools 3/adb" shell su -c id
```

Expected: `uid=0(root)`.

## 3) Roll Back to Stock (Core Partitions)

```bash
python3 mtk.py w lk_a images/stock_restore/lk_a.bin --preloader mtkclient/Loader/MTK_DA_V6.bin
python3 mtk.py w lk_b images/stock_restore/lk_b.bin --preloader mtkclient/Loader/MTK_DA_V6.bin
python3 mtk.py w vbmeta_a images/stock_restore/vbmeta_a.bin --preloader mtkclient/Loader/MTK_DA_V6.bin
python3 mtk.py w vendor_boot_a images/stock_restore/vendor_boot_a.bin --preloader mtkclient/Loader/MTK_DA_V6.bin
```

For boot rollback in fastboot:

```bash
"/Users/nick/Downloads/platform-tools 3/fastboot" flash boot_a images/stock_restore/boot_a.bin
"/Users/nick/Downloads/platform-tools 3/fastboot" flash boot_b images/stock_restore/boot_b.bin
```

## 4) Safety Rule

Never flash unrelated images into `boot_*` (example: `otp.bin` into `boot_b`) unless intentionally doing a write-path test and immediately restoring.
