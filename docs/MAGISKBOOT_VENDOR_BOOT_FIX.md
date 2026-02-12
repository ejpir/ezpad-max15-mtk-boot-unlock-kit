# MagiskBoot Vendor Boot Fix (Init 127)

This project hit a boot panic path where init exited with code `127`.
The reliable fix was rebuilding `vendor_boot_a` and stripping AVB/verify fs_mgr flags from first-stage fstab entries.

## Script

- `scripts/rebuild_vendor_boot_noavb_magiskboot.sh`

## Example

```bash
cd working_bundle_20260211
./scripts/rebuild_vendor_boot_noavb_magiskboot.sh \
  images/stock_restore/vendor_boot_a.bin \
  images/working/vendor_boot_a_noavb_fstab.bin
```

## What it does

1. Unpacks `vendor_boot` using `magiskboot`.
2. Extracts `ramdisk.cpio`.
3. Patches fstab candidates:
   - `first_stage_ramdisk/fstab.mt8781`
   - `first_stage_ramdisk/fstab.mt6789`
   - `first_stage_ramdisk/fstab.emmc`
   - `fstab.mt8781`
   - `system/etc/recovery.fstab`
4. Removes fs_mgr flags:
   - `avb`
   - `avb=*`
   - `avb_keys=*`
   - `verify`
   - `verify_*`
   - `verifyatboot*`
5. Re-packs with `magiskboot repack`.
6. Writes a patched fstab dump next to output image.

## Output

- Patched image: the output path you provide.
- Fstab dump: `<output_basename>.fstab_dump/`
- Byte hash may differ from the archived `images/working/vendor_boot_a_noavb_fstab.bin`
  due to repack differences, but fstab-level changes should match.

## Notes

- Set `MAGISKBOOT_BIN` if your `magiskboot` is not in PATH.
- Script refuses to repack if no fstab lines changed.
