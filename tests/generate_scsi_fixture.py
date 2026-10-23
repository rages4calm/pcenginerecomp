"""Authored RAM instructions for the opt-in CD command transport profile."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit

MPR_SCSI = (0xFF, 0xF8, 0x80, 0x81, 0xF7, 0xFF, 0xF7, 0)
ADDRESSES = (0x1800, 0x1801, 0x1802, 0x1803, 0x1804, 0x1807, 0x1808,
             0xB800, 0xB801, 0xB802, 0xB803, 0xB804, 0xB807, 0xB808)


def make_fixture():
    definitions = [(op, address) for op in (0xAD, 0x8D) for address in ADDRESSES]
    definitions += [(0x0C, 0x1802), (0x1C, 0x1802), (0x43, 0), (0xEA, 0),
                    (0xAD, 0x1901), (0x8D, 0x1811)]
    cases = [(0x2800 + i * 8, op, address) for i, (op, address) in enumerate(definitions)]
    memory = {}
    for pc, op, address in cases:
        if op == 0xEA:
            data = (op, 0x80, 0xFE)
        elif op == 0x43:
            data = (op, 0, 0x80, 0xFE)
        else:
            data = (op, address & 255, address >> 8, 0x80, 0xFE)
        memory.update({0x1F0000 + (pc & 8191) + i: b for i, b in enumerate(data)})
    reset = bytes(b for i, value in enumerate(MPR_SCSI) for b in (0xA9, value, 0x53, 1 << i))
    memory.update({0x1F0700 + i: b for i, b in enumerate(reset)})
    return Snapshot(MPR_SCSI, memory, tuple(pc for pc, _, _ in cases),
                    'synthetic-cd-transport-v1'), cases


def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    snapshot, cases = make_fixture()
    module = out / 'module.cpp'
    if module.exists():
        module.unlink()  # Owned synthetic CMake output.
    emit(analyze(snapshot), out)
    lines = ['#pragma once', '#include <array>', '#include <utility>', '#include <cstdint>',
             'inline constexpr std::array<std::uint8_t,8> scsi_mpr{' + ','.join(map(str, MPR_SCSI)) + '};',
             'struct ScsiCase { std::uint16_t pc; std::uint8_t op; std::uint16_t address; };',
             f'inline constexpr std::array<ScsiCase,{len(cases)}> scsi_cases{{{{']
    lines += [f'{{{pc},{op},{address}}},' for pc, op, address in cases] + ['}};']
    lines += [f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(snapshot.memory)}> scsi_program{{{{']
    lines += [f'{{{pa},{value}}},' for pa, value in sorted(snapshot.memory.items())] + ['}};', '']
    (out / 'scsi_fixture.hpp').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    generate(Path(sys.argv[1]))
