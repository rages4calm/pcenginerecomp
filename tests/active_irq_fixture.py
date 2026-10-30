"""Authored active-display IRQ/READ-fed ADPCM recipes; no retail inputs."""
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.vdc_adpcm_irq_fixture import Program, pattern

MPR=(255,248,0,0,0,0,0,0)
SOURCES=('raster','collision')
ACCESS=('high','tai')
POLICIES=('retain','mask')
DATA,SAT=0x6000,0x7000
FIRST,PAYLOAD,TAIL=0xdead,0xa65c,0x5aa5
LIMIT=1500000

def cases():
    return [dict(id=f'{source}-{access}-{policy}-div{div}-vce{vce}',source=source,
        access=access,policy=policy,divisor=div,vce=vce)
        for source in SOURCES for div in (3,12) for vce in (4,3,2)
        for access in ACCESS for policy in POLICIES]

def write_word(p,address,value):
    p.register(0,address);p.register(2,value);p.delay(100)

def program(case):
    p=Program(0xe000)
    for op in [('sei',),('lda',0),('tam',0xfd),('lda',248),('tam',2),('lda',255),('tam',1)]:p.add(*op)
    if case['divisor']==3:p.add('csh')
    p.add('ldx',255);p.add('txs');p.add('ldx',0);p.write(0x1402,7);p.write(0x1802,0)
    p.write(0x400,{4:0,3:1,2:2}[case['vce']])
    # Each selected HDW reaches its natural RCR event before physicalHSYNC.
    # Extending HDW beyond a physical line would skip original sprite fetches.
    hdr={4:0x7f1f,3:0x7f2f,2:0x7f47}[case['vce']]
    for reg,value in ((5,0),(9,3),(10,0x0202),(11,hdr),(12,0x0f02),(13,239),(14,2),(15,0)):
        p.register(reg,value)
    for index in range(2):
        for offset,value in enumerate((64,32,512,0x3000)):
            write_word(p,SAT+4*index+offset,value)
    for row in range(64):write_word(p,0x4000+(row//16)*128+(row&15),65535)
    for index,value in enumerate((FIRST,PAYLOAD,TAIL)):write_word(p,DATA+index,value)
    p.register(1,DATA);p.delay(100);p.register(19,SAT);p.register(5,0xc0)
    for _ in range(10):p.delay(6000)
    p.write(0x180d,128);p.write(0x180d,0)
    p.write(0x1808,254);p.write(0x1809,255);p.write(0x180d,3);p.write(0x180d,0)
    p.write(0x1800,0)
    for i,value in enumerate((8,0,0,0,1,0)):
        p.poll('command'+str(i),0x58,0x50);p.write(0x1801,value);p.ack(0)
    p.poll('data',0x58,0x48);p.write(0x1802,12)
    p.register(1,DATA);p.delay(100)
    p.register(6,96);p.register(5,0xc4 if case['source']=='raster'else 0xc1)
    p.label('wait_irq1');p.add('load',0x1403);p.add('and',2);p.add('cmp',2);p.add('bne','wait_irq1')
    # RCR occurs late in a line; two ordinary WRAM transfers place its queue
    # request in the following active line. Collision already asserts at HDW
    # entry, so it needs no extra delay (including the slow TAI prologue).
    # The arithmetic uses guest cycles and register geometry, not observations.
    if case['source']=='raster':
        for _ in range(2):p.delay(10 if case['divisor']==3 else 1)
    p.write(0,2);p.add('load',3)
    p.write(0x1402,4);p.add('lda',2);p.label('pre_dma');p.add('sta',0x180b)
    p.add('cli');p.label('target')
    if case['access']=='high':p.add('load',3)
    else:p.add('tai',(2,0x2200,2))
    p.label('return_pc');p.add('nop');p.add('sta',0x2015)
    p.poll('status',0x58,0x58)
    p.label('write_done');p.add('load',0x180c);p.add('and',4);p.add('cmp',0);p.add('bne','write_done')
    p.write(0x180b,0);p.add('load',0x1801);p.add('sta',0x2010);p.ack(0)
    p.poll('message',0x78,0x78);p.add('load',0x1801);p.add('sta',0x2013);p.ack(0)
    p.poll('free',0x80,0);p.add('sei');p.write(0x1402,7);p.write(0x1802,0)
    p.label('done');p.add('bra','done');p.finish()
    h1=Program(0xf800);h1.add('pha');h1.add('inc',0x2011);h1.register(5,0xc0)
    h1.add('load',0);h1.add('and',63);h1.add('sta',0x2014)
    h1.add('load',0x1803);h1.add('and',12);h1.add('sta',0x2016)
    if case['policy']=='mask':h1.write(0x1802,0)
    h1.label('post_ack');h1.add('pla');h1.add('rti');h1.finish()
    h2=Program(0xf880);h2.add('pha');h2.add('inc',0x2012);h2.write(0x1402,7);h2.add('pla');h2.add('rti');h2.finish()
    if p.pc>=0xf800:raise ValueError('Authored setup overlaps handlers')
    rom=bytearray([0xea]*262144)
    for piece in (p,h1,h2):rom[piece.start&8191:(piece.start&8191)+len(piece.code)]=piece.code
    for address,target in ((0xfff6,h2.start),(0xfff8,h1.start),(0xfffa,0xf900),(0xfffe,p.start)):
        rom[address&8191:(address&8191)+2]=target.to_bytes(2,'little')
    rom[0x1900]=0x40;mapping=[0]*8;a=0;sources=[]
    for pc,raw in sorted(p.ops.items()):
        sources.append(dict(pc=pc,mpr=list(mapping),physical=[(mapping[((pc+i)&65535)>>13]<<13)|((pc+i)&8191)for i in range(len(raw))],data=list(raw)))
        if raw[0]==0xa9:a=raw[1]
        if raw[0]==0x53:
            for page in range(8):
                if raw[1]&(1<<page):mapping[page]=a
    assert tuple(mapping)==MPR
    for piece in (h1,h2):
        for pc,raw in piece.ops.items():sources.append(dict(pc=pc,mpr=list(MPR),physical=[(pc+i)&8191 for i in range(len(raw))],data=list(raw)))
    markers={name:p.labels[name]for name in ('pre_dma','target','return_pc','done')}
    markers.update(post_ack=h1.labels['post_ack'],handler1=h1.start,handler2=h2.start)
    return bytes(rom),markers,sources

def expected_vram():
    result=[0]*32768
    for index in range(2):result[SAT+4*index:SAT+4*index+4]=[64,32,512,0x3000]
    for row in range(64):result[0x4000+(row//16)*128+(row&15)]=65535
    for index,value in enumerate((FIRST,PAYLOAD,TAIL)):result[DATA+index]=value
    return result

def expected_wram(case):
    markers=program(case)[1];result=[0]*8192
    a=0xa6 if case['access']=='high'else 2
    flags=129 if case['access']=='high'else 1
    result[0x11]=1;result[0x12]=int(case['policy']=='retain')
    result[0x14]=4 if case['source']=='raster'else 1
    result[0x15]=a;result[0x16]=12
    ret=markers['return_pc']+int(case['policy']=='retain')
    result[508:512]=[a,flags,ret&255,ret>>8]
    if case['access']=='tai':result[512:514]=[0x5c,0xa6]
    return result

def fixtures(out):
    from pcerecomp.project import ABI
    from pcerecomp.emitter import emit_capture
    out=Path(out);out.mkdir(parents=True,exist_ok=True);fixture=out/'fixture';rows=[];all_sources={}
    for case in cases():
        rom,markers,plan=program(case);row=dict(case,**markers,rom=case['id']+'.pce',sha256=hashlib.sha256(rom).hexdigest());rows.append(row)
        (out/row['rom']).write_bytes(rom)
        for source in plan:all_sources[json.dumps(source,sort_keys=True)]=dict(source,native_hits=0,interpreted_hits=1)
    sources=list(all_sources.values());emit_capture(dict(schema=1,runtime_abi=ABI,capacity=len(sources),dropped_instructions=0,
        unreadable_instructions=0,retired_instructions=len(sources),complete=True,observations=sources),fixture,single_unit=True)
    (out/'data.bin').write_bytes(bytes(pattern())+bytes(3*2048));(out/'data.cue').write_text('FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n',encoding='ascii')
    fields='source access policy divisor vce pre_dma target return_pc post_ack done handler1 handler2'.split()
    header=['#pragma once','#include <string>','#include <stdexcept>','struct ActiveIrqCase{const char*id;unsigned '+','.join(fields)+';};','inline constexpr ActiveIrqCase active_irq_cases[]{']
    for r in rows:
        values=dict(r,source=SOURCES.index(r['source']),access=ACCESS.index(r['access']),policy=POLICIES.index(r['policy']))
        header.append('{"'+r['id']+'",'+','.join(str(values[key])for key in fields)+'},')
    header+=['};','inline const ActiveIrqCase& active_irq_case(const std::string&id){for(const auto&c:active_irq_cases)if(id==c.id)return c;throw std::runtime_error("Unknown active IRQ recipe");}']
    (fixture/'active_irq_fixture.hpp').write_text('\n'.join(header)+'\n',encoding='utf-8')
    (fixture/'fixture.json').write_text(json.dumps(dict(cases=rows,source_plan=sources,execution_evidence=False),indent=2)+'\n');return fixture

if __name__=='__main__':fixtures(sys.argv[1])
