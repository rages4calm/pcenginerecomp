"""Authored VDC port instructions; ST writes deliberately bypass MPR0."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from pcerecomp.analysis import Snapshot, analyze
from pcerecomp.emitter import emit

MPR_VDC=(0x80,0xF8,0x80,0x81,0x82,0xFF,0x84,0)
ADDRESSES=(0xA000,0xA001,0xA002,0xA003,0xA3FC,0xA3FD,0xA3FE,0xA3FF)

def make_fixture():
    cases=[(0x2800+i*4,op,value) for i,(op,value) in enumerate((op,v) for op in (3,19,35) for v in range(256))]
    cases += [(0x3400+i*8,op,address) for i,(op,address) in enumerate((op,a) for op in (0xAD,0x8D) for a in ADDRESSES)]
    memory={}
    for pc,op,value in cases:
        data=(op,value,0x80,0xFE) if op in (3,19,35) else (op,value&255,value>>8,0x80,0xFE)
        memory.update({0x1F0000+(pc&8191)+i:b for i,b in enumerate(data)})
    reset=bytes(b for i,v in enumerate(MPR_VDC) for b in (0xA9,v,0x53,1<<i))
    memory.update({0x1F0700+i:b for i,b in enumerate(reset)})
    memory.update({0x1F0600+i:b for i,b in enumerate(bytes([0xEA]*16+[0x80,0xFE]))})
    return Snapshot(MPR_VDC,memory,tuple(pc for pc,_,_ in cases)+(0x2600,),"synthetic-vdc-v1"),cases

def generate(out):
    out.mkdir(parents=True,exist_ok=True)
    snapshot,cases=make_fixture()
    module=out/"module.cpp"
    if module.exists():module.unlink() # owned CMake synthetic output
    emit(analyze(snapshot),out)
    lines=['#pragma once','#include <array>','#include <utility>','#include <cstdint>',
           'inline constexpr std::array<std::uint8_t,8> vdc_mpr{'+','.join(map(str,MPR_VDC))+'};',
           'struct VdcCase { std::uint16_t pc; std::uint8_t op; std::uint16_t value; };',
           f'inline constexpr std::array<VdcCase,{len(cases)}> vdc_cases{{{{']
    lines += [f'{{{pc},{op},{v}}},' for pc,op,v in cases]+['}};']
    lines += [f'inline constexpr std::array<std::pair<std::uint32_t,std::uint8_t>,{len(snapshot.memory)}> vdc_program{{{{']
    lines += [f'{{{pa},{v}}},' for pa,v in sorted(snapshot.memory.items())]+['}};','']
    (out/'vdc_fixture.hpp').write_text('\n'.join(lines),encoding='utf-8')

if __name__=='__main__':generate(Path(sys.argv[1]))
