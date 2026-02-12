#!/usr/bin/env python3
"""
Reconstruct MTK expdb into human-readable logs.

This tool does not rely on adb shell. It reads the raw expdb binary and emits:
- reconstructed_full.log          (all extracted printable records)
- reconstructed_human.log         (medium/high-confidence readable records)
- latest_boot_window.log          (focused latest LK->kernel->init panic window)
- summary.txt

Usage:
  python3 Tools/reconstruct_expdb.py <expdb.bin> [--outdir <dir>]
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


HIGH_PATTERNS = [
    r"\[AVB\]",
    r"\[SEC\]",
    r"auth fail|Auth Fail|Image Auth Fail",
    r"boot_linux_fdt:508: lk finished --> jump to linux kernel 64Bit",
    r"Kernel panic - not syncing",
    r"Attempted to kill init",
    r"init:",
    r"EXT4-fs",
    r"e2fsck",
]

MED_PATTERNS = [
    r"\[[ ]*\d+\.\d+\]",
    r"bootargs:",
    r"slot [01]|ab_suffix|get_suffix",
    r"first stage|second stage|fs_mgr|dm-verity|selinux|avc:",
]

WINDOW_PATTERNS = [
    r"\[AVB\]|auth fail|Auth Fail|Image Auth Fail",
    r"boot_linux_fdt:508: lk finished --> jump to linux kernel 64Bit",
    r"Update version, boot successfully on slot",
    r"bootargs:|kcmdline appended",
    r"init:|first stage|second stage|fs_mgr|selinux|avc:|Permission denied|No such file|exec",
    r"e2fsck|EXT4-fs",
    r"Kernel panic - not syncing|Attempted to kill init",
]


@dataclass
class Record:
    off: int
    text: str
    level: str


def normalize_text(raw: bytes) -> str:
    s = raw.decode("ascii", "ignore").replace("\t", " ")
    s = re.sub(r" +", " ", s).strip()
    return s


def extract_printable_records(data: bytes, min_len: int) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    run = bytearray()
    run_start = 0

    def flush() -> None:
        nonlocal run, run_start
        if not run:
            return
        text = normalize_text(bytes(run))
        if len(text) >= min_len:
            out.append((run_start, text))
        run = bytearray()

    for i, b in enumerate(data):
        is_printable = 32 <= b < 127 or b == 9
        if is_printable:
            if not run:
                run_start = i
            run.append(b)
            continue
        flush()

    flush()
    return out


def score_level(text: str, high_res: Iterable[re.Pattern[str]], med_res: Iterable[re.Pattern[str]]) -> str:
    score = 0
    for pat in high_res:
        if pat.search(text):
            score += 4
    for pat in med_res:
        if pat.search(text):
            score += 2

    letters = sum(1 for c in text if c.isalpha())
    ratio = letters / len(text) if text else 0.0
    if ratio > 0.45:
        score += 1

    if re.fullmatch(r"[0-9A-Fa-f]{24,}", text):
        score -= 3

    if score >= 6:
        return "H"
    if score >= 2:
        return "M"
    return "L"


def find_last_index(records: list[Record], needle: str) -> int:
    idx = -1
    for i, rec in enumerate(records):
        if needle in rec.text:
            idx = i
    return idx


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_full(records: list[Record], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for i, rec in enumerate(records):
            f.write(f"{i:06d} 0x{rec.off:08X} [{rec.level}] {rec.text}\n")


def write_human(records: list[Record], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            if rec.level in {"H", "M"}:
                f.write(rec.text + "\n")


def write_latest_window(records: list[Record], out_path: Path, before: int, after: int) -> None:
    jump_idx = find_last_index(records, "lk finished --> jump to linux kernel 64Bit")
    panic_idx = find_last_index(records, "Attempted to kill init")
    if jump_idx < 0 and panic_idx < 0:
        with out_path.open("w", encoding="utf-8") as f:
            f.write("No LK handoff/panic markers found.\n")
        return

    anchor = jump_idx if jump_idx >= 0 else panic_idx
    start = max(0, anchor - before)
    end_anchor = panic_idx if panic_idx >= 0 else anchor
    end = min(len(records), end_anchor + after)
    pats = [re.compile(p) for p in WINDOW_PATTERNS]

    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"latest_jump_idx={jump_idx}\n")
        f.write(f"latest_init_panic_idx={panic_idx}\n")
        f.write("\n")
        for i in range(start, end):
            rec = records[i]
            if rec.level == "L":
                continue
            if any(p.search(rec.text) for p in pats):
                f.write(f"{i:06d} 0x{rec.off:08X} [{rec.level}] {rec.text}\n")


def write_summary(records: list[Record], out_path: Path) -> None:
    h = sum(1 for r in records if r.level == "H")
    m = sum(1 for r in records if r.level == "M")
    l = sum(1 for r in records if r.level == "L")

    avb_lines = [r.text for r in records if "[AVB] avb_ret" in r.text]
    lk_auth_lines = [r.text for r in records if "image lk auth fail" in r.text or "lk Image Auth Fail" in r.text]
    cmdline_lines = [r.text for r in records if "bootargs:" in r.text or "kcmdline appended:" in r.text]
    observed_slot_suffix = any("androidboot.slot_suffix" in r.text for r in records)
    observed_verified_state = any("androidboot.verifiedbootstate" in r.text for r in records)
    observed_veritymode = any("androidboot.veritymode" in r.text for r in records)
    observed_vbmeta_state = any("androidboot.vbmeta" in r.text for r in records)
    jump_idx = find_last_index(records, "lk finished --> jump to linux kernel 64Bit")
    panic_idx = find_last_index(records, "Attempted to kill init")
    jump_idxs = [i for i, r in enumerate(records) if "lk finished --> jump to linux kernel 64Bit" in r.text]
    panic_idxs = [i for i, r in enumerate(records) if "Attempted to kill init" in r.text]

    # Pair each jump with the first panic after it (if any).
    pairs: list[tuple[int, int | None]] = []
    pi = 0
    for ji in jump_idxs:
        while pi < len(panic_idxs) and panic_idxs[pi] < ji:
            pi += 1
        pairs.append((ji, panic_idxs[pi] if pi < len(panic_idxs) else None))

    latest_pair = pairs[-1] if pairs else None
    latest_completed = next((p for p in reversed(pairs) if p[1] is not None), None)

    # Diagnostics specifically for the newest observed boot attempt.
    if jump_idxs:
        latest_jump = jump_idxs[-1]
        last_lk_auth_after_latest = None
        last_avb_after_latest = None
        for i in range(len(records) - 1, latest_jump - 1, -1):
            t = records[i].text
            if last_lk_auth_after_latest is None and ("image lk auth fail" in t or "lk Image Auth Fail" in t):
                last_lk_auth_after_latest = t
            if last_avb_after_latest is None and "[AVB] avb_ret" in t:
                last_avb_after_latest = t
            if last_lk_auth_after_latest is not None and last_avb_after_latest is not None:
                break
    else:
        last_lk_auth_after_latest = None
        last_avb_after_latest = None

    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"records_total={len(records)}\n")
        f.write(f"records_high={h}\n")
        f.write(f"records_medium={m}\n")
        f.write(f"records_low={l}\n")
        f.write(f"latest_jump_idx={jump_idx}\n")
        f.write(f"latest_init_panic_idx={panic_idx}\n")
        f.write(f"jump_count={len(jump_idxs)}\n")
        f.write(f"init_panic_count={len(panic_idxs)}\n")
        if latest_pair:
            f.write(f"latest_attempt_jump_idx={latest_pair[0]}\n")
            f.write(f"latest_attempt_panic_idx={(latest_pair[1] if latest_pair[1] is not None else '<none_after_latest_jump>')}\n")
        else:
            f.write("latest_attempt_jump_idx=<not found>\n")
            f.write("latest_attempt_panic_idx=<not found>\n")
        if latest_completed:
            f.write(f"latest_completed_attempt_jump_idx={latest_completed[0]}\n")
            f.write(f"latest_completed_attempt_panic_idx={latest_completed[1]}\n")
        else:
            f.write("latest_completed_attempt_jump_idx=<not found>\n")
            f.write("latest_completed_attempt_panic_idx=<not found>\n")
        f.write(f"last_avb_ret={(avb_lines[-1] if avb_lines else '<not found>')}\n")
        f.write(f"last_lk_auth_line={(lk_auth_lines[-1] if lk_auth_lines else '<not found>')}\n")
        f.write(f"last_avb_ret_after_latest_jump={(last_avb_after_latest if last_avb_after_latest else '<not found_after_latest_jump>')}\n")
        f.write(f"last_lk_auth_line_after_latest_jump={(last_lk_auth_after_latest if last_lk_auth_after_latest else '<not found_after_latest_jump>')}\n")
        f.write(f"observed_androidboot_slot_suffix_in_logs={observed_slot_suffix}\n")
        f.write(f"observed_androidboot_verifiedbootstate_in_logs={observed_verified_state}\n")
        f.write(f"observed_androidboot_veritymode_in_logs={observed_veritymode}\n")
        f.write(f"observed_androidboot_vbmeta_in_logs={observed_vbmeta_state}\n")
        if cmdline_lines:
            f.write(f"last_cmdline_line={cmdline_lines[-1]}\n")
        else:
            f.write("last_cmdline_line=<not found>\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconstruct expdb into readable logs.")
    ap.add_argument("expdb", help="Path to expdb binary")
    ap.add_argument("--outdir", default="", help="Output directory (default: alongside expdb)")
    ap.add_argument("--min-len", type=int, default=8, help="Minimum extracted token length")
    ap.add_argument("--window-before", type=int, default=120, help="Records before latest jump marker")
    ap.add_argument("--window-after", type=int, default=80, help="Records after latest panic marker")
    args = ap.parse_args()

    expdb = Path(args.expdb)
    if not expdb.is_file():
        raise SystemExit(f"expdb not found: {expdb}")

    outdir = Path(args.outdir) if args.outdir else expdb.parent / f"{expdb.stem}_reconstructed"
    ensure_dir(outdir)

    data = expdb.read_bytes()
    raw_records = extract_printable_records(data, min_len=args.min_len)
    high_res = [re.compile(p) for p in HIGH_PATTERNS]
    med_res = [re.compile(p) for p in MED_PATTERNS]

    records = [Record(off=off, text=text, level=score_level(text, high_res, med_res)) for off, text in raw_records]

    full_log = outdir / "reconstructed_full.log"
    human_log = outdir / "reconstructed_human.log"
    latest_log = outdir / "latest_boot_window.log"
    summary = outdir / "summary.txt"

    write_full(records, full_log)
    write_human(records, human_log)
    write_latest_window(records, latest_log, before=args.window_before, after=args.window_after)
    write_summary(records, summary)

    print(f"expdb: {expdb}")
    print(f"outdir: {outdir}")
    print(f"records: {len(records)}")
    print(f"written: {full_log}")
    print(f"written: {human_log}")
    print(f"written: {latest_log}")
    print(f"written: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
