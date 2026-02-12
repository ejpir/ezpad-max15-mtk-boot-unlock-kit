#!/usr/bin/env python3
"""
LK patch v16 (v15 + skip lock-state restore):
- Replace embedded AVB public key (trust custom vbmeta key)
- Bypass all duplicated final image-auth failure branches
- Force all discovered verifiedbootstate selector ADD immediates to orange
- Rewrite selected cmdline literals to androidboot.selinux=permissive
- Skip backup lock-state restore in boot_linux_fdt
"""

import struct
import sys


LK_AVB_KEY_OFFSET = 0x136F80
AVB_KEY_LEN = 256
VBMETA_HEADER_SIZE = 0x100

NOP = struct.pack("<I", 0xD503201F)
ORANGE_IMM = 0xF35
MOV_W0_0 = struct.pack("<I", 0x52800000)

# boot_linux_fdt restore lock-state call:
#   c59c: 94006ba5   bl 0x27430
# patched to:
#   c59c: 52800000   mov w0, #0
LOCK_RESTORE_CALL_OFF = 0xC59C

# (offset, expected branch target, label)
IMG_AUTH_BRANCHES = (
    (0x095554, 0x0957C8, "copyA CBNZ img_auth"),
    (0x09566C, 0x095800, "copyA CBNZ img_auth_mkimg"),
    (0x1B957C, 0x1B97F0, "copyB CBNZ img_auth"),
    (0x1B9694, 0x1B9828, "copyB CBNZ img_auth_mkimg"),
    (0x2D1530, 0x2D17A4, "copyC CBNZ img_auth"),
    (0x2D1648, 0x2D17DC, "copyC CBNZ img_auth_mkimg"),
)

# (offset, expected_imm, label)
# ADD Xn, Xn, #imm (shift=0), patch imm -> 0xF35 (orange string offset)
FORCE_ORANGE_SELECTOR_PATCHES = (
    (0x085CF8, 0xF7F, "selector red -> orange"),
    (0x085D7C, 0xFA1, "selector green -> orange"),
    (0x0ADA00, 0xFA1, "selector green copy2 -> orange"),
    (0x141DE0, 0xFA1, "selector green copy3a -> orange"),
    (0x1428B0, 0xFA1, "selector green copy3b -> orange"),
    (0x142988, 0xFA1, "selector green copy3c -> orange"),
    (0x142AE4, 0xFA1, "selector green copy3d -> orange"),
    (0x142BD0, 0xFA1, "selector green copy3e -> orange"),
    (0x142C08, 0xFA1, "selector green copy3f -> orange"),
    (0x15607C, 0xF7F, "selector red copy4 -> orange"),
    (0x15CF7C, 0xFA1, "selector green copy5a -> orange"),
    (0x15CFF4, 0xFA1, "selector green copy5b -> orange"),
)

# (offset, old_string_with_nul, new_string_with_nul, label)
SELINUX_LITERAL_PATCHES = (
    (
        0x0B13A6,
        b"androidboot.meta_log_disable=1\x00",
        b"androidboot.selinux=permissive\x00",
        "meta_log_disable=1 -> selinux=permissive",
    ),
    (
        0x0B13C5,
        b"androidboot.meta_log_disable=0\x00",
        b"androidboot.selinux=permissive\x00",
        "meta_log_disable=0 -> selinux=permissive",
    ),
)


def sign_extend(value: int, bits: int) -> int:
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)


def decode_cbnz_target(instr: int, pc: int) -> int:
    imm19 = (instr >> 5) & 0x7FFFF
    return pc + (sign_extend(imm19, 19) << 2)


def patch(data: bytearray, offset: int, value: bytes, label: str) -> None:
    old = data[offset:offset + len(value)]
    data[offset:offset + len(value)] = value
    print(f"  0x{offset:06X}: {old.hex()} -> {value.hex()}  {label}")


def extract_lk_modulus_from_vbmeta(vbmeta: bytes) -> bytes:
    if len(vbmeta) < VBMETA_HEADER_SIZE or vbmeta[:4] != b"AVB0":
        raise ValueError("invalid vbmeta image")

    auth_block_size = struct.unpack_from(">Q", vbmeta, 0x0C)[0]
    pubkey_offset = struct.unpack_from(">Q", vbmeta, 0x40)[0]
    pubkey_size = struct.unpack_from(">Q", vbmeta, 0x48)[0]
    aux_start = VBMETA_HEADER_SIZE + auth_block_size
    key_blob_start = aux_start + pubkey_offset
    key_blob_end = key_blob_start + pubkey_size

    if key_blob_end > len(vbmeta):
        raise ValueError("vbmeta pubkey blob out of range")
    if pubkey_size < 8 + AVB_KEY_LEN:
        raise ValueError(f"vbmeta pubkey blob too small: {pubkey_size}")

    # LK expects raw RSA modulus bytes; vbmeta key blob starts with 8-byte header.
    return vbmeta[key_blob_start + 8:key_blob_start + 8 + AVB_KEY_LEN]


