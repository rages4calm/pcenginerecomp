"""Small authored RAM instructions for the opt-in controller bus profile."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit

MPR_JOYPAD = (0xFF, 0xF8, 0x80, 0x81, 0x82, 0xFF, 0x84, 0)
ADDRESSES = (0x1000, 0x1001, 0x107F, 0x1100, 0x13FF,
             0xB000, 0xB001, 0xB07F, 0xB100, 0xB3FF)


def make_fixture():
    definitions = [(op, address) for op in (0xAD, 0x8D) for address in ADDRESSES]
    definitions += [(op, address) for op in (0x0C, 0x1C) for address in (0x1000, 0xB3FF)]
    definitions += [(0x43, 0), (0xEA, 0), (0xAD, 0x1400), (0x8D, 0x0FFF)]
    cases = [(0x2800 + i * 8, op, address) for i, (op, address) in enumerate(definitions)]
    memory = {}
    for pc, op, address in cases:
        if op == 0xEA:
            data = (op, 0x80, 0xFE)
        elif op == 0x43:
            data = (op, 0, 0x80, 0xFE)
        else:
            data = (op, address & 255, address >> 8, 0x80, 0xFE)
        memory.update({0x1F0000 + (pc & 8191) + i: byte for i, byte in enumerate(data)})
    reset = bytes(byte for i, value in enumerate(MPR_JOYPAD)
                  for byte in (0xA9, value, 0x53, 1 << i))
    memory.update({0x1F0700 + i: byte for i, byte in enumerate(reset)})
    return Snapshot(MPR_JOYPAD, memory, tuple(pc for pc, _, _ in cases),
                    'synthetic-joypad-v1'), cases


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    snapshot, cases = make_fixture()
    module = out / 'module.cpp'
    if module.exists():
        module.unlink()  # Owned synthetic CMake output only.
    emit(analyze(snapshot), out)
    lines = ['#pragma once', '#include <array>', '#include <utility>', '#include <cstdint>',
             'inline constexpr std::array<std::uint8_t,8> joypad_mpr{' + ','.join(map(str, MPR_JOYPAD)) + '};',
             'struct JoypadCase { std::uint16_t pc; std::uint8_t op; std::uint16_t address; };',
             f'inline constexpr std::array<JoypadCase,{len(cases)}> joypad_cases{{{{']
    lines += [f'{{{pc},{op},{address}}},' for pc, op, address in cases] + ['}};']
    lines += [f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(snapshot.memory)}> joypad_program{{{{']
    lines += [f'{{{pa},{value}}},' for pa, value in sorted(snapshot.memory.items())] + ['}};', '']
    (out / 'joypad_fixture.hpp').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    generate(Path(sys.argv[1]))
