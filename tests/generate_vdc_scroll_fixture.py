"""Authored guest scroll writes with an independent integer phase planner.

The two engine prefixes keep their documented CSH timing difference. Neither
captured clocks nor observed scroll values supply expected results.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from generate_irq_device_fixture import encode as shared_encode

LINE=1365
FRAME=LINE*262


def encode(op,pc=0):
    if op[0] in ('st0','st1','st2'):
        return bytes([{'st0':3,'st1':0x13,'st2':0x23}[op[0]],op[1]])
    if op[0]=='sxy':return bytes([2])
    if op[0]=='tia':return bytes([0xE3,op[1]&255,op[1]>>8,op[2]&255,op[2]>>8,op[3]&255,op[3]>>8])
    return shared_encode(op,pc)


class Program:
    def __init__(self):self.ops=[];self.code=bytearray();self.pc=0xE000
    def add(self,*op):
        self.ops.append((self.pc,op));raw=encode(op,self.pc);self.code.extend(raw);self.pc+=len(raw)
    def register(self,number,value):
        for address,byte in ((0,number),(2,value&255),(3,value>>8)):
            self.add('lda',byte);self.add('sta',address)
    def delay(self,n):self.add('tii',0x2200,0x2200,n)


def ticks(p,profile):
    total=0;d=12
    for _,op in p.ops:
        name=op[0]
        if name=='csh':total+=27 if profile=='runtime' else 9;d=3;continue
        c=2
        if name=='tam':c=5
        elif name=='sta':c=5+int(op[1]<0x800)
        elif name=='tii':c=17+6*op[3]
        elif name=='tia':c=17+8*op[3] # Two real fixed VDC cycles per byte.
        elif name in ('st0','st1','st2'):c=5
        elif name=='sxy':c=3
        total+=c*d
    return total


def pad(p,cycles):
    if cycles<0 or cycles==1:raise ValueError('Unrepresentable authored phase padding')
    while cycles>36050:p.delay(6000);cycles-=36017
    if cycles>=23:
        n=(cycles-17)//6
        while n and cycles-(17+6*n)==1:n-=1
        if n:p.delay(n);cycles-=17+6*n
    if cycles&1:p.add('sxy');cycles-=3
    for _ in range(cycles//2):p.add('nop')


def definitions():
    # Events are real STn port effects at authored master-clock positions.
    cases=[]
    def add(name,events,*,d=4,hsr=0x0202,x=0,y=47,counter=47,pending=False):
        cases.append(dict(id=name,divider=d,hsr=hsr,events=events,x=x,y=y,counter=counter,pending=pending))
    for phase,x,label in ((54,8,'before'),(57,8,'window'),(60,0,'after')):
        add('bxr-'+label,[['st1',8,phase]],x=x)
    add('bxr-high-window',[['st2',1,57]],x=256)
    add('bxr-low-window-high-late',[['st1',8,57],['st2',1,72]],x=8)
    for phase,y,pending,label in ((78,4,False,'before'),(81,4,False,'window'),(84,47,True,'after')):
        add('byr-'+label,[['st1',3,phase]],hsr=0x0302,y=y,counter=y,pending=pending)
    add('byr-high-window',[['st2',1,81]],hsr=0x0302,y=257,counter=257)
    add('byr-pair-valid',[['st1',3,51],['st2',0,66]],y=4,pending=True)
    add('byr-pair-exact-gap',[['st1',3,51],['st2',0,75]],y=4,pending=True)
    add('byr-pair-expired-gap',[['st1',3,51],['st2',0,78]],pending=True)
    add('byr-pair-expired-low',[['st1',3,66],['st2',0,81]],pending=True)
    add('byr-high-only',[['st2',0,66]],pending=True)
    add('byr-bxr-inhibits',[['st1',0,15],['st0',8,30],['st1',3,51],['st2',0,66]],pending=True)
    add('byr-pair-outside-hsw',[['st1',3,84],['st2',0,99]],hsr=0x0302,pending=True)
    add('byr-vce3-pair-valid',[['st1',3,63],['st2',0,78]],d=3,y=4,pending=True)
    add('byr-vce3-pair-expired',[['st1',3,63],['st2',0,84]],d=3,pending=True)
    add('byr-vce2-pair-expired',[['st1',3,27],['st2',0,42]],d=2,pending=True)
    return cases


def prefix(case):
    p=Program()
    for op in [('sei',),('lda',0),('tam',0xFD),('lda',248),('tam',2),
               ('lda',1),('tam',32),('lda',255),('tam',1)]:p.add(*op)
    p.add('lda',{4:0,3:1,2:2}[case['divider']]);p.add('sta',0x400)
    for reg,val in ((5,0),(9,0),(10,case['hsr']),(11,0x7F1D),(12,0x0F02),(13,239),(14,2),(15,0)):
        p.register(reg,val)
    # Actual slow-CPU alternating port writes initialize all BAT/pattern data.
    p.register(0,0);p.add('st0',2);p.add('tia',0xA000,2,2048)
    p.register(0,4096);p.add('st0',2);p.add('tia',0xA800,2,64)
    p.add('csh');p.register(5,128)
    selected=7 if case['id'].startswith('bxr-') or case['id']=='byr-bxr-inhibits' else 8
    p.add('st0',selected)
    for _ in range(8):p.delay(6000)
    return p


def payload():
    data=bytearray(8192)
    for y in range(32):
        for x in range(32):data[2*(y*32+x):2*(y*32+x)+2]=(256+(x&1)).to_bytes(2,'little')
    for tile in range(2):
        for y in range(8):
            word=0x00FF if (tile^(y&1))==0 else 0xFF00
            off=2048+tile*32+y*2;data[off:off+2]=word.to_bytes(2,'little')
    return data


def fixture():
    cases=[];roms={};sources={}
    for definition in definitions():
        case=deepcopy(definition);base=prefix(case)
        frame=max(ticks(base,profile)for profile in ('runtime','gear'))//FRAME+2
        origin=frame*FRAME+64*LINE
        case['frame']=frame;case['sample_ticks']=origin+300;case['expected_pixel']=1 if (((case['x']//8)&1)^(case['y']&1))==0 else 2
        for profile in ('runtime','gear'):
            p=deepcopy(base);actions=[]
            for name,value,phase in case['events']:
                delta=origin+phase-6-ticks(p,profile)
                if delta%3:raise ValueError('Guest effect off three-tick CPU lattice')
                pad(p,delta//3);actions.append(dict(index=len(p.ops),pc=p.pc,effect_ticks=origin+phase,operation=name,value=value))
                p.add(name,value)
            delta=case['sample_ticks']-ticks(p,profile)
            assert delta>=0 and delta%3==0;pad(p,delta//3)
            assert ticks(p,profile)==case['sample_ticks'] and p.pc<0xFFF6
            rom=bytearray([0xEA]*262144);rom[p.ops[0][0]&8191:(p.ops[0][0]&8191)+len(p.code)]=p.code
            rom[8190:8192]=(0xE000).to_bytes(2,'little');rom[8192:16384]=payload()
            name=case['id']+'-'+profile+'.pce';roms[name]=bytes(rom)
            case[profile]=dict(rom=name,steps=len(p.ops),end_pc=p.pc,actions=actions,rom_sha256=hashlib.sha256(rom).hexdigest())
            if profile=='runtime':
                mapping=[0]*8;a=0;case[profile]['sources']=[]
                for pc,op in p.ops:
                    raw=list(encode(op,pc));item=dict(pc=pc,mpr=list(mapping),physical=[(mapping[((pc+i)&65535)>>13]<<13)|((pc+i)&8191)for i in range(len(raw))],data=raw,native_hits=0,interpreted_hits=1)
                    sources[(pc,tuple(mapping),tuple(raw))]=item
                    case[profile]['sources'].append(item)
                    if op[0]=='lda':a=op[1]
                    if op[0]=='tam':
                        for i in range(8):
                            if op[1]&(1<<i):mapping[i]=a
        cases.append(case)
    return cases,roms,list(sources.values())


def write_changed(path,data):
    path=Path(path);data=data.encode('utf-8')if isinstance(data,str)else data
    if path.exists()and path.read_bytes()==data:return
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)


def generate(out,emit_module=True):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);cases,roms,sources=fixture()
    for name,data in roms.items():write_changed(out/name,data)
    write_changed(out/'authored.bin',bytes(16*2048))
    write_changed(out/'authored.cue','FILE "authored.bin" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n')
    if emit_module:
        from pcerecomp.emitter import emit_capture
        from pcerecomp.project import ABI
        with TemporaryDirectory(prefix='scroll-module-',dir=out.resolve())as temporary:
            stage=Path(temporary)/'module'
            emit_capture(dict(schema=1,runtime_abi=ABI,capacity=len(sources),complete=True,dropped_instructions=0,unreadable_instructions=0,retired_instructions=len(sources),observations=sources),stage,partition_size=256,single_unit=False)
            for path in stage.iterdir():write_changed(out/'module'/path.name,path.read_bytes())
    header=['#pragma once','#include <array>','#include <string>','#include <vector>','#include <stdexcept>',
        'struct ScrollAction { unsigned step; unsigned long long effect; unsigned port,value; };',
        'struct ScrollCase { const char* id; unsigned steps,end_pc,gear_steps,gear_end_pc; unsigned long long ticks; unsigned x,y,counter,pixel; bool pending; const ScrollAction* actions; const ScrollAction* gear_actions; unsigned count; };']
    for i,c in enumerate(cases):
        for profile in ('runtime','gear'):
            a=c[profile]['actions'];header.append('inline constexpr ScrollAction scroll_actions_'+str(i)+'_'+profile+'[]{'+','.join('{'+','.join(map(str,(v['index'],v['effect_ticks'],{'st0':0,'st1':2,'st2':3}[v['operation']],v['value'])))+'}'for v in a)+'};')
    header.append('inline constexpr ScrollCase scroll_cases[]{')
    for i,c in enumerate(cases):header.append('{"'+c['id']+'",'+','.join(map(str,(c['runtime']['steps'],c['runtime']['end_pc'],c['gear']['steps'],c['gear']['end_pc'],c['sample_ticks'],c['x'],c['y'],c['counter'],c['expected_pixel'])))+','+str(c['pending']).lower()+',scroll_actions_'+str(i)+'_runtime,scroll_actions_'+str(i)+'_gear,'+str(len(c['events']))+'},')
    header+=['};','inline std::vector<unsigned char> scroll_rom(const std::string& name){std::vector<unsigned char> rom(262144,0xEA);']
    for c in cases:
        data=roms[c['runtime']['rom']];changed=[(i,v)for i,v in enumerate(data)if v!=0xEA]
        header.append('if(name=="'+c['id']+'"){'+''.join('rom['+str(i)+']='+str(v)+';'for i,v in changed)+'return rom;}')
    header+=['throw std::runtime_error("Unknown authored scroll case");}']
    write_changed(out/'vdc_scroll_fixture.hpp','\n'.join(header)+'\n')
    from pcerecomp.project import ABI
    metadata=dict(schema=1,runtime_abi=ABI,cases=cases,source_plan=sources,scope='Authored real guest port writes; independent integer phases and scroll/pixel literals. Separate CSH prefix timing retained; no captured goldens.')
    write_changed(out/'fixture.json',json.dumps(metadata,indent=2)+'\n');return metadata


if __name__=='__main__':generate(sys.argv[1])
