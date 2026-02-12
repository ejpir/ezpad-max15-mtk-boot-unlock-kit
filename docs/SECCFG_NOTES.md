# seccfg Notes (2026-02-11)

## Current Readback

`seccfg_read.bin` decoded header:

- magic: `0x4D4D4D4D`
- version: `0x4`
- size: `0x3C`
- lock_state: `0x4` (locked)
- critical_lock_state: `0x0`
- sboot_runtime: `0x0`
- endflag: `0x45454545`

Hash:

- `seccfg_read.bin`: `16a07bb7b37375107b96777b2ff1303822cded9f2d1b371e21a9bbb0d89f5541`
- `images/stock_restore/seccfg.bin`: same hash

This means persistent `seccfg` remained stock/locked in this capture.

## Interpretation

Runtime unlocked/orange behavior was achieved through LK/boot-chain behavior, while persistent lock metadata did not stay changed.

## Extra Patch Candidate

`images/experimental/lk_*_patched_v18_lockfix*` also patches the two additional lock-restore callsites and lockstate getter path. It is provided for testing but is not marked fully confirmed in this bundle.
