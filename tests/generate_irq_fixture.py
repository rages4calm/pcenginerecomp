"""Small authored interrupt/RTI module, with all vectors in mapped RAM."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit
from pcerecomp.isa import physical

MPR_IRQ = (0xFF,) + (0xF8,) * 7
PROGRAMS = {
    0x2800: (0xEA, 0xEA, 0xEA, 0x80, 0xFE),
    0x2810: (0x58, 0xEA, 0xEA, 0x80, 0xFE),
    0x2820: (0x78, 0xEA, 0xEA, 0x80, 0xFE),
    0x2830: (0x28, 0xEA, 0xEA, 0x80, 0xFE),
    0x2840: (0x40,),
    0x2850: (0x8D, 2, 0x14, 0xEA, 0x80, 0xFE),
    0x2860: (0x8D, 3, 0x14, 0xEA, 0x80, 0xFE),
    0x2870: (0xAD, 2, 0x14, 0x80, 0xFE),
    0x2880: (0xAD, 3, 0x14, 0x80, 0xFE),
    0x2890: (0x80, 0xFE),
    0x2900: (0x40,),
    0x2910: (0x8D, 0, 0x0C, 0x80, 0xFE),
    0x2920: (0x8D, 1, 0x0C, 0x80, 0xFE),
    0x2930: (0xAD, 0, 0x0C, 0x80, 0xFE),
    0x2940: (0x54, 0x80, 0xFE),
    0x2950: (0xD4, 0x80, 0xFE),
    0x2960: (0xF4, 0xEA, 0x80, 0xFE),
    0x2970: (0x40,),
    0x2980: (0x40,),
}


def make_fixture():
    memory = {physical(pc+n, MPR_IRQ): value
              for pc, data in PROGRAMS.items() for n, value in enumerate(data)}
    return Snapshot(MPR_IRQ, memory, tuple(PROGRAMS), 'synthetic-irq-v1')


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    snapshot = make_fixture()
    module = out/'module.cpp'
    if module.exists():
        module.unlink()  # Owned generated synthetic output only.
    emit(analyze(snapshot), out)
    lines = ['#pragma once', '#include <array>', '#include <utility>', '#include <cstdint>',
             'inline constexpr std::array<std::uint8_t,8> irq_mpr{' + ','.join(map(str, MPR_IRQ)) + '};',
             f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(snapshot.memory)}> irq_program{{{{']
    lines += [f'{{{pa},{value}}},' for pa, value in sorted(snapshot.memory.items())]
    lines += ['}};', '']
    (out/'irq_fixture.hpp').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    generate(Path(sys.argv[1]))
