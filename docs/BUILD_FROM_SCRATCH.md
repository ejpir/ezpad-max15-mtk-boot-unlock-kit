# Build Images From Scratch (Script Path)

Use this if you do not want to consume prebuilt images from `images/working/`.
These steps rebuild the required images from stock inputs using bundle scripts.

## Prerequisites

- `python3`
- `openssl` (for vbmeta signing)
- `lz4`
- `bsdtar`

Run from bundle root:

```bash
cd working_bundle_20260211
mkdir -p .tmp_build
```

## 1) Rebuild `vbmeta_a` (stock descriptors + custom key + flags=3)

```bash
python3 scripts/rebuild_vbmeta_from_stock.py \
  --stock images/stock_restore/vbmeta_a.bin \
  --custom images/working/vbmeta_a_custom_v2.img \
  --key scripts/custom_avb.pem \
  --output .tmp_build/vbmeta_a_custom_v2_rebuilt_from_stock.img \
  --flags 3
```

Expected SHA256:

- `a2faa69afc4ffe4223a666f97bd2880847d452eccbc06f3ca2699ceb9ee4a195`

## 2) Rebuild patched `lk_a` from stock + rebuilt vbmeta key material

```bash
python3 scripts/patch_lk_v16_imgauth_allcopies_force_orange_allselectors_selinux_skiprestore.py \
  images/stock_restore/lk_a.bin \
  .tmp_build/vbmeta_a_custom_v2_rebuilt_from_stock.img \
  .tmp_build/lk_a_v16_rebuilt.img
```

Expected SHA256:

- `aa428a7dc00c710c0736b2b559e2e0b02161c10487a03bb1c3bf0a6c5c099846`

Flash the same LK payload to both slots:

```bash
python3 mtk.py w lk_a .tmp_build/lk_a_v16_rebuilt.img --preloader mtkclient/Loader/MTK_DA_V6.bin
python3 mtk.py w lk_b .tmp_build/lk_a_v16_rebuilt.img --preloader mtkclient/Loader/MTK_DA_V6.bin
```

## 3) Rebuild patched `vendor_boot_a` (remove AVB/verify fstab flags)

Python path:

```bash
python3 scripts/patch_vendor_boot_strip_fstab_avb.py \
  --input images/stock_restore/vendor_boot_a.bin \
  --output .tmp_build/vendor_boot_a_noavb_rebuilt.bin
```

This also creates:

- `.tmp_build/vendor_boot_a_noavb_rebuilt.fstab_dump/`

Check that AVB/verify flags are stripped:

```bash
rg -n "avb|verify" .tmp_build/vendor_boot_a_noavb_rebuilt.fstab_dump || true
```

Notes:

- Rebuilt `vendor_boot` hash can differ from archived `images/working/vendor_boot_a_noavb_fstab.bin`.
- Functional equivalence is based on patched fstab content and successful boot behavior.

## 4) Flash rebuilt artifacts

```bash
python3 mtk.py w vbmeta_a .tmp_build/vbmeta_a_custom_v2_rebuilt_from_stock.img --preloader mtkclient/Loader/MTK_DA_V6.bin
python3 mtk.py w vendor_boot_a .tmp_build/vendor_boot_a_noavb_rebuilt.bin --preloader mtkclient/Loader/MTK_DA_V6.bin
```

Then flash rooted `boot` per:

- `docs/WORKING_PLAYBOOK.md`

## 5) Optional MagiskBoot-based vendor_boot rebuild

If you prefer the magiskboot workflow:

```bash
./scripts/rebuild_vendor_boot_noavb_magiskboot.sh \
  images/stock_restore/vendor_boot_a.bin \
  .tmp_build/vendor_boot_a_noavb_rebuilt_magiskboot.bin
```

See:

- `docs/MAGISKBOOT_VENDOR_BOOT_FIX.md`
