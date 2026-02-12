#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  rebuild_vendor_boot_noavb_magiskboot.sh <input_vendor_boot.img> <output_vendor_boot.img>

Purpose:
  Rebuild vendor_boot with MagiskBoot while stripping AVB/verify fs_mgr flags from
  first-stage fstab entries. This is the reproducible fix path used to clear the
  init exit-127 boot failure in this project.

Env:
  MAGISKBOOT_BIN  Optional explicit path to magiskboot.
                  If unset, script tries:
                  1) /Users/nick/Downloads/magiskboot
                  2) magiskboot from PATH
USAGE
}

if [[ $# -ne 2 ]]; then
  usage
  exit 1
fi

IN_IMG="$1"
OUT_IMG="$2"

if [[ ! -f "$IN_IMG" ]]; then
  echo "Input image not found: $IN_IMG" >&2
  exit 1
fi

find_magiskboot() {
  if [[ -n "${MAGISKBOOT_BIN:-}" && -x "${MAGISKBOOT_BIN}" ]]; then
    echo "${MAGISKBOOT_BIN}"
    return 0
  fi
  if [[ -x "/Users/nick/Downloads/magiskboot" ]]; then
    echo "/Users/nick/Downloads/magiskboot"
    return 0
  fi
  if command -v magiskboot >/dev/null 2>&1; then
    command -v magiskboot
    return 0
  fi
  return 1
}

MAGISKBOOT="$(find_magiskboot || true)"
if [[ -z "${MAGISKBOOT}" ]]; then
  echo "magiskboot not found. Set MAGISKBOOT_BIN or install magiskboot." >&2
  exit 1
fi

TMPDIR_WORK="$(mktemp -d "${TMPDIR:-/tmp}/vb-noavb-magiskboot.XXXXXX")"
cleanup() {
  rm -rf "${TMPDIR_WORK}"
}
trap cleanup EXIT

IN_ABS="$(cd "$(dirname "$IN_IMG")" && pwd)/$(basename "$IN_IMG")"
OUT_ABS="$(cd "$(dirname "$OUT_IMG")" && pwd)/$(basename "$OUT_IMG")"
OUT_DUMP="${OUT_ABS%.*}.fstab_dump"

mkdir -p "$(dirname "$OUT_ABS")"
rm -rf "$OUT_DUMP"
mkdir -p "$OUT_DUMP"

cp -f "$IN_ABS" "$TMPDIR_WORK/orig.img"

pushd "$TMPDIR_WORK" >/dev/null

"$MAGISKBOOT" unpack orig.img >/dev/null 2>&1
if [[ ! -f ramdisk.cpio ]]; then
  echo "magiskboot unpack did not produce ramdisk.cpio. Is this a valid vendor_boot?" >&2
  exit 1
fi

# vendor_boot ramdisk may still be compressed after unpack; normalize to plain cpio.
if "$MAGISKBOOT" decompress ramdisk.cpio ramdisk.dec >/dev/null 2>&1; then
  RAMDISK_WORK="ramdisk.dec"
else
  cp -f ramdisk.cpio ramdisk.dec
  RAMDISK_WORK="ramdisk.dec"
fi

"$MAGISKBOOT" cpio "$RAMDISK_WORK" "extract" >/dev/null 2>&1

mapfile -t FSTABS <<'EOF'
first_stage_ramdisk/fstab.mt8781
first_stage_ramdisk/fstab.mt6789
first_stage_ramdisk/fstab.emmc
fstab.mt8781
system/etc/recovery.fstab
EOF

changed_total=0

patch_fstab() {
  local in_file="$1"
  local out_file="$2"
  python3 - "$in_file" "$out_file" <<'PY'
import sys
from pathlib import Path

src = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore").splitlines()
out = []
changed = 0

def strip_flags(flags: str) -> str:
    keep = []
    for raw in flags.split(","):
        f = raw.strip()
        if not f:
            continue
        if f == "avb" or f.startswith("avb=") or f.startswith("avb_keys="):
            continue
        if f == "verify" or f.startswith("verify_") or f.startswith("verifyatboot"):
            continue
        keep.append(f)
    return ",".join(keep)

for line in src:
    s = line.strip()
    if not s or s.startswith("#"):
        out.append(line)
        continue
    parts = line.split()
    if len(parts) < 5:
        out.append(line)
        continue
    old = parts[4]
    new = strip_flags(old)
    if new != old:
        parts[4] = new
        line = " ".join(parts)
        changed += 1
    out.append(line)

Path(sys.argv[2]).write_text("\n".join(out) + "\n", encoding="utf-8")
print(changed)
PY
}

for rel in "${FSTABS[@]}"; do
  if [[ -f "$rel" ]]; then
    patched="$TMPDIR_WORK/$(echo "$rel" | tr '/' '_').patched"
    count="$(patch_fstab "$rel" "$patched")"
    if [[ "$count" -gt 0 ]]; then
      "$MAGISKBOOT" cpio "$RAMDISK_WORK" "add 0644 $rel $patched" >/dev/null 2>&1
      cp -f "$patched" "$OUT_DUMP/$(echo "$rel" | tr '/' '__')"
      changed_total=$((changed_total + count))
      echo "patched $rel: $count line(s)"
    fi
  fi
done

if [[ "$changed_total" -le 0 ]]; then
  echo "No AVB/verify flags removed from fstab files. Refusing to repack." >&2
  exit 1
fi

# Repack with compressed ramdisk to preserve expected vendor_boot size/format.
if ! "$MAGISKBOOT" compress=lz4_legacy "$RAMDISK_WORK" ramdisk.cpio >/dev/null 2>&1; then
  "$MAGISKBOOT" compress=lz4 "$RAMDISK_WORK" ramdisk.cpio >/dev/null 2>&1
fi

"$MAGISKBOOT" repack orig.img >/dev/null 2>&1

if [[ ! -f new-boot.img ]]; then
  echo "magiskboot repack did not produce new-boot.img" >&2
  exit 1
fi

cp -f new-boot.img "$OUT_ABS"
popd >/dev/null

echo "Wrote: $OUT_ABS"
echo "Fstab dump: $OUT_DUMP"
echo "Lines changed: $changed_total"
