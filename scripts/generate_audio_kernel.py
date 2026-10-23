#!/usr/bin/env python3
"""Generate our Q30 64-tap/160-phase Blackman-windowed sinc kernel.

No emulator code or coefficients are used. The interpolation ideal is
2*fc*sinc(2*fc*x), fc=20000/44100; the symmetric Blackman window is
0.42+0.5*cos(pi*x/32)+0.08*cos(2*pi*x/32), |x|<=32. Each phase has
exact integer unity gain after normalization and nearest/ties-away rounding.
The largest-magnitude tap receives the tiny normalization residual.
Python's host libm can affect final-bit coefficient regeneration; the checked-in
integer table, not a build-time generator or host libm, defines the runtime.
"""
import argparse
import math
from pathlib import Path


def coefficients():
    result = []
    for phase in range(160):
        center = 31 + phase / 160
        values = []
        for tap in range(64):
            distance = tap - center
            window = (.42 + .5 * math.cos(math.pi * distance / 32)
                      + .08 * math.cos(2 * math.pi * distance / 32))
            z = 2 * (20000 / 44100) * distance
            sinc = 1 if z == 0 else math.sin(math.pi * z) / (math.pi * z)
            values.append(2 * (20000 / 44100) * sinc * window)
        scale = (1 << 30) / sum(values)
        quantized = [int(math.copysign(math.floor(abs(v * scale) + .5), v))
                     for v in values]
        largest = max(range(64), key=lambda index: abs(values[index]))
        quantized[largest] += (1 << 30) - sum(quantized)
        assert sum(quantized) == 1 << 30
        result.append(quantized)
    return result


def render():
    rows = ["    {{" + ",".join(map(str, row)) + "}}" for row in coefficients()]
    return ("// Authored integer coefficients; regenerate with scripts/generate_audio_kernel.py.\n"
            "// 20 kHz cutoff at 44.1 kHz; 64 taps, 160 phases, exact Q30 unity per phase.\n"
            "#pragma once\n#include <array>\n#include <cstdint>\n"
            "namespace pce::audio_detail {\n"
            "inline constexpr std::array<std::array<std::int32_t,64>,160> kernel={{\n"
            + ",\n".join(rows) + "\n}};\n} // namespace pce::audio_detail\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] /
                        "runtime/include/pce/audio_kernel.hpp")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        if args.output.read_text(encoding="utf-8") != content:
            parser.exit(1, "audio kernel differs from this generator's output\n")
    else:
        args.output.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
