"""Authored VDC-DMA/READ-fed ADPCM overlap, never retail code or state."""
from pathlib import Path
import hashlib
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.dma_irq_checkpoint_fixture import Program as BaseProgram,pattern,expected_ram

MPR=(255,248,0,0,0,0,0,0)
ACCESS=('high','tai')
POLICIES=('retain','mask')
OPCODES=(0x73,0xf3)
WORDS=4096
PAYLOAD,TAIL=0xa65c,0x5aa5
LIMIT=1500000

def cases():
    return [dict(id=f'{access}-{policy}-div{div}-vce{vce}',access=access,policy=policy,divisor=div,vce=vce,loops=189 if div==3 else 47)
            for div in(3,12)for vce in(4,3,2)for access in ACCESS for policy in POLICIES]

class Program(BaseProgram):
    def add(self,name,value=None):
        if name=='dex':self.ops[self.pc]=b'\xca';self.code.append(0xca)
        elif name in('tii','tai'):
            src,dst,n=value;raw=bytes([0x73 if name=='tii'else 0xf3])+src.to_bytes(2,'little')+dst.to_bytes(2,'little')+n.to_bytes(2,'little')
            self.ops[self.pc]=raw;self.code.extend(raw)
        else:super().add(name,value)
    def delay(self,n):self.add('tii',(0x2200,0x2200,n))
    def register(self,reg,value):
        for port,byte in((0,reg),(2,value&255),(3,value>>8)):self.write(port,byte)

def program(case):
    p=Program(0xe000)
    for op in[('sei',),('lda',0),('tam',0xfd),('lda',248),('tam',2),('lda',255),('tam',1)]:p.add(*op)
    if case['divisor']==3:p.add('csh')
    p.add('ldx',255);p.add('txs');p.write(0x1402,7);p.write(0x1802,0)
    p.write(0x0400,{4:0,3:1,2:2}[case['vce']])
    for reg,value in((5,0),(10,0x7f1f),(11,0x7f7f),(15,0)):p.register(reg,value)
    for address,value in((0,PAYLOAD),(WORDS-1,TAIL)):
        p.register(0,address);p.register(2,value);p.delay(100)
    p.register(1,WORDS-1);p.delay(100)
    for _ in range(4):p.delay(6000)
    p.write(0x180d,128);p.write(0x180d,0);p.write(0x1808,254);p.write(0x1809,255);p.write(0x180d,3);p.write(0x180d,0)
    p.write(0x1800,0)
    for i,value in enumerate((8,0,0,0,1,0)):
        p.poll('command'+str(i),0x58,0x50);p.write(0x1801,value);p.ack(0)
    p.write(0x1802,12);p.write(0x1402,4);p.add('cli');p.add('nop');p.write(0x180b,2)
    p.add('ldx',case['loops']);p.label('warmup');p.delay(1023);p.add('dex');p.add('bne','warmup')
    if case['divisor']==12:p.delay(300)
    for reg,value in((15,2),(16,0),(17,0x2000)):p.register(reg,value)
    p.write(0,18);p.write(2,(WORDS-1)&255);p.add('lda',(WORDS-1)>>8)
    p.label('pre_dma');p.add('sta',3)
    p.register(1,0);p.write(0,2)
    p.label('target')
    if case['access']=='high':p.add('load',3)
    else:p.add('tai',(2,0x2200,2))
    p.label('return_pc');p.add('nop');p.add('sta',0x2015)
    p.poll('status',0x58,0x58)
    p.label('write_done');p.add('load',0x180c);p.add('and',4);p.add('cmp',0);p.add('bne','write_done')
    p.write(0x180b,0);p.add('load',0x1801);p.add('sta',0x2010);p.ack(0)
    p.poll('message',0x78,0x78);p.add('load',0x1801);p.add('sta',0x2013);p.ack(0)
    p.poll('free',0x80,0);p.add('sei');p.write(0x1402,7);p.write(0x1802,0)
    p.label('done');p.add('bra','done');p.finish()
    h1=Program(0xf800);h1.add('pha');h1.add('inc',0x2011);h1.add('load',0);h1.add('sta',0x2014)
    h1.add('load',0x1803);h1.add('and',12);h1.add('sta',0x2016)
    if case['policy']=='mask':h1.write(0x1802,0)
    h1.label('post_ack');h1.add('pla');h1.add('rti');h1.finish()
    h2=Program(0xf840);h2.add('pha');h2.add('inc',0x2012);h2.write(0x1402,7);h2.add('pla');h2.add('rti');h2.finish()
    rom=bytearray([0xea]*262144)
    for piece in(p,h1,h2):rom[piece.start&8191:(piece.start&8191)+len(piece.code)]=piece.code
    for address,target in((0xfff6,h2.start),(0xfff8,h1.start),(0xfffa,0xf880),(0xfffe,p.start)):rom[address&8191:(address&8191)+2]=target.to_bytes(2,'little')
    rom[0x1880]=0x40;mapping=[0]*8;a=0;sources=[]
    for pc,raw in sorted(p.ops.items()):
        sources.append(dict(pc=pc,mpr=list(mapping),physical=[(mapping[(pc+i)>>13]<<13)|((pc+i)&8191)for i in range(len(raw))],data=list(raw)))
        if raw[0]==0xa9:a=raw[1]
        if raw[0]==0x53:
            for page in range(8):
                if raw[1]&(1<<page):mapping[page]=a
    assert tuple(mapping)==MPR
    for piece in(h1,h2):
        for pc,raw in piece.ops.items():sources.append(dict(pc=pc,mpr=list(MPR),physical=[(pc+i)&8191 for i in range(len(raw))],data=list(raw)))
    return bytes(rom),dict(pre_dma=p.labels['pre_dma'],target=p.labels['target'],return_pc=p.labels['return_pc'],post_ack=h1.labels['post_ack'],done=p.labels['done'],handler1=h1.start,handler2=h2.start),sources

