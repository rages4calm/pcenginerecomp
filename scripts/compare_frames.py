"""Compares two PPM (P6) frames pixel by pixel and, optionally, saves PNGs.

Usage: python scripts/compare_frames.py <reference.ppm> <ours.ppm> [--png dir]

Exit code 0 = identical, 1 = different, 2 = invalid input or output.
"""
import argparse
import os
import struct
import sys
import zlib

# Adapted from Fabiano Gelain's PCERecomp, MIT.
# Pinned source and full license are recorded in licenses/PCERecomp-MIT.txt.
MAX_PIXELS = 16_777_216


def read_ppm(path):
    with open(path, "rb") as f:
        data = f.read(MAX_PIXELS * 3 + 4097)
    if len(data) > MAX_PIXELS * 3 + 4096:
        raise ValueError("PPM exceeds the frame size limit")
    parts = []
    pos = 0
    while len(parts) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            end = data.find(b"\n", pos)
            if end < 0:
                raise ValueError("Unterminated PPM comment")
            pos = end + 1
            continue
        if pos >= len(data) or pos > 4096:
            raise ValueError("Incomplete or oversized PPM header")
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        parts.append(data[start:pos])
    separator = data[pos:pos + 1]
    if not separator.isspace():
        raise ValueError("Missing PPM raster separator")
    pos += 2 if data[pos:pos + 2] == b"\r\n" else 1
    if parts[0] != b"P6":
        raise ValueError(f"{path}: not a P6 PPM")
    w, h = int(parts[1]), int(parts[2])
    if not (0 < w <= 8192 and 0 < h <= 8192 and w * h <= MAX_PIXELS) or parts[3] != b"255":
        raise ValueError("Expected bounded RGB8 PPM geometry and maximum value 255")
    if len(data) - pos != w * h * 3:
        raise ValueError("PPM raster byte count differs from geometry")
    return w, h, data[pos:]


def write_png(path, w, h, rgb):
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(kind, payload):
        c = struct.pack(">I", len(payload)) + kind + payload
        return c + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    with open(path, "xb") as f:
        f.write(png)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference")
    ap.add_argument("ours")
    ap.add_argument("--png", help="directory where reference.png, ours.png and diff.png are saved")
    args = ap.parse_args()

    rw, rh, ref = read_ppm(args.reference)
    ow, oh, our = read_ppm(args.ours)

    if args.png:
        os.makedirs(args.png, exist_ok=False)
        write_png(os.path.join(args.png, "reference.png"), rw, rh, ref)
        write_png(os.path.join(args.png, "ours.png"), ow, oh, our)

    if (rw, rh) != (ow, oh):
        print(f"DIFFERENT: reference size {rw}x{rh}, ours {ow}x{oh}")
        return 1

    diff = bytearray(len(ref))
    count = 0
    first = None
    for i in range(0, len(ref), 3):
        if ref[i:i + 3] != our[i:i + 3]:
            count += 1
            diff[i:i + 3] = b"\xff\x00\xff"
            if first is None:
                first = (i // 3 % rw, i // 3 // rw)
        else:
            g = sum(ref[i:i + 3]) // 6  # darkened reference
            diff[i:i + 3] = bytes((g, g, g))
    if args.png:
        write_png(os.path.join(args.png, "diff.png"), rw, rh, bytes(diff))

    if count:
        print(f"DIFFERENT: {count} pixels of {rw * rh} (first at x={first[0]}, y={first[1]})")
        return 1
    print(f"EQUAL: {rw}x{rh}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print(f"compare frames: {error}", file=sys.stderr)
        sys.exit(2)
