"""Authored, code-free-source-bound RAM/stack/mapping bus reference fixture.

Only these literal bytes create the private firmware. No retail input is used.
The primer clears WRAM through guest code; the measured route is finite and
contains no interrupts, MMIO, branches, speed changes or hidden continuations.
"""
from pathlib import Path
import hashlib
import json

PRIMER = [bytes.fromhex(value) for value in (
    '78', 'A9 00', '53 FD', 'A9 F8', '53 02', 'A9 00', '8D 00 20',
    '73 00 20 01 20 FF 1F', 'A2 FF', '9A', 'A2 00', 'A0 00',
    'A9 04', '48', '28')]
SCALAR = [bytes.fromhex(value) for value in (
    'A9 55', '8D 30 20', 'AD 30 20', '48', 'A9 A3', '68',
    'A2 80', '9A', '48', '68', 'A9 F8', '53 04', '8D 31 40',
    'AD 31 40', 'A9 00', '53 04', 'A2 FF', '9A', 'A2 00',
    'A5 30', '85 32', 'E6 32', 'A5 32', 'AD 00 E8',
    'A9 80', '53 04', 'AD 00 40', 'A9 00', '53 04')]
BLOCK = [bytes.fromhex(value) for value in (
    'A9 19', '8D 30 20', 'A9 37', '8D 31 20', 'A9 91', '8D 32 20',
    '73 30 20 40 20 03 00')]


def fixture(profile):
    if profile not in ('low', 'high', 'block'):
        raise ValueError('Known finite bus fixture required')
    primer = PRIMER + [bytes((0xD4 if profile == 'high' else 0x54,)), bytes.fromhex('A9 00')]
    measured = BLOCK if profile == 'block' else SCALAR
    rom = bytearray([0xEA] * 262144)
    code = b''.join(primer + measured) + bytes.fromhex('80 FE')
    rom[:len(code)] = code
    rom[8190:8192] = bytes.fromhex('00 E0')
    marker = 0xE000 + sum(map(len, primer))
    pc = marker
    rows = []
    for ordinal, raw in enumerate(measured, 1):
        rows.append(dict(ordinal=ordinal, pc=pc, data=list(raw)))
        pc += len(raw)
    return bytes(rom), dict(schema=1, profile=profile,
        fixture_sha256=hashlib.sha256(rom).hexdigest(), primer_steps=len(primer),
        steps=len(measured), marker=marker, final_pc=pc,
        entry_mpr=[0, 248, 0, 0, 0, 0, 0, 0],
        entry_divisor=3 if profile == 'high' else 12, instructions=rows)


def generate(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for profile in ('low', 'high', 'block'):
        rom, description = fixture(profile)
        (out/(profile+'.pce')).write_bytes(rom)
        (out/(profile+'.json')).write_text(json.dumps(description, indent=2)+'\n', encoding='utf-8')
    # C++ metadata describes source extent, never executes alternate CPU logic.
    lines = ['#pragma once', '#include <array>', '#include <cstdint>', '#include <string>',
        '#include <stdexcept>', '#include <vector>',
        'struct BusFixtureInstruction {unsigned pc;std::vector<std::uint8_t> bytes;};',
        'struct BusFixture {unsigned primer,divisor;std::vector<BusFixtureInstruction> instructions;};',
        'inline BusFixture bus_fixture(const std::string& profile){']
    for profile in ('low', 'high', 'block'):
        _, value = fixture(profile)
        rows = ','.join('{'+str(row['pc'])+',{'+','.join(map(str,row['data']))+'}}' for row in value['instructions'])
        lines += ['if(profile=="'+profile+'")return {'+str(value['primer_steps'])+','+str(value['entry_divisor'])+',{'+rows+'}};']
    lines += ['throw std::runtime_error("Unknown finite fixture");}']
    (out/'bus_reference_fixture.hpp').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def expected_accesses(profile):
    """Independent literal direction/address/value/map order, not a CPU model."""
    base = [0,248,0,0,0,0,0,0]
    mapped = base.copy();mapped[2]=248
    unbacked = base.copy();unbacked[2]=128
    if profile == 'block':
        rows=[('write',0x2030,0x19,base),('write',0x2031,0x37,base),('write',0x2032,0x91,base),
              ('write',0x21FF,0,base),('write',0x21FE,0x91,base),('write',0x21FD,0,base),
              ('read',0x2030,0x19,base),('write',0x2040,0x19,base),
              ('read',0x2031,0x37,base),('write',0x2041,0x37,base),
              ('read',0x2032,0x91,base),('write',0x2042,0x91,base),
              ('read',0x21FD,0,base),('read',0x21FE,0x91,base),('read',0x21FF,0,base)]
    elif profile in ('low','high'):
        rows=[('write',0x2030,0x55,base),('read',0x2030,0x55,base),
              ('write',0x21FF,0x55,base),('read',0x21FF,0x55,base),
              ('write',0x2180,0x55,base),('read',0x2180,0x55,base),
              ('write',0x4031,0xF8,mapped),('read',0x4031,0xF8,mapped),
              ('read',0x2030,0x55,base),('write',0x2032,0x55,base),
              ('read',0x2032,0x55,base),('write',0x2032,0x56,base),
              ('read',0x2032,0x56,base),('read',0xE800,0xEA,base),
              ('read',0x4000,0xFF,unbacked)]
    else:
        raise ValueError('Known finite bus fixture required')
    return [dict(direction=direction,logical=logical,value=value,mpr=mpr,
                 physical=(mpr[logical>>13]<<13)|(logical&8191))
            for direction,logical,value,mpr in rows]


def expected_event_cycles(profile, engine):
    """Finite source-derived software callback cycle literals, not pin timing.

    Gear scalar bodies access before the pending opcode charge is flushed.
    Beetle scalar bodies charge before access (RMW reads at five, writes at six).
    Both TII bodies push at entry and charge fourteen startup cycles; Beetle
    charges each six-cycle group before its byte access, Gear afterward.
    """
    if engine not in ('Geargrafx','beetle-pce'):
        raise ValueError('Known independent core required')
    if profile in ('low','high'):
        return ([2,7,12,17,25,28,39,44,62,66,70,70,76,80,92]if engine=='Geargrafx'
            else[7,12,15,21,28,32,44,49,66,70,75,76,80,85,97])
    if profile=='block':
        return ([2,9,16,21,21,21,35,35,41,41,47,47,53,53,53]if engine=='Geargrafx'
            else[7,14,21,21,21,21,41,41,47,47,53,53,53,53,53])
    raise ValueError('Known finite bus fixture required')


if __name__ == '__main__':
    import sys
    generate(sys.argv[1])
