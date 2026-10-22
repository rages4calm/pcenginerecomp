"""Authored RAM code for the limited CD-control/BRAM profile."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit

MPR_IO=(0xFF,0xF8,0x80,0x81,0xF7,0xFF,0xF7,0)
ADDRESSES=(0x1802,0x1803,0x1804,0x1807,0xB802,0xB803,0xB804,0xB807,
           0x8000,0x87FF,0x8800,0x9FFF,0xC000,0xC7FF,0xC800,0xDFFF)


def make_fixture():
    definitions=[(op,address) for op in (0xAD,0x8D) for address in ADDRESSES]
    definitions += [(0xBD,0x87FF),(0x9D,0x87FF),(0x0C,0x1803),(0x1C,0x1803),
                    (0xAD,0x1907),(0x8D,0x1817),(0xAD,0x0000),(0x43,0)]
    cases=[(0x2800+i*8,op,address) for i,(op,address) in enumerate(definitions)]
    memory={}
    for pc,op,address in cases:
        data=(op,0,0x80,0xFE) if op==0x43 else (op,address&255,address>>8,0x80,0xFE)
        memory.update({0x1F0000+(pc&8191)+i:b for i,b in enumerate(data)})
    reset=bytes(b for i,value in enumerate(MPR_IO) for b in (0xA9,value,0x53,1<<i))
    memory.update({0x1F0700+i:b for i,b in enumerate(reset)})
    return Snapshot(MPR_IO,memory,tuple(pc for pc,_,_ in cases),'synthetic-cd-control-v1'),cases


def generate(out):
    out.mkdir(parents=True,exist_ok=True)
    snapshot,cases=make_fixture()
    module=out/'module.cpp'
    if module.exists():
        module.unlink()  # owned synthetic CMake output
    emit(analyze(snapshot),out)
    lines=['#pragma once','#include <array>','#include <utility>','#include <cstdint>',
           'inline constexpr std::array<std::uint8_t,8> io_mpr{'+','.join(map(str,MPR_IO))+'};',
           'struct IoCase { std::uint16_t pc; std::uint8_t op; std::uint16_t address; };',
           f'inline constexpr std::array<IoCase,{len(cases)}> io_cases{{{{']
    lines += [f'{{{pc},{op},{address}}},' for pc,op,address in cases]+['}};']
    lines += [f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(snapshot.memory)}> io_program{{{{']
    lines += [f'{{{pa},{value}}},' for pa,value in sorted(snapshot.memory.items())]+['}};','']
    (out/'io_fixture.hpp').write_text('\n'.join(lines),encoding='utf-8')


if __name__=='__main__':
    generate(Path(sys.argv[1]))