def validate_cbnz(data: bytes, offset: int, expected_target: int) -> None:
    instr = struct.unpack_from("<I", data, offset)[0]
    if (instr & 0x7F000000) != 0x35000000:
        raise ValueError(f"Expected CBNZ at 0x{offset:06X}, got 0x{instr:08X}")
    target = decode_cbnz_target(instr, offset)
    if target != expected_target:
        raise ValueError(
            f"Unexpected target at 0x{offset:06X}: got 0x{target:06X},"
            f" expected 0x{expected_target:06X}"
        )


def validate_bytes(data: bytes, offset: int, expected: bytes, label: str) -> None:
    actual = data[offset:offset + len(expected)]
    if actual != expected:
        raise ValueError(
            f"Unexpected bytes at 0x{offset:06X} for {label}:"
            f" got {actual!r}, expected {expected!r}"
        )


def expect_bl(data: bytes, offset: int) -> None:
    instr = struct.unpack_from("<I", data, offset)[0]
    if (instr & 0xFC000000) != 0x94000000:
        raise ValueError(f"Expected BL at 0x{offset:06X}, got 0x{instr:08X}")


def patch_add_imm_to_orange(data: bytearray, offset: int, expected_imm: int, label: str) -> None:
    instr = struct.unpack_from("<I", data, offset)[0]

    # ADD (immediate), 64-bit: sf=1, op=0, S=0, shift=0
    if (instr & 0x7F000000) != 0x11000000:
        raise ValueError(f"Expected ADD (imm) at 0x{offset:06X}, got 0x{instr:08X}")
    sf = (instr >> 31) & 1
    op = (instr >> 30) & 1
    s_bit = (instr >> 29) & 1
    shift = (instr >> 22) & 0x3
    imm = (instr >> 10) & 0xFFF
    rn = (instr >> 5) & 0x1F
    rd = instr & 0x1F
    if not (sf == 1 and op == 0 and s_bit == 0 and shift == 0 and rd == rn):
        raise ValueError(f"Unexpected ADD form at 0x{offset:06X}: 0x{instr:08X}")
    if imm != expected_imm:
        raise ValueError(
            f"Unexpected imm at 0x{offset:06X}: got 0x{imm:X}, expected 0x{expected_imm:X}"
        )

    patched = (instr & ~(0xFFF << 10)) | (ORANGE_IMM << 10)
    patch(data, offset, struct.pack("<I", patched), label)


def main() -> int:
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <lk.img> <vbmeta.img> <output.img>")
        return 1

    lk_path, vbmeta_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(lk_path, "rb") as f:
        data = bytearray(f.read())
    with open(vbmeta_path, "rb") as f:
        vbmeta = f.read()

    avb_key = extract_lk_modulus_from_vbmeta(vbmeta)

    print("=== LK patch v16 (v15 + skip lock restore) ===")
    print("\n[1] AVB public key replacement")
    patch(data, LK_AVB_KEY_OFFSET, avb_key, "AVB key from vbmeta")

    print("\n[2] Bypass all duplicated image-auth CBNZ branches")
    for off, target, label in IMG_AUTH_BRANCHES:
        validate_cbnz(data, off, target)
        patch(data, off, NOP, label)

    print("\n[3] Force all discovered verifiedbootstate selectors to orange")
    for off, imm, label in FORCE_ORANGE_SELECTOR_PATCHES:
        patch_add_imm_to_orange(data, off, imm, label)

    print("\n[4] Rewrite cmdline literals to selinux permissive")
    for off, old, new, label in SELINUX_LITERAL_PATCHES:
        if len(old) != len(new):
            raise ValueError(f"Length mismatch for {label}: {len(old)} vs {len(new)}")
        validate_bytes(data, off, old, label)
        patch(data, off, new, label)

    print("\n[5] Skip backup lock-state restore")
    expect_bl(data, LOCK_RESTORE_CALL_OFF)
    patch(data, LOCK_RESTORE_CALL_OFF, MOV_W0_0, "boot_linux_fdt restore lock -> success no-op")

    with open(out_path, "wb") as f:
        f.write(data)

    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
