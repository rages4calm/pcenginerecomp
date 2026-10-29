"""Authored READ-fed IRQ2 edges inside whole HuC6280 block instructions."""
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.dma_irq_checkpoint_fixture import Program as BaseProgram, pattern, expected_ram

MPR=(255,248,0,0,0,0,0,0)
FAMILIES=('tii','tdd','tin','tia','tai')
OPCODES=(0x73,0xc3,0xd3,0xe3,0xf3)
LENGTH=1023
LIMIT=1500000
KINDS=('enabled','masked')

def cases():
    return [dict(id=f'{family}-{kind}-div{div}',family=family,kind=kind,mode=2,divisor=div,loops=210 if div==3 else 56)
            for div in (3,12) for family in FAMILIES for kind in KINDS]

def rom_pattern():return [(i*29+(i>>6)*11+0x27)&255 for i in range(LENGTH)]

class Program(BaseProgram):
    def add(self,name,value=None):
        if name=='dex':
            self.ops[self.pc]=b'\xca';self.code.append(0xca)
        elif name in FAMILIES:
            source,destination=0xe800,0x2200
            if name=='tdd':source+=LENGTH-1;destination+=LENGTH-1
            raw=bytes([OPCODES[FAMILIES.index(name)]])+source.to_bytes(2,'little')+destination.to_bytes(2,'little')+LENGTH.to_bytes(2,'little')
            self.ops[self.pc]=raw;self.code.extend(raw)
        else:super().add(name,value)

def scratch(case):
    result=[0]*LENGTH;data=rom_pattern();family=case['family']
    if family in ('tii','tdd'):result=data
    elif family=='tin':result[0]=data[-1]
    elif family=='tia':result[0],result[1]=data[-1],data[-2]
    else:result=[data[i&1]for i in range(LENGTH)]
    return result

def expected_wram(case):
    result=bytearray(8192);result[18]=int(case['kind']=='enabled')
    result[0x200:0x200+LENGTH]=bytes(scratch(case))
    result[508:512]=bytes([2 if case['kind']=='enabled'else 0,1,2,0])
    return list(result)

def program(case):
    p=Program(0xe000)
    for op in [('sei',),('lda',0),('tam',0xfd),('lda',248),('tam',2),('lda',255),('tam',1)]:p.add(*op)
    if case['divisor']==3:p.add('csh')
    p.add('ldx',255);p.add('txs');p.write(0x1402,7);p.write(0x1802,0)
    p.write(0x180d,128);p.write(0x180d,0)
    p.write(0x1808,254);p.write(0x1809,255);p.write(0x180d,3);p.write(0x180d,0)
    p.write(0x1800,0)
    for i,value in enumerate((8,0,0,0,1,0)):
        p.poll('command'+str(i),0x58,0x50);p.write(0x1801,value);p.ack(0)
    # Independent negative/control: empty-buffer mode1 is immediately disabled.
    p.write(0x180b,1);p.add('load',0x180b);p.add('sta',0x2013)
    p.write(0x1802,12);p.write(0x1402,6 if case['kind']=='enabled'else 7)
    p.add('ldx',case['loops']);p.add('cli');p.add('nop');p.add('lda',2)
    p.label('pre_arm');p.add('sta',0x180b)
    p.label('block');p.add(case['family']);p.add('dex');p.add('bne','block')
    p.poll('status',0x58,0x58)
    p.label('write_done');p.add('load',0x180c);p.add('and',4);p.add('cmp',0);p.add('bne','write_done')
    p.label('post_dma');p.write(0x180b,0)
    p.add('load',0x1801);p.add('sta',0x2010);p.ack(0)
    p.poll('message',0x78,0x78);p.add('load',0x1801);p.add('sta',0x2011);p.ack(0)
    p.poll('free',0x80,0);p.add('sei');p.write(0x1402,7);p.write(0x1802,0)
    p.label('done');p.add('bra','done');p.finish()
    h=Program(0xf800);h.add('pha');h.add('inc',0x2012);h.write(0x1402,7);h.add('pla');h.add('rti');h.finish()
    rom=bytearray([0xea]*262144)
    for piece in(p,h):rom[piece.start&8191:(piece.start&8191)+len(piece.code)]=piece.code
    rom[0x800:0x800+LENGTH]=bytes(rom_pattern())
    for address,target in((0xfff6,0xf800),(0xfff8,0xf880),(0xfffa,0xf880),(0xfffe,0xe000)):
        rom[address&8191:(address&8191)+2]=target.to_bytes(2,'little')
    rom[0x1880]=0x40
    mapping=[0]*8;a=0;sources=[]
    for pc,raw in sorted(p.ops.items()):
        sources.append(dict(pc=pc,mpr=list(mapping),physical=[(mapping[(pc+i)>>13]<<13)|((pc+i)&8191)for i in range(len(raw))],data=list(raw)))
        if raw[0]==0xa9:a=raw[1]
        if raw[0]==0x53:
            for page in range(8):
                if raw[1]&(1<<page):mapping[page]=a
    assert tuple(mapping)==MPR
    for pc,raw in h.ops.items():sources.append(dict(pc=pc,mpr=list(MPR),physical=[(pc+i)&8191 for i in range(len(raw))],data=list(raw)))
    return bytes(rom),dict(pre_arm=p.labels['pre_arm'],block=p.labels['block'],post_dma=p.labels['post_dma'],done=p.labels['done'],handler=0xf800),sources

def fixtures(out):
    from pcerecomp.project import ABI
    from pcerecomp.emitter import emit_capture
    out=Path(out);out.mkdir(parents=True,exist_ok=True);fixture=out/'fixture';all_sources={};rows=[]
    for case in cases():
        rom,markers,sources=program(case);row=dict(case,**markers,rom=case['id']+'.pce',sha256=hashlib.sha256(rom).hexdigest());rows.append(row);(out/row['rom']).write_bytes(rom)
        for s in sources:all_sources[json.dumps(s,sort_keys=True)]=dict(s,native_hits=0,interpreted_hits=1)
    sources=list(all_sources.values());capture=dict(schema=1,runtime_abi=ABI,capacity=len(sources),dropped_instructions=0,unreadable_instructions=0,retired_instructions=len(sources),complete=True,observations=sources)
    emit_capture(capture,fixture,single_unit=True)
    (out/'data.bin').write_bytes(bytes(pattern())+bytes(3*2048));(out/'data.cue').write_text('FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n',encoding='ascii')
    header=['#pragma once','#include <string>','#include <stdexcept>','struct BlockDmaCase{const char* id;unsigned kind,family,divisor,loops,pre_arm,block,post_dma,done,handler;};','inline constexpr BlockDmaCase block_dma_cases[]{']
    for r in rows:header.append('{"'+r['id']+'",'+','.join(str(v)for v in(KINDS.index(r['kind']),FAMILIES.index(r['family']),r['divisor'],r['loops'],r['pre_arm'],r['block'],r['post_dma'],r['done'],r['handler']))+'},')
    header+=['};','inline const BlockDmaCase& block_dma_case(const std::string& id){for(const auto&c:block_dma_cases)if(id==c.id)return c;throw std::runtime_error("Unknown block DMA recipe");}']
    (fixture/'block_dma_irq_fixture.hpp').write_text('\n'.join(header)+'\n');(fixture/'fixture.json').write_text(json.dumps(dict(cases=rows,source_plan=sources,execution_evidence=False),indent=2)+'\n');return fixture

if __name__=='__main__':fixtures(sys.argv[1])