def expected_vram():
    values=[0]*32768;values[0]=values[0x2000]=PAYLOAD;values[WORDS-1]=values[0x2000+WORDS-1]=TAIL;return values

def expected_wram(case):
    markers=program(case)[1];result=[0]*8192;retain=case['policy']=='retain';a=0xa6 if case['access']=='high'else 2;p=129 if case['access']=='high'else 1
    result[0x11]=1;result[0x12]=int(retain);result[0x14]=16;result[0x15]=a;result[0x16]=12
    ret=markers['return_pc']+int(retain);result[508:512]=[a,p,ret&255,ret>>8]
    if case['access']=='tai':result[512:514]=[0x5c,0xa6]
    return result

def fixtures(out):
    from pcerecomp.project import ABI
    from pcerecomp.emitter import emit_capture
    out=Path(out);out.mkdir(parents=True,exist_ok=True);fixture=out/'fixture';rows=[];all_sources={}
    for case in cases():
        rom,markers,plan=program(case);r=dict(case,**markers,rom=case['id']+'.pce',sha256=hashlib.sha256(rom).hexdigest());rows.append(r);(out/r['rom']).write_bytes(rom)
        for source in plan:all_sources[json.dumps(source,sort_keys=True)]=dict(source,native_hits=0,interpreted_hits=1)
    sources=list(all_sources.values());emit_capture(dict(schema=1,runtime_abi=ABI,capacity=len(sources),dropped_instructions=0,unreadable_instructions=0,retired_instructions=len(sources),complete=True,observations=sources),fixture,single_unit=True)
    (out/'data.bin').write_bytes(bytes(pattern())+bytes(3*2048));(out/'data.cue').write_text('FILE "data.bin" BINARY\n TRACK 01 MODE1/2048\n INDEX 01 00:00:00\n',encoding='ascii')
    header=['#pragma once','#include <string>','#include <stdexcept>','struct VdcAdpcmCase{const char*id;unsigned access,policy,divisor,vce,loops,pre_dma,target,return_pc,post_ack,done,handler1,handler2;};','inline constexpr VdcAdpcmCase vdc_adpcm_cases[]{']
    for r in rows:header.append('{"'+r['id']+'",'+','.join(str(v)for v in(ACCESS.index(r['access']),POLICIES.index(r['policy']),r['divisor'],r['vce'],r['loops'],r['pre_dma'],r['target'],r['return_pc'],r['post_ack'],r['done'],r['handler1'],r['handler2']))+'},')
    header+=['};','inline const VdcAdpcmCase& vdc_adpcm_case(const std::string&id){for(const auto&c:vdc_adpcm_cases)if(id==c.id)return c;throw std::runtime_error("Unknown VDC ADPCM overlap recipe");}']
    (fixture/'vdc_adpcm_irq_fixture.hpp').write_text('\n'.join(header)+'\n');(fixture/'fixture.json').write_text(json.dumps(dict(cases=rows,source_plan=sources,execution_evidence=False),indent=2)+'\n');return fixture

if __name__=='__main__':fixtures(sys.argv[1])
