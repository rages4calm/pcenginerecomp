"""Authored no-CD DMA/queued-read phase sweep, with guest-only padding."""
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.vdc_adpcm_irq_fixture import Program

MPR=(255,248,0,0,0,0,0,0)
PAYLOAD,TAIL=0xa65c,0x5aa5
LIMIT=1000

def baseline_cases():
    return [dict(id=f'{access}-div{cpu}-vce{vce}-words{words}-pad{pad}',access=access,divisor=cpu,vce=vce,words=words,pad=pad)
            for cpu in(3,12)for vce in(4,3,2)for access in('high','tai')for words in(127,4096)for pad in(0,1)]

def guest_launch_clock(case,*,selected_speed):
    """Declared opcode-cycle derivation; never consumes an observed wait.

    The two established CSH timing conventions are retained separately.
    Setup's completed WRAM delays leave no queued CPU transfer stall. The
    executable adapters independently check this fixed-cycle prediction.
    """
    _,markers,plan=program(case);clock=0;divisor=12
    for row in plan:
        if row['pc']==markers['launch']:break
        data=row['data'];op=data[0]
        if op==0xd4:
            clock+=9 if selected_speed else 2*divisor+3;divisor=3;continue
        if op==0x73:cycles=17+6*(data[5]|data[6]<<8)
        else:cycles={0x78:2,0xa9:2,0x53:5,0xa2:2,0x9a:2,0x8d:5,0x48:3}[op]+int(op==0x8d and(data[1]|data[2]<<8)<0x800)
        clock+=cycles*divisor
    return clock

def edge_cases():
    # Choose the source padding before any new guest execution. The desired
    # original launch positions put DMA's last dot near forced HSW or the
    # truncated line tail. Native CSH keeps its genuine eighteen-tick offset.
    goals={'hsw':{2:354,3:1212,4:705},'tail':{2:345,3:1203,4:693}}
    result=[]
    for cpu in(3,12):
        for vce in(4,3,2):
            for access in('high','tai'):
                base=dict(access=access,divisor=cpu,vce=vce,words=127,pad=0)
                launch=guest_launch_clock(base,selected_speed=True)
                for edge in('hsw','tail'):
                    goal=goals[edge][vce];n=next(n for n in range(1,456)if(launch+(17+6*n)*cpu)%1365==goal)
                    result.append(dict(base,id=f'edge-{edge}-{access}-div{cpu}-vce{vce}-tune{n}',edge=edge,tune=n,design_launch_hclock=goal,design_base_launch_ticks=launch))
    return result

def cases():return baseline_cases()+edge_cases()

def program(case):
    p=Program(0xe000)
    for op in[('sei',),('lda',0),('tam',0xfd),('lda',248),('tam',2),('lda',255),('tam',1)]:p.add(*op)
    if case['divisor']==3:p.add('csh')
    p.add('ldx',255);p.add('txs');p.write(0x1402,7)
    p.write(0x0400,{4:0,3:1,2:2}[case['vce']])
    for reg,value in((5,0),(10,0x7f1f),(11,0x7f7f),(15,0)):p.register(reg,value)
    for address,value in((0,PAYLOAD),(case['words']-1,TAIL)):
        p.register(0,address);p.register(2,value);p.delay(100)
    p.register(1,case['words']-1);p.delay(100)
    for _ in range(4):p.delay(6000)
    if case.get('tune'):p.delay(case['tune'])
    # A real three-cycle push changes slow-CPU slot parity. A two-cycle NOP
    # advances six VCE/4 dots at slow speed and cannot supply this control.
    if case['pad']:p.add('pha')
    for reg,value in((15,2),(16,0),(17,0x2000)):p.register(reg,value)
    p.write(0,18);p.write(2,(case['words']-1)&255);p.add('lda',(case['words']-1)>>8)
    p.label('launch');p.add('sta',3)
    p.register(1,0);p.write(0,2)
    p.label('target')
    if case['access']=='high':p.add('load',3)
    else:p.add('tai',(2,0x2200,2))
    p.label('after_target');p.add('sta',0x2015);p.delay(100)
    p.label('done');p.add('bra','done');p.finish()
    rom=bytearray([0xea]*262144);rom[:len(p.code)]=p.code;rom[0x1ffe:0x2000]=(0xe000).to_bytes(2,'little')
    mapping=[0]*8;a=0;plan=[]
    for pc,raw in sorted(p.ops.items()):
        plan.append(dict(pc=pc,mpr=list(mapping),physical=[(mapping[(pc+i)>>13]<<13)|((pc+i)&8191)for i in range(len(raw))],data=list(raw)))
        if raw[0]==0xa9:a=raw[1]
        if raw[0]==0x53:
            for page in range(8):
                if raw[1]&(1<<page):mapping[page]=a
    assert tuple(mapping)==MPR
    return bytes(rom),p.labels,plan

def expected_vram(case):
    result=[0]*32768;result[0]=result[8192]=PAYLOAD;result[case['words']-1]=result[8192+case['words']-1]=TAIL;return result

def expected_wram(case):
    result=[0]*8192;a=0xa6 if case['access']=='high'else 2;sp=255-case['pad']
    result[0x15]=a
    # Every completed TII preserves A/X/Y, leaving these descending push
    # residues; the optional earlier PHA remains above its saved frame.
    result[256+sp]=0;result[255+sp]=a;result[254+sp]=255
    if case['pad']:result[511]=(case['words']-1)>>8
    if case['access']=='tai':result[512:514]=[0x5c,0xa6]
    return result

def fixtures(out):
    from pcerecomp.emitter import emit_capture
    from pcerecomp.project import ABI
    out=Path(out);out.mkdir(parents=True,exist_ok=True);fixture=out/'fixture';sources={};rows=[]
    for case in cases():
        rom,markers,plan=program(case);(out/(case['id']+'.pce')).write_bytes(rom);rows.append(dict(case,**markers,sha256=hashlib.sha256(rom).hexdigest()))
        for source in plan:sources[json.dumps(source,sort_keys=True)]=dict(source,native_hits=0,interpreted_hits=1)
    source_plan=list(sources.values());emit_capture(dict(schema=1,runtime_abi=ABI,capacity=len(source_plan),dropped_instructions=0,unreadable_instructions=0,retired_instructions=len(source_plan),complete=True,observations=source_plan),fixture,single_unit=True)
    header=['#pragma once','#include <stdexcept>','#include <string>','struct PhaseCase{const char*id;unsigned access,divisor,vce,words,pad,launch,target,after_target,done;};','inline constexpr PhaseCase phase_cases[]{']
    for row in rows:header.append('{"'+row['id']+'",'+','.join(str(v)for v in(int(row['access']=='tai'),row['divisor'],row['vce'],row['words'],row['pad'],row['launch'],row['target'],row['after_target'],row['done']))+'},')
    header+=['};','inline const PhaseCase&phase_case(const std::string&id){for(const auto&c:phase_cases)if(id==c.id)return c;throw std::runtime_error("Unknown authored phase case");}']
    (fixture/'vdc_phase_fixture.hpp').write_text('\n'.join(header)+'\n');(fixture/'fixture.json').write_text(json.dumps(dict(cases=rows,source_plan=source_plan,execution_evidence=False),indent=2)+'\n');return fixture

if __name__=='__main__':fixtures(sys.argv[1])
