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

## v16 vs v18

- `v16`:
  - AVB key replacement
  - image-auth fail branch bypasses
  - orange-state selector forcing
  - selinux cmdline literal rewrite
  - one lock-restore call skip (`0xC59C`)
- `v18`:
  - everything in `v16`, plus:
  - two extra lock-restore caller skips (`0x6CD0`, `0x6F10`)
  - forced lockstate getter path (`state=3`, success return)

## Why v18 Is Not Baseline

In testing, persistent lock metadata still returns to locked on disk (`seccfg` remains stock-locked). The most likely reason is secure-world lock handling (TEE) reasserting lock state outside the LK patch scope.

Result:

- `v18` is useful as an experiment but does not reliably make persistent lock state stick.
- This does not block the practical workflow here: fastbootd/flash workflows still work for custom-ROM bring-up.
