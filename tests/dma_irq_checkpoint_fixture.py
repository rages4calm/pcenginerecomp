"""Authored autonomous guest CD READ6/DMA/IRQ recipes; no retail code or state."""
from pathlib import Path
import hashlib
import json
from tempfile import TemporaryDirectory
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

MPR=(255,248,0,0,0,0,0,0)
KINDS=('cpu-ack','cd-ack','cpu-masked','cd-masked','i-masked')
LIMIT=1500000

def cases():
    return [dict(id=f'{kind}-mode{mode}-div{div}',kind=kind,mode=mode,divisor=div)
            for div in (3,12) for mode in (1,2) for kind in KINDS]

def pattern():return [(i*17+(i>>8)*7+0x53)&255 for i in range(2048)]

class Program:
    def __init__(self,pc):self.start=pc;self.code=bytearray();self.ops={};self.labels={};self.fixups=[]
    @property
    def pc(self):return self.start+len(self.code)
    def label(self,name):self.labels[name]=self.pc
    def add(self,name,value=None):
        one={'sei':0x78,'cli':0x58,'nop':0xea,'csh':0xd4,'pha':0x48,'pla':0x68,'rti':0x40,'txs':0x9a}
        immediate={'lda':0xa9,'ldx':0xa2,'tam':0x53,'and':0x29,'cmp':0xc9}
        absolute={'sta':0x8d,'load':0xad,'inc':0xee}
        raw=bytes([one[name]]) if name in one else bytes([immediate[name],value]) if name in immediate else bytes([absolute[name],value&255,value>>8]) if name in absolute else None
        if name in ('bne','beq','bra'):
            self.fixups.append((self.pc,value));raw=bytes([{'bne':0xd0,'beq':0xf0,'bra':0x80}[name],0])
        if raw is None:raise ValueError(name)
        self.ops[self.pc]=raw;self.code.extend(raw)
    def finish(self):
        for pc,label in self.fixups:
            delta=self.labels[label]-pc-2
            if not -128<=delta<=127:raise ValueError('Authored branch extent')
            raw=bytes([self.ops[pc][0],delta&255]);self.ops[pc]=raw;self.code[pc-self.start:pc-self.start+2]=raw
    def write(self,address,value):self.add('lda',value);self.add('sta',address)
    def poll(self,name,mask,value):
        self.label(name);self.add('load',0x1800);self.add('and',mask);self.add('cmp',value);self.add('bne',name)
    def ack(self,enable):
        self.write(0x1802,0x80|enable)
        # Real REQ fall is a required phase of the guest handshake.
        name='fall'+str(self.pc);self.poll(name,0x40,0)
        self.write(0x1802,enable)

