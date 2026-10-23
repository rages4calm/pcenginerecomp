"""Authored code fetched through normal-PC-Engine WRAM aliases."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit
from pcerecomp.isa import physical

MPR = (255, 248, 249, 250, 251, 248, 249, 248)
PROGRAMS = {0x4800: (0xA9, 0x42), 0x4810: (0x8D, 0, 0x60),
            0x4820: (0xAD, 0, 0x80), 0x4830: (0xEE, 0, 0xA0),
            0x4840: (0x73, 0, 0x60, 1, 0x80, 2, 0)}

def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    memory = {physical(pc+i, MPR): byte for pc, data in PROGRAMS.items() for i, byte in enumerate(data)}
    module = out/'module.cpp'
    if module.exists():
        module.unlink()
    emit(analyze(Snapshot(MPR, memory, tuple(PROGRAMS), 'authored-wram-mirrors')), out)
    lines = ['#pragma once', '#include <array>', '#include <utility>', '#include <cstdint>',
             'inline constexpr std::array<std::uint8_t,8> mirror_mpr{'+','.join(map(str, MPR))+'};',
             f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(memory)}> mirror_program{{{{']
    lines += [f'{{{address},{byte}}},' for address, byte in sorted(memory.items())]
    lines += ['}};', '']
    (out/'mirror_fixture.hpp').write_text('\n'.join(lines), encoding='utf-8')

if __name__ == '__main__':
    generate(Path(sys.argv[1]))
