"""Generate an entirely synthetic, redistributable conformance module."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit
from pcerecomp.isa import NATIVE, DATA_OPCODES, RMW_OPCODES, TEST_OPCODES, _LENGTH, _ROWS

MPR_DEFAULT = (0xFF,0xF8,0x80,0x81,0x82,0x83,0x84,0)
# RAM-resident reference reset: page 1 stays F8, and page 7 is restored last.
# The last nonzero TAM sets the dedicated latch to zero. No CSL/CSH needed.
MPR_RESET = bytes(b for i,value in enumerate(MPR_DEFAULT) for b in (0xA9,value,0x53,1<<i))


def mpr_cases(oracle=False):
    start=0x3800 if oracle else 0x5000
    return [(start+i*4,op,mask) for i,(op,mask) in enumerate(
        (op,mask) for op in (0x43,0x53) for mask in range(256))]

def edge_cases():
    """Native-only fixture sites for address-space/MMU boundary proofs."""
    return [(0x4900+i*8, op, word) for i, (op, word) in enumerate(
        [(op, word) for op in (0x6C, 0x7C) for word in (0x3FFF, 0xFFFF, 0xFFF0)] +
        [(op, 0xFFFF) for op in (0x1E, 0x7E, 0xDE, 0xFE)])]

def make_fixture(oracle=False):
    origin, base = (0x3000, 0x1F1000) if oracle else (0x4000, 0x100000)
    memory, entries, cases = {}, [], []
    # BRK requires a mapped vector and interrupt-stack expectations. Its
    # dedicated fixture covers those, including IRQ priority and RTI; this
    # ordinary instruction fixture intentionally has no interrupt-vector ROM.
    for index, opcode in enumerate(sorted(NATIVE - {0x00})):
        pc = origin + index*8
        mode = _ROWS[opcode].split(".")[1]
        size = _LENGTH[mode]
        data = [opcode]
        if size == 2:
            # Relative branches loop on themselves when taken; never jump
            # into another fixture's operands as the opcode set grows.
            data += [0xFE if mode == "rel" else 4 if opcode == 0x53 else
                     0xFF if opcode in DATA_OPCODES | RMW_OPCODES | TEST_OPCODES and mode != "imm" else 0x20]
        elif size == 3:
            data += [0xFF,0xFD] if mode=="zrl" else [0x55,0xFF] if mode in ("imz","izx") else [0, 0x48] if opcode in (0x20, 0x4C) else [0xFF, 0x22]
        elif size == 4:
            data += [0x55,0xFF,0x22]
        elif size == 7:
            data += [0,0x22,0x10,0x22,3,0]
        if size != 7:
            data += [0x80, 0xFE]
        memory.update({base+pc-origin+i: b for i, b in enumerate(data)})
        entries.append(pc); cases.append((pc, opcode))
    if not oracle:
        memory[0x100800] = 0x60
        for pc, op, word in edge_cases():
            for i, value in enumerate((op, word&255, word>>8, 0x80, 0xFE)):
                address=0x100000+pc-0x4000+i
                if address in memory:
                    raise ValueError("Synthetic boundary site overlaps a primary instruction")
                memory[address] = value
            entries.append(pc)
    for pc,op,mask in mpr_cases(oracle):
        for i,value in enumerate((op,mask,0x80,0xFE)):
            pa=(MPR_DEFAULT[pc>>13]<<13)|(pc&8191)
            memory[pa+i]=value
        entries.append(pc)
    if oracle:
        memory.update({0x1F0700+i:b for i,b in enumerate(MPR_RESET)})
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
    header += ['}};']
    header += ['struct MprCase { std::uint16_t pc; std::uint8_t op, mask; };',
               f'inline constexpr std::array<MprCase,{len(mpr_cases(oracle))}> mpr_cases{{{{']
    header += [f'{{{pc},{op},{mask}}},' for pc,op,mask in mpr_cases(oracle)]
    header += ['}};']
    if not oracle:
        header += ['struct EdgeCase { std::uint16_t pc; std::uint8_t op; std::uint16_t word; };',
                   f'inline constexpr std::array<EdgeCase,{len(edge_cases())}> edges{{{{']
        header += [f'{{{pc},{op},{word}}},' for pc, op, word in edge_cases()]
        header += ['}};']
    header += [f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(snapshot.memory)}> program{{{{']
    header += [f'{{{address},{value}}},' for address, value in sorted(snapshot.memory.items())]
    header += ['}};', '']
    (out / "fixture.hpp").write_text("\n".join(header), encoding="utf-8")


if __name__ == "__main__":
    generate(Path(sys.argv[1]), len(sys.argv)>2 and sys.argv[2]=="oracle")
