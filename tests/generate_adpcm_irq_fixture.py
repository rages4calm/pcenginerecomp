"""Authored guest-created ADPCM HALF/END and CPU IRQ boundary fixtures."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from generate_irq_device_fixture import Program,encode,source
STEPS=48
COLUMNS=['pc','a','x','y','sp','p','clock_divisor','elapsed_ticks',
         *['mpr'+str(i)for i in range(8)],'mpr_latch','irq_entries','irq_vector','rti_steps',
         'cpu_mask','irq_requests','vdc_status','cd_enable','cd_active','irq1_count','irq2_count',
         'control','address','read_address','write_address','length','half_irq','end_irq','playing','adpcm_status']


def definitions():
    cases=[]
    for speed,label in ((3,'high'),(12,'low')):
        for kind in ('half-read','half-play','end-read','both-write','threshold-read'):
            cases.append(dict(id=f'{kind}-{label}',speed=speed,source=kind,kind='normal'))
        for src in ('half-read','end-read'):
            for kind in ('cpu-mask','cd-mask','i-mask','disable-retain','reset-retain','reload-retain','held-rti'):
                cases.append(dict(id=f'{src}-{kind}-{label}',speed=speed,source=src,kind=kind))
        for mask in range(4):
            cases.append(dict(id=f'priority-mask{mask}-{label}',speed=speed,source='both-write',kind='priority',mask=4|mask))
        cases.append(dict(id=f'wrapped-stack-{label}',speed=speed,source='end-read',kind='normal',sp=1))
    for c in cases:
        c.setdefault('mask',5 if c['kind']=='cpu-mask'else 4)
        c.setdefault('sp',255)
        c['enable']=0 if c['kind']=='cd-mask'else 8 if c['source']=='end-read'else 12 if c['source']=='both-write'else 4
        c['acc']=0 if c['kind']=='disable-retain'else 128 if c['kind']=='reset-retain'else 16 if c['kind']=='reload-retain'else 1
    return cases


def make_program(c):
    p=Program(0xE000)
    for op in [('sei',),('lda',0),('tam',0xFD),('lda',248),('tam',2),('lda',0),('sta',0x2000),
               ('tii',0x2000,0x2001,8191),('lda',255),('tam',1),('ldx',c['sp']),('txs',),('clx',)]:p.add(*op)
    if c['speed']==3:p.add('csh')
    for value,port in ((7,0x1402),(0,0x1802),(128,0x180D),(0,0x180D)):
        p.add('lda',value);p.add('sta',port)
    length=32769 if c['source']in('half-play','threshold-read')else 32768 if c['source']=='half-read'else 0
    for value,port in ((length&255,0x1808),(length>>8,0x1809),(16,0x180D),(0,0x180D)):
        p.add('lda',value);p.add('sta',port)
    if c['source']=='half-play':
        p.add('lda',15);p.add('sta',0x180E);p.add('lda',32);p.add('sta',0x180D)
        p.delay(80 if c['speed']==3 else 15)
        p.add('lda',0);p.add('sta',0x180D)
    elif c['source']=='both-write':
        p.add('lda',0x5A);p.add('sta',0x180A);p.delay(8)
    else:p.add('load',0x180A);p.delay(8)
    if c['kind']=='priority':
        for number,value in ((15,2),(16,0),(17,1),(18,0)):p.register(number,value)
        p.delay(200)
    for value,port in ((c['enable'],0x1802),(c['mask'],0x1402)):
        p.add('lda',value);p.add('sta',port)
    p.add('lda',c['acc']);primer=list(p.ops.items());marker=p.pc
    p.add('nop'if c['kind']=='i-mask'else'cli')
    if c['kind']=='disable-retain':p.add('sta',0x1802)
    elif c['kind']in('reset-retain','reload-retain'):p.add('sta',0x180D)
    elif c['kind']=='normal'and c['source']in('half-read','end-read'):p.add('load',0x1803 if c['source']=='half-read'else 0x180C)
    else:p.add('nop')
    terminal=p.pc;p.add('bra',terminal)
    programs=dict(p.ops);segments=[(p.start,bytes(p.code))]
    for bit,target in ((2,0xF800),(1,0xF840)):
        h=Program(target);cell=0x2011 if bit==2 else 0x2012
        h.add('inc',cell)
        if bit==1 and c['kind']=='held-rti':
            h.add('load',cell);h.add('cmp',2);branch=h.add('bne',0)
        if bit==2:h.add('load',0)
        else:h.add('lda',128);h.add('sta',0x180D)
        if bit==1 and c['kind']=='held-rti':
            h.ops[branch]=('bne',h.pc);offset=branch-h.start;h.code[offset:offset+2]=encode(h.ops[branch],branch)
        h.add('rti');programs.update(h.ops);segments.append((h.start,bytes(h.code)))
    rom=bytearray([0xEA]*262144)
    for address,raw in segments:rom[address&8191:(address&8191)+len(raw)]=raw
    for vector,target in ((0xFFF6,0xF840),(0xFFF8,0xF800),(0xFFFA,0xF800),(0xFFFE,0xE000)):
        rom[vector&8191:(vector&8191)+2]=target.to_bytes(2,'little')
    mpr=[0]*8;a=0;primers=[]
    for pc,op in primer:
        primers.append(source(pc,mpr,op))
        if op[0]=='lda':a=op[1]
        elif op[0]=='tam':
            for i in range(8):
                if op[1]&(1<<i):mpr[i]=a
    return bytes(rom),programs,primers,marker,terminal,mpr


def literals(c,program,marker,mpr):
    ram=bytearray(8192)
    # TII saves Y,A,X at S,S-1,S-2; later self-copy primers retain A's slot.
    if c['source']=='half-play':ram[256+((c['sp']-1)&255)]=32
    if c['source']=='both-write' and c['kind']!='priority':ram[256+((c['sp']-1)&255)]=0x5A
    pc=marker;a=c['acc'];x=y=0;sp=c['sp'];p=4|(a&128)|(2 if not a else 0)
    ticks=entries=vector=rti=0;mask=c['mask'];enable=c['enable'];vstatus=16 if c['kind']=='priority'else 0
    address=32769 if c['source']in('half-play','threshold-read')else 32768 if c['source']=='half-read'else 0
    control=0;read_address=0 if c['source']=='both-write'else 1
    write_address=1 if c['source']=='both-write'else 0
    length={'half-read':32767,'half-play':32768,'end-read':0,'both-write':1,'threshold-read':32768}[c['source']]
    half=c['source']in('half-read','half-play','both-write');end=c['source']in('end-read','both-write')
    rows=[];sources=[]
    def active():return(4 if half else 0)|(8 if end else 0)
    def requests():return(2 if vstatus else 0)|(1 if active()&enable else 0)
    def nz(v):
        nonlocal p
        p=(p&~130)|(v&128)|(2 if not v else 0)
    def push(v):
        nonlocal sp
        ram[256+sp]=v&255;sp=(sp-1)&255
    def pop():
        nonlocal sp
        sp=(sp+1)&255;return ram[256+sp]
    def row(ordinal,delivered=0):
        values=[pc,a,x,y,sp,p,c['speed'],ticks,*mpr,255,entries,vector,rti,mask,requests(),vstatus,enable,
                active(),ram[17],ram[18],control,address,read_address,write_address,length,int(half),int(end),0,int(end)]
        assert len(values)==len(COLUMNS)
        return dict(ordinal=ordinal,values=values,wram_sha256=hashlib.sha256(ram).hexdigest(),irq_vector=delivered)
    initial=row(0)
    for ordinal in range(1,STEPS+1):
        op=program[pc];name=op[0];raw=encode(op,pc);sources.append(source(pc,mpr,op));sampled=0 if p&4 else requests()&~mask
        pc+=len(raw);cycles=2
        if name=='lda':a=op[1];nz(a)
        elif name=='cli':p&=~4
        elif name=='inc':
            at=op[1]&8191;ram[at]=(ram[at]+1)&255;nz(ram[at]);cycles=7
        elif name=='load':
            cycles=5
            if op[1]==0:a=vstatus;vstatus=0;cycles+=1
            elif op[1]==0x1803:a=active()|0x12
            elif op[1]==0x180C:a=int(end)
            else:a=ram[op[1]&8191]
            nz(a)
        elif name=='sta':
            cycles=5
            if op[1]==0x1802:enable=a&127
            elif op[1]==0x180D:
                control=a
                if a&16:length=address;end=False
                if a&128:address=read_address=write_address=length=0;half=end=False
            else:raise ValueError('Unauthored store')
        elif name=='cmp':v=(a-op[1])&255;p=(p&~1)|int(a>=op[1]);nz(v)
        elif name=='bne':
            if not p&2:pc=op[1];cycles=4
        elif name=='bra':pc=op[1];cycles=4
        elif name=='rti':p=pop()&~16;lo=pop();pc=lo|(pop()<<8);cycles=7;rti+=1
        elif name!='nop':raise ValueError('Unauthored opcode')
        p&=~32;ticks+=cycles*c['speed'];bit=2 if sampled&2 else 1 if sampled&1 else 0;delivered=0
        if bit:
            push(pc>>8);push(pc);push(p&~16);p=(p|4)&~40;pc=0xF800 if bit==2 else 0xF840
            entries+=1;vector=delivered=0xFFF8 if bit==2 else 0xFFF6;ticks+=8*c['speed']
        rows.append(row(ordinal,delivered))
    return initial,rows,sources


def authored_fixture():
    cases=[];images={};all_sources={}
    for definition in definitions():
        c=dict(definition);rom,program,primer,marker,terminal,mpr=make_program(c)
        initial,rows,measured=literals(c,program,marker,mpr)
        c.update(rom=c['id']+'.pce',primer_steps=len(primer),steps=STEPS,marker=marker,end_pc=terminal,
                 initial=initial,expected=rows,block_steps=sum(r['data'][0]==0x73 for r in primer),
                 rom_sha256=hashlib.sha256(rom).hexdigest())
        counts=Counter();records={}
        for r in primer+measured:
            assert list(rom[p]for p in r['physical'])==r['data']
            key=r['pc'],tuple(r['mpr']),tuple(r['physical']),tuple(r['data']);counts[key]+=1;records[key]=r
            all_sources[key]=dict(r,native_hits=0,interpreted_hits=1)
        c['source_hits']=[dict(records[k],hits=counts[k])for k in sorted(counts)]
        assert rows[-1]['values'][0]==terminal
        cases.append(c);images[c['id']]=rom
    return cases,images,list(all_sources.values())


def generate(out,emit_module=True):
    from pcerecomp.project import ABI
    out=Path(out);out.mkdir(parents=True,exist_ok=True);cases,images,sources=authored_fixture()
    def write(path,data):
        data=data.encode('utf-8')if isinstance(data,str)else data
        if not path.exists()or path.read_bytes()!=data:path.write_bytes(data)
    write(out/'authored.bin',bytes(16*2048))
    write(out/'authored.cue','FILE "authored.bin" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n')
    for c in cases:write(out/c['rom'],images[c['id']])
    if emit_module:
        from pcerecomp.emitter import emit_capture
        capture=dict(schema=1,runtime_abi=ABI,capacity=len(sources),dropped_instructions=0,unreadable_instructions=0,
                     retired_instructions=len(sources),complete=True,observations=sources)
        with TemporaryDirectory(prefix='adpcm-irq-',dir=out)as stage:
            target=Path(stage)/'module';emit_capture(capture,target,single_unit=True)
            for path in target.iterdir():write(out/path.name,path.read_bytes())
    header=['#pragma once','#include <array>','#include <cstdint>','#include <string>','#include <stdexcept>','#include <vector>',
            f'struct AdpcmIrqLiteral {{ std::array<std::uint64_t,{len(COLUMNS)}> values; const char* wram_sha256; unsigned irq_vector; }};',
            'struct AdpcmIrqCase {const char* id;unsigned primer_steps,steps,marker,end_pc,block_steps;AdpcmIrqLiteral initial;const AdpcmIrqLiteral* rows;};']
    def lit(row):return'{{'+','.join(map(str,row['values']))+'},"'+row['wram_sha256']+'",'+str(row['irq_vector'])+'}'
    for i,c in enumerate(cases):header.append(f'inline constexpr AdpcmIrqLiteral adpcm_irq_{i}[]'+'{'+','.join(map(lit,c['expected']))+'};')
    header.append('inline constexpr AdpcmIrqCase adpcm_irq_cases[]{')
    for i,c in enumerate(cases):header.append('{"'+c['id']+'",'+','.join(str(c[k])for k in('primer_steps','steps','marker','end_pc','block_steps'))+','+lit(c['initial'])+f',adpcm_irq_{i}'+'},')
    header.extend(['};','inline const AdpcmIrqCase& adpcm_irq_case(const std::string& id){for(const auto& c:adpcm_irq_cases)if(id==c.id)return c;throw std::runtime_error("Unknown ADPCM IRQ case");}',
                   'inline std::vector<std::uint8_t> adpcm_irq_rom(const AdpcmIrqCase& c){std::vector<std::uint8_t> rom(262144,0xEA);'])
    for c in cases:
        raw=images[c['id']];header.append('if(std::string(c.id)=="'+c['id']+'"){'+''.join(f'rom[{i}]={v};'for i,v in enumerate(raw)if v!=0xEA)+'return rom;}')
    header.append('throw std::runtime_error("Unknown authored ROM");}')
    write(out/'adpcm_irq_fixture.hpp','\n'.join(header)+'\n')
    result=dict(schema=1,runtime_abi=ABI,cases=cases,literal_columns=COLUMNS,cue='authored.cue',
                source_plan='Independent authored finite instruction/IRQ ledger, not an execution capture.')
    write(out/'fixture.json',json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':generate(sys.argv[1])



