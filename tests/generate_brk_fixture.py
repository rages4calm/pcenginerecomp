"""Authored BRK/RTI source identities, including wrap and stack aliases."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from pcerecomp.emitter import emit_capture
from pcerecomp.isa import physical

CONTEXTS=((0xF8,)*8,(0xF8,0xF8,0xF9,0xF8,0xF8,0xF8,0xF8,0xF8),
          (0xF8,0xF8,0xF8,0xF8,0xF8,0xF8,0xF8,0x81))
SITES=(0x2800,0x3FFF,0xFFFF,0x2100)
HANDLER=0x2900

def make_fixture():
    observations=[];memory={}
    for mpr in CONTEXTS:
        for pc in (*SITES,HANDLER):
            raw=(0x40,) if pc==HANDLER else (0,0xA5)
            locations=[physical(pc+i,mpr) for i in range(len(raw))]
            for pa,value in zip(locations,raw):
                if pa in memory and memory[pa]!=value:raise ValueError('Conflicting authored fixture bytes')
                memory[pa]=value
            observations.append(dict(pc=pc,mpr=list(mpr),physical=locations,data=list(raw),native_hits=0,interpreted_hits=1))
    capture=dict(schema=1,runtime_abi=16,capacity=32,dropped_instructions=0,unreadable_instructions=0,
                 retired_instructions=len(observations),complete=True,observations=observations)
    return capture,memory

def generate(out):
    out.mkdir(parents=True,exist_ok=True)
    capture,memory=make_fixture()
    # The capture emitter requires a fresh directory, while CMake reuses its
    # known fixture directory on regeneration. Only replace these authored
    # generated files; never remove the fixture directory or unrelated data.
    with TemporaryDirectory(prefix='brk-authored-',dir=out.parent) as scratch:
        generated=Path(scratch)/'module'
        emit_capture(capture,generated,single_unit=True)
        for source in generated.iterdir():(out/source.name).write_bytes(source.read_bytes())
    lines=['#pragma once','#include <array>','#include <utility>','#include <cstdint>',
           f'inline constexpr std::array<std::array<std::uint8_t,8>,{len(CONTEXTS)}> brk_contexts{{{{']
    lines += ['{'+','.join(map(str,mpr))+'},' for mpr in CONTEXTS]+['}};']
    lines += [f'inline constexpr std::array<std::uint16_t,{len(SITES)}> brk_sites{{'+','.join(map(str,SITES))+'};',
              f'inline constexpr std::uint16_t brk_handler={HANDLER};',
              f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(memory)}> brk_program{{{{']
    lines += [f'{{{pa},{value}}},' for pa,value in sorted(memory.items())]+['}};','']
    (out/'brk_fixture.hpp').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__':generate(Path(sys.argv[1]))
