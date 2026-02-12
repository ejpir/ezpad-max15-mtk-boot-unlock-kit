#!/usr/bin/env python3
"""
LK patch v18 incremental (v16 -> v18):
- Keep v16 behavior intact
- Disable the two remaining callers to lock-restore helper (target 0x27430)
- Force lock-state getter path to return state=3 and status=0 (from v17)

Usage:
  python3 Tools/patch_lk_v18_from_v16_lockfix.py <lk_v16.img> <out.img>
"""

import struct
import sys

MOV_W0_0 = 0x52800000
NOP = 0xD503201F

# In stock/v16, these are BL calls to helper at 0x27430.
# v16 only patched 0xC59C callsite.
LOCK_RESTORE_EXTRA_CALLS = (
    (0x006CD0, 0x940081D8, MOV_W0_0, "skip restore caller #1"),
    (0x006F10, 0x94008148, MOV_W0_0, "skip restore caller #2"),
)

# Force lock-state getter function path (same patch set as v17).
FORCE_LOCKSTATE3_PATCHES = (
    (0x0A333C, 0x97FFFF3D, 0x52800068, "lock_get: mov w8, #3"),
    (0x0A3340, 0x900007E8, 0xB9000268, "lock_get: str w8, [x19]"),
    (0x0A3344, 0xB9458D08, 0x2A1F03E0, "lock_get: mov w0, wzr"),
    (0x0A3348, 0x7100001F, NOP, "lock_get: nop cmp"),
    (0x0A334C, 0x52860009, NOP, "lock_get: nop mov"),
    (0x0A3350, 0x72A00209, NOP, "lock_get: nop movk"),
    (0x0A3354, 0x1A9F0508, NOP, "lock_get: nop csinc"),
    (0x0A3358, 0xB9000268, NOP, "lock_get: nop str"),
    (0x0A3360, 0x1A8903E0, 0x2A1F03E0, "lock_get: force return 0"),
)


def patch_u32(data: bytearray, off: int, expected: int, new: int, label: str) -> None:
    old = struct.unpack_from("<I", data, off)[0]
    if old != expected:
        raise ValueError(
            f"Unexpected u32 at 0x{off:06X} for {label}: got 0x{old:08X}, expected 0x{expected:08X}"
        )
    struct.pack_into("<I", data, off, new)
    print(f"  0x{off:06X}: 0x{old:08X} -> 0x{new:08X}  {label}")


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <lk_v16.img> <out.img>")
        return 1

    inp, outp = sys.argv[1], sys.argv[2]
    with open(inp, "rb") as f:
        data = bytearray(f.read())

    # Safety checks that input looks like v16 base.
    c59c = struct.unpack_from("<I", data, 0x00C59C)[0]
    if c59c != MOV_W0_0:
        raise ValueError(
            f"Input does not look like v16+: 0x00C59C expected MOV W0,#0 (0x{MOV_W0_0:08X}), got 0x{c59c:08X}"
        )

    print("=== LK patch v18 incremental (from v16) ===")
    print("\n[1] Disable remaining lock-restore callers")
    for off, expected, new, label in LOCK_RESTORE_EXTRA_CALLS:
        patch_u32(data, off, expected, new, label)

    print("\n[2] Force lock-state getter path to state=3 / success")
    for off, expected, new, label in FORCE_LOCKSTATE3_PATCHES:
        patch_u32(data, off, expected, new, label)

    with open(outp, "wb") as f:
        f.write(data)

    print(f"\nWritten: {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
