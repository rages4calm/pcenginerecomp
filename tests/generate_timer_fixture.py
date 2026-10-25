"""Authored timer reads, control writes, IRQ acknowledgement and block reads."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit
from pcerecomp.isa import physical

MPR = (0xFF,) + (0xF8,) * 7
PROGRAMS = {
    0x2800: (0xAD, 0, 0x0C),
    0x2810: (0x8D, 0, 0x0C),
    0x2820: (0x8D, 1, 0x0C),
    0x2830: (0x8D, 3, 0x14),
    0x2840: (0xEA,),
    0x2850: (0x40,),
    0x2860: (0x73, 0, 0x0C, 0, 0x22, 4, 0),
    0x2870: (0xAD, 0xFF, 0x0F),
}


def generate(out):
    memory = {physical(pc + i, MPR): value
              for pc, code in PROGRAMS.items() for i, value in enumerate(code)}
    snapshot = Snapshot(MPR, memory, tuple(PROGRAMS), 'authored-timer-phase-v1')
    out.mkdir(parents=True, exist_ok=True)
    module = out / 'module.cpp'
    if module.exists():
        module.unlink()  # Only this generator's synthetic output.
    emit(analyze(snapshot), out)
    lines = ['#pragma once', '#include <array>', '#include <utility>', '#include <cstdint>',
             'inline constexpr std::array<std::uint8_t,8> timer_mpr{' + ','.join(map(str, MPR)) + '};',
             f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(memory)}> timer_program{{{{']
    lines += [f'{{{pa},{value}}},' for pa, value in sorted(memory.items())]
    lines += ['}};', '']
    (out / 'timer_fixture.hpp').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    generate(Path(sys.argv[1]))
