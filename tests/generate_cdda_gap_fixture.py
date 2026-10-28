"""Authored D8 gap-admission programs and synthetic CUE geometry."""
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
MPR=(255,248,128,129,247,255,247,0)
SITES=((0x2800,0x8D,0x1800),(0x2808,0x8D,0x1801),(0x2810,0x8D,0x1802),(0x2818,0xAD,0x1801))
LAYOUTS=tuple(dict(id=f'{kind}-{first}',kind=kind,first=first,start=10,leadout=610)
              for kind in ('virtual','stored') for first in ('data','audio'))

def cases():
    result=[]
    for state in ('idle','playing','paused','stopped','seeking'):
        for mode in (0,1):
            for target in (8,9):
                result.append(dict(id=f'{state}-mode{mode}-gap{target}',state=state,mode=mode,target=target,kind='gap'))
    for mode in (0,1):
        for target,kind in ((10,'program'),(610,'leadout')):
            result.append(dict(id=f'idle-mode{mode}-{kind}',state='idle',mode=mode,target=target,kind=kind))
    return result

def cdb(op,mode=0,lba=0):return [op,mode,0,(lba>>16)&255,(lba>>8)&255,lba&255,0,0,0,0]

def authored_sources():
    return [dict(pc=pc,mpr=list(MPR),physical=[0x1F0000+(pc&8191)+i for i in range(3)],
                 data=[op,address&255,address>>8],native_hits=1,interpreted_hits=0) for pc,op,address in SITES]

def generate(out):
    from pcerecomp.emitter import emit_capture
    from pcerecomp.project import ABI
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    source=authored_sources()
    with TemporaryDirectory()as temporary:
        stage=Path(temporary)/'module'
        emit_capture(dict(schema=1,runtime_abi=ABI,capacity=len(source),complete=True,dropped_instructions=0,
                         unreadable_instructions=0,retired_instructions=len(source),observations=source),stage,single_unit=True)
        for file in stage.iterdir():
            target=out/file.name;raw=file.read_bytes()
            if not target.exists()or target.read_bytes()!=raw:target.write_bytes(raw)
    header=['#pragma once','#include <array>','#include <cstdint>','#include <utility>',
            'inline constexpr std::array<std::uint8_t,8> gap_mpr{'+','.join(map(str,MPR))+'};',
            'struct GapSite {unsigned pc,opcode,address;};',
            'inline constexpr std::array<GapSite,4> gap_sites{{'+','.join('{'+','.join(map(str,s))+'}'for s in SITES)+'}};',
            'inline constexpr std::array<std::pair<unsigned,std::uint8_t>,12> gap_program{{'+','.join(
                '{'+str(0x1F0000+(pc&8191)+i)+','+str(value)+'}'for pc,op,address in SITES for i,value in enumerate((op,address&255,address>>8)))+'}};']
    (out/'cdda_gap_fixture.hpp').write_text('\n'.join(header)+'\n',encoding='utf8')
    rom=bytearray([0xEA]*262144);rom[8190:8192]=bytes((0,0xE0));(out/'authored.pce').write_bytes(rom)
    for layout in LAYOUTS:
        folder=out/layout['id'];folder.mkdir(exist_ok=True)
        (folder/'data.bin').write_bytes(bytes(4*2048))
        first_audio=layout['first']=='audio';width=2352 if first_audio else 2048
        (folder/'first.bin').write_bytes(bytes(4*width))
        samples=bytearray(600*2352)
        for sector in range(600):
            for frame in range(588):
                value=(sector*31+frame*17)%60000-30000
                pos=sector*2352+frame*4
                samples[pos:pos+2]=value.to_bytes(2,'little',signed=True)
                samples[pos+2:pos+4]=(-value).to_bytes(2,'little',signed=True)
        (folder/'audio.bin').write_bytes((bytes(2*2352)if layout['kind']=='stored'else b'')+samples)
        (folder/'disc.cue').write_text('FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\nFILE "first.bin" BINARY\n TRACK 02 '+('AUDIO'if first_audio else'MODE1/2048')+'\n INDEX 01 00:00:00\nFILE "audio.bin" BINARY\n TRACK 03 AUDIO\n'+
            (' PREGAP 00:00:02\n'if layout['kind']=='virtual'else' INDEX 00 00:00:00\n')+
            ' INDEX 01 '+('00:00:02'if layout['kind']=='stored'else'00:00:00')+'\n',encoding='ascii')
    (out/'cases.txt').write_text('\n'.join(' '.join(str(case[k])for k in ('id','state','mode','target','kind'))for case in cases())+'\n',encoding='ascii')
    (out/'fixture.json').write_text(json.dumps(dict(schema=1,runtime_abi=ABI,layouts=LAYOUTS,cases=cases(),authored_sources=source),indent=2)+'\n',encoding='utf8')

if __name__=='__main__':generate(Path(sys.argv[1]))
