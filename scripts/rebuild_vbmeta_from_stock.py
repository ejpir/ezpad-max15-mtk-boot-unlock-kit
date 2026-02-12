#!/usr/bin/env python3
import argparse
import hashlib
import struct
import subprocess
import tempfile
from pathlib import Path


HEADER_SIZE = 0x100


def read_u64be(buf: bytes, off: int) -> int:
    return struct.unpack_from(">Q", buf, off)[0]


def read_u32be(buf: bytes, off: int) -> int:
    return struct.unpack_from(">I", buf, off)[0]


def write_u32be(buf: bytearray, off: int, value: int) -> None:
    struct.pack_into(">I", buf, off, value)


def parse_header(hdr: bytes) -> dict:
    if len(hdr) < HEADER_SIZE:
        raise ValueError("vbmeta header too small")
    if hdr[0:4] != b"AVB0":
        raise ValueError("invalid vbmeta magic")
    return {
        "required_major": read_u32be(hdr, 0x04),
        "required_minor": read_u32be(hdr, 0x08),
        "auth_block_size": read_u64be(hdr, 0x0C),
        "aux_block_size": read_u64be(hdr, 0x14),
        "algorithm_type": read_u32be(hdr, 0x1C),
        "hash_offset": read_u64be(hdr, 0x20),
        "hash_size": read_u64be(hdr, 0x28),
        "sig_offset": read_u64be(hdr, 0x30),
        "sig_size": read_u64be(hdr, 0x38),
        "pubkey_offset": read_u64be(hdr, 0x40),
        "pubkey_size": read_u64be(hdr, 0x48),
        "pkmd_offset": read_u64be(hdr, 0x50),
        "pkmd_size": read_u64be(hdr, 0x58),
        "desc_offset": read_u64be(hdr, 0x60),
        "desc_size": read_u64be(hdr, 0x68),
        "rollback_index": read_u64be(hdr, 0x70),
        "flags": read_u32be(hdr, 0x78),
        "rollback_index_location": read_u32be(hdr, 0x7C),
    }


def sign_sha256_rsa2048(data: bytes, key_path: Path) -> bytes:
    with tempfile.NamedTemporaryFile() as in_f, tempfile.NamedTemporaryFile() as sig_f:
        in_f.write(data)
        in_f.flush()
        subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(key_path),
                "-binary",
                "-out",
                sig_f.name,
                in_f.name,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return Path(sig_f.name).read_bytes()


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild vbmeta using stock descriptors + custom key.")
    ap.add_argument("--stock", required=True, help="Stock top-level vbmeta image (e.g. backup2/vbmeta_a.bin)")
    ap.add_argument("--custom", required=True, help="Custom vbmeta image with desired AVB key (e.g. vbmeta_a_custom.img)")
    ap.add_argument("--key", required=True, help="Custom AVB private key PEM")
    ap.add_argument("--output", required=True, help="Output vbmeta image")
    ap.add_argument("--flags", type=int, default=3, help="vbmeta flags value (default: 3)")
    args = ap.parse_args()

    stock_path = Path(args.stock)
    custom_path = Path(args.custom)
    key_path = Path(args.key)
    out_path = Path(args.output)

    stock = bytearray(stock_path.read_bytes())
    custom = custom_path.read_bytes()

    if len(stock) < HEADER_SIZE or len(custom) < HEADER_SIZE:
        raise ValueError("input image too small")

    stock_hdr = bytearray(stock[:HEADER_SIZE])
    stock_h = parse_header(stock_hdr)
    custom_h = parse_header(custom[:HEADER_SIZE])

    if stock_h["algorithm_type"] != 1:
        raise ValueError(f"unsupported stock algorithm_type={stock_h['algorithm_type']} (expected 1)")
    if stock_h["hash_size"] != 32:
        raise ValueError(f"unsupported hash_size={stock_h['hash_size']} (expected 32)")

    stock_auth_size = stock_h["auth_block_size"]
    stock_aux_size = stock_h["aux_block_size"]
    stock_aux_abs = HEADER_SIZE + stock_auth_size
    if len(stock) < stock_aux_abs + stock_aux_size:
        raise ValueError("stock image truncated")

    custom_aux_abs = HEADER_SIZE + custom_h["auth_block_size"]
    if len(custom) < custom_aux_abs + custom_h["aux_block_size"]:
        raise ValueError("custom image truncated")

    stock_aux = bytearray(stock[stock_aux_abs:stock_aux_abs + stock_aux_size])
    custom_aux = custom[custom_aux_abs:custom_aux_abs + custom_h["aux_block_size"]]

    cpk_off = custom_h["pubkey_offset"]
    cpk_size = custom_h["pubkey_size"]
    spk_off = stock_h["pubkey_offset"]
    spk_size = stock_h["pubkey_size"]

    if cpk_size == 0 or spk_size == 0:
        raise ValueError("missing public key block in vbmeta input")
    if cpk_size != spk_size:
        raise ValueError(f"public key size mismatch custom={cpk_size} stock={spk_size}")
    if cpk_off + cpk_size > len(custom_aux):
        raise ValueError("custom pubkey range out of bounds")
    if spk_off + spk_size > len(stock_aux):
        raise ValueError("stock pubkey range out of bounds")

    custom_pubkey = custom_aux[cpk_off:cpk_off + cpk_size]
    stock_aux[spk_off:spk_off + spk_size] = custom_pubkey

    write_u32be(stock_hdr, 0x78, args.flags)

    to_sign = bytes(stock_hdr) + bytes(stock_aux)
    digest = hashlib.sha256(to_sign).digest()
    signature = sign_sha256_rsa2048(to_sign, key_path)

    sig_size = stock_h["sig_size"]
    if len(signature) != sig_size:
        raise ValueError(f"signature size mismatch expected={sig_size} got={len(signature)}")

    auth = bytearray(stock_auth_size)
    h_off = stock_h["hash_offset"]
    h_size = stock_h["hash_size"]
    s_off = stock_h["sig_offset"]
    s_size = stock_h["sig_size"]

    if h_off + h_size > len(auth):
        raise ValueError("hash field out of auth block bounds")
    if s_off + s_size > len(auth):
        raise ValueError("signature field out of auth block bounds")

    auth[h_off:h_off + h_size] = digest
    auth[s_off:s_off + s_size] = signature

    out = bytearray(stock)
    out[:HEADER_SIZE] = stock_hdr
    out[HEADER_SIZE:HEADER_SIZE + stock_auth_size] = auth
    out[stock_aux_abs:stock_aux_abs + stock_aux_size] = stock_aux

    out_path.write_bytes(out)
    print(f"Wrote {out_path}")
    print(f"flags={args.flags}")
    print(f"descriptors_size=0x{stock_h['desc_size']:x}")
    print(f"public_key_size=0x{spk_size:x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
