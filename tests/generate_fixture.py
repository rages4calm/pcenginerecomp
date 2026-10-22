"""Generate an entirely synthetic, redistributable conformance module."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit
from pcerecomp.isa import NATIVE, DATA_OPCODES, _LENGTH, _ROWS

def make_fixture(oracle=False):
    origin, base = (0x3000, 0x1F1000) if oracle else (0x4000, 0x100000)
    memory, entries, cases = {}, [], []
    for index, opcode in enumerate(sorted(NATIVE)):
        pc = origin + index*8
        mode = _ROWS[opcode].split(".")[1]
        size = _LENGTH[mode]
        data = [opcode]
        if size == 2:
            # Relative branches loop on themselves when taken; never jump
            # into another fixture's operands as the opcode set grows.
            data += [0xFE if mode == "rel" else 4 if opcode == 0x53 else
                     0xFF if opcode in DATA_OPCODES and mode != "imm" else 0x20]
        elif size == 3:
            data += [0, 0x48] if opcode in (0x20, 0x4C) else [0xFF, 0x22]
        data += [0x80, 0xFE]
        memory.update({base+pc-origin+i: b for i, b in enumerate(data)})
        entries.append(pc); cases.append((pc, opcode))
    if not oracle:
        memory[0x100800] = 0x60
    snapshot = Snapshot((0xFF, 0xF8, 0x80, 0x81, 0x82, 0x83, 0x84, 0), memory, tuple(entries), "synthetic-conformance-v1")
    return snapshot, cases


def generate(out, oracle=False):
    out.mkdir(parents=True, exist_ok=True)
    snapshot, cases = make_fixture(oracle)
    module = out / "module.cpp"
    if module.exists():
        module.unlink()  # owned CMake-generated synthetic output only
    emit(analyze(snapshot), out)
    header = ['#pragma once', '#include <array>', '#include <utility>', '#include <cstdint>',
              f'inline constexpr std::array<std::pair<std::uint16_t,std::uint8_t>,{len(cases)}> cases{{{{']
    header += [f'{{{pc},{op}}},' for pc, op in cases]
    header += ['}};', f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(snapshot.memory)}> program{{{{']
    header += [f'{{{address},{value}}},' for address, value in sorted(snapshot.memory.items())]
    header += ['}};', '']
    (out / "fixture.hpp").write_text("\n".join(header), encoding="utf-8")


if __name__ == "__main__":
    generate(Path(sys.argv[1]), len(sys.argv)>2 and sys.argv[2]=="oracle")
