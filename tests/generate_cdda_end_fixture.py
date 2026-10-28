"""Authored end-update CDBs, translated sample-latch ports, synthetic media."""
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from generate_cdda_gap_fixture import generate as gap_generate, MPR, SITES as GAP_SITES
from pcerecomp.project import ABI

SITES=(*GAP_SITES,(0x2820,0x8D,0x1805),(0x2828,0xAD,0x1805),(0x2830,0xAD,0x1806))
EDGES=1300
PHASES=(0,244)

def cases():
    return [dict(id=f'{state}-end{end}-mode{mode}-phase{phase}',state=state,end=end,mode=mode,offset=phase)
            for state in ('paused','playing') for end in (9,10,11) for mode in (1,2,3) for phase in PHASES]

def authored_sources():
    return [dict(pc=pc,mpr=list(MPR),physical=[0x1F0000+(pc&8191)+i for i in range(3)],
                 data=[op,address&255,address>>8],native_hits=1,interpreted_hits=0) for pc,op,address in SITES]

def generate(out):
    from pcerecomp.emitter import emit_capture
    out=Path(out);gap_generate(out)
    source=authored_sources()
    with TemporaryDirectory() as temporary:
        stage=Path(temporary)/'module'
        emit_capture(dict(schema=1,runtime_abi=ABI,capacity=len(source),complete=True,dropped_instructions=0,
                         unreadable_instructions=0,retired_instructions=len(source),observations=source),stage,single_unit=True)
        for file in stage.iterdir():(out/file.name).write_bytes(file.read_bytes())
    header=['#pragma once','#include <array>','#include <cstdint>','#include <utility>',
            'inline constexpr std::array<std::uint8_t,8> gap_mpr{'+','.join(map(str,MPR))+'};',
            'struct GapSite {unsigned pc,opcode,address;};',
            f'inline constexpr std::array<GapSite,{len(SITES)}> gap_sites{{{{'+','.join('{'+','.join(map(str,s))+'}'for s in SITES)+'}};',
            f'inline constexpr std::array<std::pair<unsigned,std::uint8_t>,{3*len(SITES)}> gap_program{{{{'+','.join(
                '{'+str(0x1F0000+(pc&8191)+i)+','+str(value)+'}'for pc,op,address in SITES for i,value in enumerate((op,address&255,address>>8)))+'}};']
    (out/'cdda_gap_fixture.hpp').write_text('\n'.join(header)+'\n',encoding='utf8')
    (out/'cases.txt').write_text('\n'.join(' '.join(str(case[k])for k in ('id','state','end','mode','offset'))for case in cases())+'\n',encoding='ascii')
    (out/'fixture.json').write_text(json.dumps(dict(schema=1,runtime_abi=ABI,edges=EDGES,phases=PHASES,cases=cases(),authored_sources=source),indent=2)+'\n',encoding='utf8')

if __name__=='__main__':generate(Path(sys.argv[1]))
