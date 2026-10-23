"""Authored multi-context observations for the optional independent CPU probe."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pcerecomp.isa import physical


def plans():
    result = []

    def add(name, pc, data, *, mpr=None, flags=4, a=0x49, x=0x55, sp=0xFD, patches=()):
        mapping = list(mpr or (0, 0xF8, 1, 2, 3, 4, 5, 0))
        final = mapping.copy()
        if data[0] == 0x53:
            for i in range(8):
                if data[1] & (1 << i):
                    final[i] = a
        result.append(dict(id=name, pc=pc, data=list(data), mpr=mapping,
                           next_mpr=final, p=flags, a=a, x=x, y=0xA7, sp=sp,
                           seed=len(result), patches=[list(p) for p in patches]))

    for divisor in (3, 12):
        for context in (1, 2):
            mapping = [0, 0xF8, 1, 2, context, 4, 5, 0]
            for operand in (0x09, 0x99):
                for flags in (4, 5, 12, 13, 36, 37, 44, 45):
                    add(f'adc-{divisor}-{context}-{operand:02x}-{flags:02x}', 0x2800,
                        [0x69, operand], mpr=mapping, flags=flags)
                    result[-1]['divisor'] = divisor
    # The same logical PC fetches genuinely distinct physical ROM banks.
    add('rom-bank-1', 0x4800, [0xA9, 0x11])
    add('rom-bank-2', 0x4800, [0xA9, 0x88], mpr=[0, 0xF8, 2, 2, 1, 4, 5, 0])
    for bank in (1, 2):
        add(f'cross-page-{bank}', 0x3FFF, [0x69, 0x20 + bank],
            mpr=[0, 0xF8, bank, 2, 1, 4, 5, 0], flags=45)
        add(f'wrap-fetch-{bank}', 0xFFFF, [0xA9, 0x20 + bank],
            mpr=[bank, 0xF8, 1, 2, 1, 4, 5, 0xF8])
    add('tma-or', 0x2800, [0x43, 0x34], flags=0xFF)
    add('tam-context', 0x2800, [0x53, 4], a=2, flags=0xFF)
    for sp in (0, 0xFE, 0xFF):
        add(f'pha-{sp}', 0x2800, [0x48], sp=sp, flags=0xFF)
        add(f'rti-{sp}', 0x2800, [0x40], sp=sp, flags=0xFF,
            patches=[(0x100 + ((sp+1)&255), 0xA5),
                     (0x100 + ((sp+2)&255), 0x34),
                     (0x100 + ((sp+3)&255), 0x12)])
    for p in result:
        p.setdefault('divisor', 3)
    return result


def bootstrap(mapping, divisor):
    # MPR1 remains the work-RAM window, including while every other map changes.
    data = [0x78, 0x54 if divisor == 12 else 0xD4]
    for i, value in enumerate(mapping):
        data += [0xA9, value, 0x53, 1 << i]
    return bytes(data)


def rom_image():
    rom = bytearray([0xEA] * (8 * 8192))
    boot = bootstrap([0, 0xF8, 1, 2, 3, 4, 5, 0], 3)
    rom[:len(boot)] = boot
    rom[0x1FFE:0x2000] = bytes([0, 0xE0])
    for p in plans():
        for i, value in enumerate(p['data']):
            address = physical((p['pc'] + i) & 0xFFFF, p['mpr'])
            if address < len(rom):
                rom[address] = value
    return rom


def ram_image(p):
    ram = bytearray((i * 37 + p['seed'] * 17) & 255 for i in range(8192))
    boot = bootstrap(p['mpr'], p['divisor'])
    ram[0x700:0x700+len(boot)] = boot
    ram[0x600:0x603] = bytes([0x43, 0, 0xEA])
    for i, value in enumerate(p['data']):
        address = physical((p['pc'] + i) & 0xFFFF, p['mpr'])
        if 0x1F0000 <= address < 0x1F2000:
            ram[address - 0x1F0000] = value
    for offset, value in p['patches']:
        ram[offset] = value
    return ram


def capture():
    observations = {}
    for p in plans():
        for pc, mapping, data in ((p['pc'], p['mpr'], p['data']),
                                  (0x2600, p['next_mpr'], [0x43, 0])):
            key = (pc, tuple(mapping), tuple(data))
            observations[key] = dict(pc=pc, mpr=mapping, data=data,
                physical=[physical((pc+i)&65535, mapping) for i in range(len(data))],
                native_hits=0, interpreted_hits=1)
    return dict(schema=1, runtime_abi=12, capacity=256, dropped_instructions=0,
                unreadable_instructions=0, retired_instructions=len(observations),
                complete=True, observations=list(observations.values()))


def generate(out):
    from pcerecomp.emitter import emit_capture
    out.mkdir(parents=True, exist_ok=True)
    # Unlike the public CLI, CMake regenerates an owned authored fixture in
    # place. Keep the compiler's new-directory safety rule intact.
    with tempfile.TemporaryDirectory(prefix='capture-fixture-', dir=out) as temp:
        generated = Path(temp)/'generated'
        emit_capture(capture(), generated)
        for name in ('module.cpp', 'module.json'):
            (out/name).write_bytes((generated/name).read_bytes())
    lines = ['#pragma once', '#include <array>', '#include <cstdint>',
             'struct CapturePlan { unsigned pc,a,x,y,sp,p,divisor,latch; std::array<std::uint8_t,8> mpr; std::array<std::uint8_t,8192> ram; };',
             'inline const CapturePlan capture_plans[] = {']
    for p in plans():
        fields = [p[k] for k in ('pc', 'a', 'x', 'y', 'sp', 'p', 'divisor')]+[p['mpr'][-1]]
        lines += ['{' + ','.join(map(str, fields)) + ',{' + ','.join(map(str,p['mpr'])) + '},{' + ','.join(map(str,ram_image(p))) + '}},']
    lines += ['};', 'inline const std::array<std::uint8_t,65536> capture_rom{' + ','.join(map(str,rom_image())) + '};']
    (out/'capture_fixture.hpp').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    (out/'plans.json').write_text(json.dumps(plans(),indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    generate(Path(sys.argv[1]))
