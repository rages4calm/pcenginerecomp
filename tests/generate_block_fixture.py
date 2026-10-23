"""Authored, RAM-only block transfers, including address-space wraparound."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit

MPR_BLOCK = (0xF8,) * 8
OPS = (0x73, 0xC3, 0xD3, 0xE3, 0xF3)


def make_fixture():
    transfers = [(0x2300, 0x2400, n) for n in (1, 2, 3, 4, 17, 255, 256, 257, 1023)]
    transfers += [(0x2300, 0x2301, 17), (0x2301, 0x2300, 17),
                  (0x21FD, 0x2400, 7), (0x2300, 0x21FD, 7),
                  (0x21FD, 0x21FC, 7), (0xFFFF, 0x23F0, 17),
                  (0x23F0, 0xFFFF, 17), (0x3FFC, 0x5FFC, 9),
                  (0x2300, 0x0002, 4)]
    cases, memory = [], {}
    for op in OPS:
        for source, destination, length in transfers + [
                (0x2200 if op != 0xF3 else 0x2300,
                 0x2200 if op in (0x73, 0xC3) else 0x2400, 0)]:
            pc = 0x2800 + len(cases) * 16
            cases.append((pc, op, source, destination, length))
            data = bytes([op]) + b''.join(n.to_bytes(2, 'little')
                                         for n in (source, destination, length)) + bytes([0x80, 0xFE])
            for i, value in enumerate(data):
                memory[0x1F0000 + ((pc+i) & 8191)] = value
    # Each starts in stack RAM. With SP=(PC+5)&255, Y/A/X replace
    # length-low/destination-high/destination-low before operand fetching.
    for index, op in enumerate(OPS):
        pc = 0x21AA + index * 16
        cases.append((pc, op, 0x2300, 0x2500, 7))
        for i, value in enumerate(bytes([op, 0, 0x23, 0, 0x25, 7, 0, 0x80, 0xFE])):
            memory[0x1F0000 + ((pc+i) & 8191)] = value
    return Snapshot(MPR_BLOCK, memory, tuple(c[0] for c in cases), 'synthetic-block-v1'), cases


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    snapshot, cases = make_fixture()
    module = out / 'module.cpp'
    if module.exists():
        module.unlink()  # This generator owns only its synthetic CMake output.
    emit(analyze(snapshot), out)
    lines = ['#pragma once', '#include <array>', '#include <utility>', '#include <cstdint>',
             'inline constexpr std::array<std::uint8_t,8> block_mpr{' + ','.join(map(str, MPR_BLOCK)) + '};',
             'struct BlockCase { std::uint16_t pc; std::uint8_t op; std::uint16_t source,destination,length; };',
             f'inline constexpr std::array<BlockCase,{len(cases)}> block_cases{{{{']
    lines += ['{' + ','.join(map(str, case)) + '},' for case in cases] + ['}};']
    lines += [f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(snapshot.memory)}> block_program{{{{']
    lines += [f'{{{pa},{value}}},' for pa, value in sorted(snapshot.memory.items())] + ['}};', '']
    (out / 'block_fixture.hpp').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    generate(Path(sys.argv[1]))
