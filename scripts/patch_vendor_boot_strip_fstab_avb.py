#!/usr/bin/env python3
import argparse
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path


def align(value: int, page_size: int) -> int:
    return (value + page_size - 1) & ~(page_size - 1)


def run(cmd, cwd=None):
    subprocess.run(cmd, check=True, cwd=cwd)


def parse_vendor_boot(img: bytes):
    if img[:8] != b"VNDRBOOT":
        raise ValueError("Not a vendor_boot image (missing VNDRBOOT magic)")

    off = 8
    header_version, page_size, kernel_addr, ramdisk_addr, vendor_ramdisk_size = struct.unpack_from(
        "<5I", img, off
    )
    off += 20
    cmdline = img[off:off + 2048]
    off += 2048
    tags_addr = struct.unpack_from("<I", img, off)[0]
    off += 4
    name = img[off:off + 16]
    off += 16
    header_size = struct.unpack_from("<I", img, off)[0]
    off += 4
    dtb_size = struct.unpack_from("<I", img, off)[0]
    off += 4
    dtb_addr = struct.unpack_from("<Q", img, off)[0]
    off += 8
    vendor_ramdisk_table_size, vendor_ramdisk_table_entry_num, vendor_ramdisk_table_entry_size, bootconfig_size = struct.unpack_from(
        "<4I", img, off
    )

    if header_version < 3:
        raise ValueError(f"Unsupported vendor_boot header version {header_version}")

    header_area_size = align(header_size, page_size)
    ramdisk_off = header_area_size
    dtb_off = ramdisk_off + align(vendor_ramdisk_size, page_size)
    table_off = dtb_off + align(dtb_size, page_size)
    bootconfig_off = table_off + align(vendor_ramdisk_table_size, page_size)

    return {
        "header_version": header_version,
        "page_size": page_size,
        "vendor_ramdisk_size": vendor_ramdisk_size,
        "header_size": header_size,
        "header_area_size": header_area_size,
        "dtb_size": dtb_size,
        "vendor_ramdisk_table_size": vendor_ramdisk_table_size,
        "vendor_ramdisk_table_entry_num": vendor_ramdisk_table_entry_num,
        "vendor_ramdisk_table_entry_size": vendor_ramdisk_table_entry_size,
        "bootconfig_size": bootconfig_size,
        "ramdisk_off": ramdisk_off,
        "dtb_off": dtb_off,
        "table_off": table_off,
        "bootconfig_off": bootconfig_off,
        "cmdline": cmdline,
        "tags_addr": tags_addr,
        "name": name,
        "kernel_addr": kernel_addr,
        "ramdisk_addr": ramdisk_addr,
        "dtb_addr": dtb_addr,
    }


def strip_avb_verify_flags(fs_mgr_flags: str) -> str:
    kept = []
    for flag in fs_mgr_flags.split(","):
        f = flag.strip()
        if not f:
            continue
        if f == "avb" or f.startswith("avb=") or f.startswith("avb_keys="):
            continue
        if f == "verify" or f.startswith("verify_") or f.startswith("verifyatboot"):
            continue
        kept.append(f)
    return ",".join(kept)


