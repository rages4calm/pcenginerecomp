"""Authored source identities for actual translated bus-observer execution."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bus_reference_fixture import fixture, generate as reference_generate
from pcerecomp.emitter import emit_capture
from pcerecomp.isa import physical
from pcerecomp.abi import ABI

EXTRA = {
    0x2800: bytes.fromhex('AD 30 20'), 0x2803: bytes.fromhex('8D 31 20'),
    0x2806: bytes.fromhex('48'), 0x2807: bytes.fromhex('68'),
    0x2840: bytes.fromhex('73 30 20 40 20 03 00'),
    0x2850: bytes.fromhex('03 05'), 0x2860: bytes.fromhex('00 EA'),
    0x2870: bytes.fromhex('EA'), 0x2880: bytes.fromhex('AD 00 00'),
}


def generate(out):
    out = Path(out)
    reference_generate(out)
    rows = {}
    for profile in ('low', 'high', 'block'):
        _, description = fixture(profile)
        mpr, accumulator = list(description['entry_mpr']), 0
        for row in description['instructions']:
            raw, pc = row['data'], row['pc']
            key = (pc, tuple(mpr), tuple(raw))
            rows[key] = dict(pc=pc, mpr=mpr[:], data=raw,
                physical=[physical((pc+i)&65535, mpr) for i in range(len(raw))],
                native_hits=0, interpreted_hits=1)
            if raw[0] == 0xA9:
                accumulator = raw[1]
            elif raw[0] == 0x53:
                for bit in range(8):
                    if raw[1] & (1 << bit):
                        mpr[bit] = accumulator
    mpr = [0xF8]*8
    memory = {}
    for pc, raw in EXTRA.items():
        locations = [physical((pc+i)&65535, mpr) for i in range(len(raw))]
        rows[(pc, tuple(mpr), tuple(raw))] = dict(pc=pc, mpr=mpr[:], data=list(raw),
            physical=locations, native_hits=0, interpreted_hits=1)
        memory.update(zip(locations, raw))
    capture = dict(schema=1, runtime_abi=ABI, capacity=len(rows),
        dropped_instructions=0, unreadable_instructions=0,
        retired_instructions=len(rows), complete=True, observations=list(rows.values()))
    with TemporaryDirectory(prefix='bus-trace-authored-', dir=out.parent) as scratch:
        generated = Path(scratch)/'module'
        emit_capture(capture, generated, single_unit=True)
        for source in generated.iterdir():
            (out/source.name).write_bytes(source.read_bytes())
    lines = ['#pragma once', '#include <array>', '#include <utility>', '#include <cstdint>',
        f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(memory)}> bus_trace_program{{{{']
    lines += [f'{{{pa},{value}}},' for pa, value in sorted(memory.items())]
    lines += ['}};', '']
    (out/'bus_trace_fixture.hpp').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    generate(sys.argv[1])