def program(case):
    p=Program(0xe000)
    for op in [('sei',),('lda',0),('tam',0xfd),('lda',248),('tam',2),('lda',255),('tam',1)]:p.add(*op)
    if case['divisor']==3:p.add('csh')
    p.add('ldx',255);p.add('txs')
    p.write(0x1402,7);p.write(0x1802,0)
    # All measured WRAM cells and stack start from the independently configured zero reset.
    p.write(0x180d,128);p.write(0x180d,0)
    p.write(0x1808,254);p.write(0x1809,255);p.write(0x180d,3);p.write(0x180d,0)
    p.write(0x1800,0)
    for i,value in enumerate((8,0,0,0,1,0)):
        p.poll('command'+str(i),0x58,0x50);p.write(0x1801,value);p.ack(0)
    p.poll('data',0x58,0x48)
    p.write(0x1802,0 if case['kind']=='cd-masked' else 12)
    p.write(0x1402,7 if case['kind']=='cpu-masked' else 6)
    p.write(0x180b,case['mode'])
    p.label('pending');p.add('load',0x1803);p.add('and',8);p.add('cmp',8);p.add('bne','pending')
    p.label('pre_cli');p.add('nop' if case['kind']=='i-masked' else 'cli')
    p.poll('status',0x58,0x58)
    # DMA may still have a delayed final RAM write; busy bit 2 is guest-observable.
    p.label('write_done');p.add('load',0x180c);p.add('and',4);p.add('cmp',0);p.add('bne','write_done')
    p.label('post_dma');p.write(0x180b,0)
    p.add('load',0x1801);p.add('sta',0x2010);p.ack(0)
    p.poll('message',0x78,0x78);p.add('load',0x1801);p.add('sta',0x2011);p.ack(0)
    p.poll('free',0x80,0)
    p.add('sei');p.write(0x1402,7);p.write(0x1802,0)
    p.label('done');p.add('bra','done');p.finish()
    h=Program(0xf800);h.add('pha');h.add('inc',0x2012)
    h.write(0x1802 if case['kind']=='cd-ack' else 0x1402,0 if case['kind']=='cd-ack' else 7)
    h.add('pla');h.add('rti');h.finish()
    rom=bytearray([0xea]*262144)
    for piece in (p,h):rom[piece.start&8191:(piece.start&8191)+len(piece.code)]=piece.code
    for address,target in ((0xfff6,0xf800),(0xfff8,0xf880),(0xfffa,0xf880),(0xfffe,0xe000)):
        rom[address&8191:(address&8191)+2]=target.to_bytes(2,'little')
    rom[0x1880]=0x40
    mapping=[0]*8;a=0;sources=[]
    for pc,raw in sorted(p.ops.items()):
        sources.append(dict(pc=pc,mpr=list(mapping),physical=[(mapping[(pc+i)>>13]<<13)|((pc+i)&8191) for i in range(len(raw))],data=list(raw)))
        if raw[0]==0xa9:a=raw[1]
        if raw[0]==0x53:
            for page in range(8):
                if raw[1]&(1<<page):mapping[page]=a
    assert tuple(mapping)==MPR
    for pc,raw in h.ops.items():sources.append(dict(pc=pc,mpr=list(MPR),physical=[(pc+i)&8191 for i in range(len(raw))],data=list(raw)))
    return bytes(rom),dict(pre_cli=p.labels['pre_cli'],post_dma=p.labels['post_dma'],done=p.labels['done'],handler=0xf800),sources

def fixtures(out):
    from pcerecomp.project import ABI
    from pcerecomp.emitter import emit_capture
    out=Path(out);out.mkdir(parents=True,exist_ok=True);fixture=out/'fixture'
    all_sources={};rows=[]
    for case in cases():
        rom,markers,sources=program(case);row=dict(case,**markers,rom=case['id']+'.pce',sha256=hashlib.sha256(rom).hexdigest());rows.append(row)
        (out/row['rom']).write_bytes(rom)
        for s in sources:all_sources[json.dumps(s,sort_keys=True)]=dict(s,native_hits=0,interpreted_hits=1)
    sources=list(all_sources.values())
    capture=dict(schema=1,runtime_abi=ABI,capacity=len(sources),dropped_instructions=0,unreadable_instructions=0,retired_instructions=len(sources),complete=True,observations=sources)
    emit_capture(capture,fixture,single_unit=True)
    (out/'data.bin').write_bytes(bytes(pattern())+bytes(3*2048))
    (out/'data.cue').write_text('FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n',encoding='ascii')
    header=['#pragma once','#include <string>','#include <stdexcept>',
        'struct DmaIrqCase{const char* id;unsigned kind,mode,divisor,pre_cli,post_dma,done,handler;};','inline constexpr DmaIrqCase dma_irq_cases[]{']
    for r in rows:header.append('{"'+r['id']+'",'+','.join(str(v) for v in (KINDS.index(r['kind']),r['mode'],r['divisor'],r['pre_cli'],r['post_dma'],r['done'],r['handler']))+'},')
    header+=['};','inline const DmaIrqCase& dma_irq_case(const std::string& id){for(const auto& c:dma_irq_cases)if(id==c.id)return c;throw std::runtime_error("Unknown DMA IRQ recipe");}']
    (fixture/'dma_irq_checkpoint_fixture.hpp').write_text('\n'.join(header)+'\n')
    (fixture/'fixture.json').write_text(json.dumps(dict(cases=rows,source_plan=sources,execution_evidence=False),indent=2)+'\n')
    return fixture

def expected_ram():
    result=[0]*65536
    for i,v in enumerate(pattern()):result[(0xfffe+i)&65535]=v
    return result

if __name__=='__main__':
    import sys
    fixtures(sys.argv[1])