def patch_fstab(path: Path) -> int:
    if not path.exists():
        return 0

    changed = 0
    out_lines = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(raw)
            continue

        parts = raw.split()
        if len(parts) < 5:
            out_lines.append(raw)
            continue

        fs_mgr_flags = parts[4]
        new_flags = strip_avb_verify_flags(fs_mgr_flags)
        if new_flags != fs_mgr_flags:
            parts[4] = new_flags
            raw = " ".join(parts)
            changed += 1
        out_lines.append(raw)

    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Strip AVB/verify flags from vendor_boot ramdisk fstab files.")
    ap.add_argument("--input", required=True, help="Input vendor_boot image")
    ap.add_argument("--output", required=True, help="Output patched vendor_boot image")
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    img = bytearray(in_path.read_bytes())
    p = parse_vendor_boot(img)

    ramdisk_lz4 = bytes(img[p["ramdisk_off"]:p["ramdisk_off"] + p["vendor_ramdisk_size"]])
    dtb = bytes(img[p["dtb_off"]:p["dtb_off"] + p["dtb_size"]])
    vtbl = bytearray(img[p["table_off"]:p["table_off"] + p["vendor_ramdisk_table_size"]])
    bootconfig = bytes(img[p["bootconfig_off"]:p["bootconfig_off"] + p["bootconfig_size"]])

    with tempfile.TemporaryDirectory(prefix="vb_strip_avb_") as td:
        tdir = Path(td)
        ramdisk_lz4_path = tdir / "ramdisk.lz4"
        ramdisk_cpio_path = tdir / "ramdisk.cpio"
        ramdisk_root = tdir / "root"
        new_cpio_path = tdir / "ramdisk_new.cpio"
        new_lz4_path = tdir / "ramdisk_new.lz4"

        ramdisk_lz4_path.write_bytes(ramdisk_lz4)
        run(["lz4", "-d", "-f", str(ramdisk_lz4_path), str(ramdisk_cpio_path)])
        ramdisk_root.mkdir(parents=True, exist_ok=True)
        run(["bsdtar", "-xf", str(ramdisk_cpio_path), "-C", str(ramdisk_root)])

        fstab_candidates = [
            "first_stage_ramdisk/fstab.mt8781",
            "first_stage_ramdisk/fstab.mt6789",
            "first_stage_ramdisk/fstab.emmc",
            "fstab.mt8781",
            "system/etc/recovery.fstab",
        ]

        total_changed = 0
        for rel in fstab_candidates:
            fp = ramdisk_root / rel
            ch = patch_fstab(fp)
            if ch:
                print(f"patched {rel}: {ch} line(s)")
            total_changed += ch

        if total_changed == 0:
            raise ValueError("No fstab lines were changed; refusing to create no-op image.")

        run(
            [
                "bsdtar",
                "-c",
                "--format",
                "cpio",
                "--uid",
                "0",
                "--gid",
                "0",
                "-f",
                str(new_cpio_path),
                "-C",
                str(ramdisk_root),
                ".",
            ]
        )
        run(["lz4", "-l", "-12", "-f", str(new_cpio_path), str(new_lz4_path)])
        new_ramdisk_lz4 = new_lz4_path.read_bytes()

        # Write a copy of patched fstabs next to output for quick inspection.
        out_dbg = out_path.parent / f"{out_path.stem}.fstab_dump"
        if out_dbg.exists():
            shutil.rmtree(out_dbg)
        out_dbg.mkdir(parents=True, exist_ok=True)
        for rel in fstab_candidates:
            src = ramdisk_root / rel
            if src.exists():
                dst = out_dbg / rel.replace("/", "__")
                dst.write_text(src.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

    new_ramdisk_size = len(new_ramdisk_lz4)
    page_size = p["page_size"]

    # Patch header vendor_ramdisk_size (absolute offset 24).
    struct.pack_into("<I", img, 24, new_ramdisk_size)

    # Patch ramdisk size in vendor ramdisk table entries (first u32 per entry).
    ent_num = p["vendor_ramdisk_table_entry_num"]
    ent_sz = p["vendor_ramdisk_table_entry_size"]
    if ent_num > 0 and ent_sz >= 4:
        struct.pack_into("<I", vtbl, 0, new_ramdisk_size)

    out = bytearray()
    out.extend(img[:p["header_area_size"]])

    out.extend(new_ramdisk_lz4)
    out.extend(b"\x00" * (align(len(new_ramdisk_lz4), page_size) - len(new_ramdisk_lz4)))

    out.extend(dtb)
    out.extend(b"\x00" * (align(len(dtb), page_size) - len(dtb)))

    out.extend(vtbl)
    out.extend(b"\x00" * (align(len(vtbl), page_size) - len(vtbl)))

    out.extend(bootconfig)
    out.extend(b"\x00" * (align(len(bootconfig), page_size) - len(bootconfig)))

    if len(out) > len(img):
        raise ValueError(f"Patched image grew too large: {len(out)} > {len(img)}")
    if len(out) < len(img):
        out.extend(b"\x00" * (len(img) - len(out)))

    out_path.write_bytes(out)
    print(f"Wrote {out_path}")
    print(f"old_ramdisk_size={p['vendor_ramdisk_size']}")
    print(f"new_ramdisk_size={new_ramdisk_size}")
    print(f"image_size={len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
