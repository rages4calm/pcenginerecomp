"""Finite retained-VRAM-bus transactions against separately compiled Geargrafx.

All bytes are authored. Gear's original queued CPU port completion bodies are
explicitly settled between operations; this is not a VRAM-slot wait oracle.
DMA dots and sprite evaluation call original device entry points. Rendering
cases additionally use the original core scheduler with explicit geometry.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from scripts import mapper_reference as infrastructure
from scripts import hucard_reference as common
from scripts import filtered_audio_reference as reference
sha=reference.sha


def pattern(i):return ((i*73)^(i>>3)^0xA53C)&65535


def firmware():
    ops=[]
    def add(kind,*values):
        data={'lda':(0xA9,*values),'tam':(0x53,*values),'st0':(3,*values),
              'st1':(0x13,*values),'st2':(0x23,*values),
              'read':(0xAD,values[0]&255,values[0]>>8),
              'store':(0x8D,values[0]&255,values[0]>>8)}[kind]
        ops.append((kind,values,bytes(data)))
    def reg(index,value):add('st0',index);add('st1',value&255);add('st2',value>>8)
    for value,mask in ((255,1),(248,2),(255,16)):add('lda',value);add('tam',mask)
    slot=0
    for inc in (0,1,2,3):
        reg(5,inc<<11);reg(1,0x7FFE);add('st0',2)
        for address in (2,0x8003,2,3,2,0x8003):
            add('read',address);add('store',0x2000+slot);slot+=1
        reg(0,0x8000);reg(2,0xA55A);reg(1,0xFFFF);add('st0',2)
        for address in (2,3,2):add('read',address);add('store',0x2000+slot);slot+=1
    reg(0,0x7FFF);reg(2,0x1234);reg(1,0x7FFF);add('st0',2)
    for address in (2,3,2):add('read',address);add('store',0x2000+slot);slot+=1
    raw=bytearray([0xEA]*262144);code=b''.join(o[2]for o in ops)
    raw[0x100:0x100+len(code)]=code;raw[8190:8192]=b'\x00\xE1'
    return bytes(raw),ops


def plans():
    # Exercise every driven address and its unconnected-high-bit counterpart,
    # retaining the previous *word*, never mirroring high-half storage.
    all_addresses=[('r',0)]
    for address in range(32768):all_addresses.extend((('q',address),('q',address|32768)))
    cases=[dict(id='all-65536-addresses',operations=all_addresses)]
    for fast in (0,1):
        ops=[('r',fast),('s',)]
        for address in (0x8000,0xFFFF,0,0x8000,1,0x7FFF,0x8001,0xFFFF):ops.extend((('q',address),('s',)))
        for increment in (0,1,2,3):
            ops.extend((('w',5,increment<<11),('w',1,0x7FFF),('s',),('w',0,0x8000),('w',2,0x4321),('s',),('w',2,0xFF00),('p',2),('p',3),('s',)))
        cases.append(dict(id='ports-'+str(fast),operations=ops))
    for source,destination,control,length in ((0x7FFF,0x10,0,4),(0x8001,0x20,4,4),(2,0x8000,0,4),(0xFFFF,0xFFFF,0,3),(0,0,12,3)):
        ops=[('r',0),('q',123),('w',15,control),('w',16,source),('w',17,destination),('w',18,length-1),('s',)]
        for _ in range(length):ops.extend((('d',3),('s',),('d',1),('s',)))
        cases.append(dict(id=f'dma-{source:x}-{destination:x}-{control}',operations=ops))
    for source in (0x7FFF,0x8000,0xFFFF):
        cases.append(dict(id='sat-'+hex(source),operations=[('r',0),('q',123),('w',19,source),('b',),('d',4),('s',),('d',1016),('s',),('d',4),('s',)]))
    for count in (1,2,16,17):
        for flags in (0,0x100,0x900):
            ops=[('r',0),('q',123)]
            for i in range(count):
                # First valid sprite updates the latch; later high-half rows
                # consume it. Offscreen sprites still evaluate their pattern.
                for offset,value in enumerate((64,0 if i%2 else 32,2 if i==0 else 0x400,flags)):ops.append(('t',i*4+offset,value))
            ops.extend((('f',),('s',)));cases.append(dict(id=f'sprite-{count}-{flags:x}',operations=ops))
    frame=1365*262*2
    for control in (0,1,2):
        geometry={0:(0x0202,0x041F),1:(0x0303,0x042B),2:(0x0B01,0x073F)}[control]
        for enabled in (0,0x80):
            ops=[('r',0),('z',0x16EF),('e',control),('w',5,enabled),('w',10,geometry[0]),('w',11,geometry[1]),('w',12,0x0F02),('w',14,4),('g',1000),('s',),('g',frame+21*1365+1200-1000),('s',)]
            cases.append(dict(id=f'background-{control}-{enabled}',operations=ops))
    count=len(firmware()[1])
    for fast in (0,1):cases.append(dict(id='actual-cpu-'+str(fast),operations=[('r',fast),('i',count),('s',),('c',),('m',)]))
    return cases


def serialize(cases):return '\n'.join(' '.join(map(str,op))for case in cases for op in case['operations'])+'\n'


def fnv(words):
    value=14695981039346656037
    for word in words:
        for byte in (word&255,word>>8):value=((value^byte)*1099511628211)&((1<<64)-1)
    return value


class Model:
    def __init__(self):
        self.vram=[pattern(i)for i in range(32768)];self.sat=[0]*256;self.r=[0]*20;self.r[11]=31;self.r[13]=239
        self.latch=0;self.buffer=65535;self.selected=0;self.status=0;self.pending=0;self.sat_pending=0;self.sat_armed=False;self.source=self.destination=0;self.ram=[0]*64;self.a=0
    def word(self,address):
        if address<32768:self.latch=self.vram[address]
        return self.latch
    def prefetch(self):self.buffer=self.word(self.r[1]);self.r[1]=(self.r[1]+(1,32,64,128)[(self.r[5]>>11)&3])&65535
    def write(self,port,value):
        if port==0:self.selected=value&31;return
        if port<2 or self.selected>=20:return
        index=self.selected;self.r[index]=((self.r[index]&255)|(value<<8))if port==3 else ((self.r[index]&65280)|value)
        if port==2:return
        if index==1:self.prefetch()
        elif index==2:
            if self.r[0]<32768:self.vram[self.r[0]]=self.r[2]
            self.r[0]=(self.r[0]+(1,32,64,128)[(self.r[5]>>11)&3])&65535
        elif index==18:self.pending=(self.r[18]+1)*4;self.source=self.r[16];self.destination=self.r[17]
        elif index==19:self.sat_armed=True
    def reg(self,index,value):self.write(0,index);self.write(2,value&255);self.write(3,value>>8)
    def port(self,index):
        if index==0:value=self.status;self.status=0;return value
        if index==1:return 0
        value=(self.buffer>>(8 if index==3 else 0))&255
        if index==3 and self.selected==2:self.prefetch()
        return value
    def dots(self,count):
        for _ in range(count):
            if self.sat_pending:
                self.sat_pending-=1
                if self.sat_pending%4==0:
                    i=255-self.sat_pending//4;self.sat[i]=self.word((self.r[19]+i)&65535)
                    if self.sat_pending==0 and self.r[15]&1:self.status|=8
            elif self.pending:
                self.pending-=1
                if self.pending%4==0:
                    if self.destination<32768:self.vram[self.destination]=self.word(self.source)
                    self.source=(self.source+(-1 if self.r[15]&4 else 1))&65535;self.destination=(self.destination+(-1 if self.r[15]&8 else 1))&65535
                    self.r[16:19]=[self.source,self.destination,(self.pending//4-1)&65535]
                    if self.pending==0 and self.r[15]&2:self.status|=16
    def sprites(self):
        rows=[]
        for i in range(64):
            y,x,word,flags=self.sat[i*4:i*4+4];height=(16,32,64,64)[(flags>>12)&3]
            relative=64-(y&1023)
            if not 0<=relative<height:continue
            if len(rows)==16:break
            row=height-1-relative if flags&0x8000 else relative
            pattern=(word>>1)&(1023,1021,1017,1017)[(flags>>12)&3]
            if flags&256:pattern&=1022
            base=pattern*64+(row//16)*128+(row&15);flip=bool(flags&0x800)
            for half in range(2 if flags&256 else 1):
                if len(rows)==16:break
                offset=(64 if (half==0 and flip)or(half==1 and not flip)else 0)if flags&256 else 0
                rows.append([(x&1023)-32+half*16+1024,i,int(flip),*[self.word((base+offset+p*16)&65535)for p in range(4)]])
        return [len(rows),*[v for row in rows for v in row]]
    def guest(self,count):
        for kind,values,_ in firmware()[1][:count]:
            value=values[0]
            if kind=='lda':self.a=value
            elif kind=='read':self.a=self.port(value&3)
            elif kind=='store':self.ram[value-0x2000]=self.a
            elif kind.startswith('st'):self.write({'st0':0,'st1':2,'st2':3}[kind],value)
    def device(self):return [self.latch,self.buffer,self.selected,self.status,self.sat_pending,self.pending,*self.r,fnv(self.vram),fnv(self.sat)]


def validate_records(rows,cases):
    kinds=[]
    for case in cases:
        for op in case['operations']:
            if op[0]in('s','c','m','q','p','f'):kinds.append({'s':('device',28),'c':('cpu',16),'m':('ram',64),'q':('word',2),'p':('byte',2),'f':('sprites',None)}[op[0]])
    if type(rows)is not list or len(rows)!=len(kinds):raise ValueError('Latch record count differs')
    for row,(kind,count)in zip(rows,kinds):
        if type(row)is not dict or set(row)!={'kind','values'}or row['kind']!=kind or type(row['values'])is not list or(count is not None and len(row['values'])!=count)or any(type(v)is not int or not 0<=v<2**64 for v in row['values']):raise ValueError('Latch record type/shape differs')
        if kind=='sprites'and(not row['values']or row['values'][0]>16 or len(row['values'])!=1+row['values'][0]*7):raise ValueError('Sprite cache shape differs')
    return rows


def literal_checks(rows,cases):
    validate_records(rows,cases);index=checks=0;model=None;time=0
    for case in cases:
        for op in case['operations']:
            name=op[0];wanted=None
            if name=='r':model=Model();time=0
            elif name=='w':model.reg(*op[1:])
            elif name=='v':model.vram[op[1]]=op[2]
            elif name=='t':model.sat[op[1]]=op[2]
            elif name=='z':model.vram=[op[1]]*32768
            elif name=='d':model.dots(op[1])
            elif name=='b':
                if model.sat_armed or model.r[15]&16:model.sat_pending=1024;model.sat_armed=False
            elif name=='q':wanted=('word',[op[1],model.word(op[1])])
            elif name=='p':wanted=('byte',[op[1],model.port(op[1])])
            elif name=='f':wanted=('sprites',model.sprites())
            elif name=='s':wanted=('device',model.device())
            elif name=='m':wanted=('ram',model.ram)
            elif name=='c':index+=1
            elif name=='i':model.guest(op[1])
            elif name=='g':
                time+=op[1]
                if time>700000 and model.r[5]&0x80:model.latch=0x16EF
            elif name=='e':pass
            else:raise ValueError('Unauthored operation')
            if wanted:
                expected=dict(kind=wanted[0],values=wanted[1])
                if rows[index]!=expected:raise ValueError(f'Latch literal mismatch {case["id"]} record{index}: {rows[index]} vs {expected}')
                checks+=len(wanted[1]);index+=1
    if index!=len(rows):raise ValueError('Literal observation accounting differs')
    return checks


def build_gear(args,out,report,bindings,compiler):
    checkout,source=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,source);cpp.append(ROOT/'tests/geargrafx_vram_latch_probe.cpp')
    deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in (checkout/'src',ROOT/'tests',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'): flags+=['-I',str(path)]
    objects=out/'objects';objects.mkdir();jobs=[]
    for index,path in enumerate(cpp+c):
        obj=objects/(str(index)+'-'+path.stem+'.o')
        cmd=[str(compiler),*flags,'-x','c++' if path.suffix=='.cpp' else 'c',*(['-std=c++20','-include','cerrno'] if path.suffix=='.cpp' else ['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((cmd,obj));report['commands'].append(cmd)
    def compile_one(job):
        cmd,obj=job;r=subprocess.run(cmd,capture_output=True,text=True,timeout=180);obj.with_suffix('.log').write_text(r.stdout+r.stderr);r.check_returncode()
    with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(compile_one,jobs))
    libs=[p.resolve() for p in args.library]
    if not libs or any(not p.is_file() for p in libs): raise ValueError('Supply explicit existing external libraries')
    bindings['external_libraries']={str(p):sha(p) for p in libs};binary=out/'gear-latch.exe'
    common.evidence([str(compiler),*[str(o) for _,o in jobs],*map(str,libs),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(o):sha(o) for _,o in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    return binary


def execute(label,binary,plan,image,cases,out,report,bindings,tier=None):
    command=[str(binary),str(plan),str(image)];capture=out/(label+'-capture.json')
    if tier is not None:command+=['--capture',str(capture)]
    result=common.evidence(command,label,out,report,bindings)
    rows=validate_records(json.loads(result.stdout),cases)
    if tier is None:return rows,None
    from pcerecomp.capture import load_capture
    from pcerecomp.project import ABI
    observed,_=load_capture(capture);bindings['raw_outputs'][str(capture)]=sha(capture)
    count=sum(op[1]for case in cases for op in case['operations']if op[0]=='i')
    if observed['runtime_abi']!=ABI or not observed['complete']or observed['retired_instructions']!=count or observed['unreadable_instructions']or observed['dropped_instructions']or any(o['interpreted_hits']if tier=='native'else o['native_hits']for o in observed['observations']):raise ValueError('Capture execution tier/count differs')
    return rows,observed


def run(args):
    compiler=Path(shutil.which(str(args.compiler))or'').resolve();out=args.out.resolve();tool=args.tool_source.resolve()
    if args.native:
        sys.path.insert(0,str(tool));from pcerecomp import project
        if Path(project.__file__).resolve()!=tool/'pcerecomp/project.py':raise ValueError('Compiler imported from wrong toolkit')
    if out.exists()or not out.is_relative_to(ROOT/'.local')or not compiler.is_file():raise ValueError('Require compiler and NEW private output')
    files=[Path(__file__),*[ROOT/'tests'/n for n in ('vram_latch_probe_support.hpp','geargrafx_vram_latch_probe.cpp','vram_latch_oracle_probe.cpp','test_vram_latch_reference.py','reset_probe_support.hpp')],*[ROOT/'scripts'/n for n in ('mapper_reference.py','hucard_reference.py','filtered_audio_reference.py','psg_reference.py')]]
    if args.native:files+=sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'pcerecomp').glob('*.py'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p.resolve()):sha(p)for p in files})
    report=dict(schema=1,result='incomplete',oracle_commit=reference.COMMIT,commands=[],bindings=bindings,
        configuration=['Authored public VRAM/SAT debug seeds, deterministic reset and explicit synthetic entry speed','Original Gear queued port completion methods are settled between register/CPU operations without copying their bodies; no CPU VRAM-slot-wait claim','Original Gear DMA dot Clock, sprite-fetch and VBlank entry points invoked directly for semantic vectors','Background vectors additionally use original full core scheduler, uniform authored words and ordinary display registers','Toolkit probes use continuous output for actual rendering-latch ownership; presentation-off parity is tested separately'],
        scope='Retained VRAM bus, CPU buffered reads, ignored high writes, DMA/SAT carry/wrap, sprite plane evaluation and bounded background ownership; optional actual interpreted/emitted native guest',
        not_checked=['Electrical bus phases or VRAM slot stalls','SuperGrafx priority','Gear two-bit background support (absent); separate original Mesen function adapter qualifies that mode','Retail gameplay or physical hardware'])
    out.mkdir(parents=True)
    epoch=out/'authored-inputs';epoch.mkdir()
    report['source_epoch_mappings']={};bindings['authored_epoch']={}
    for path in files:
        saved=epoch/str(len(bindings['authored_epoch']))/path.name;saved.parent.mkdir()
        shutil.copyfile(path,saved)
        if sha(saved)!=bindings['authored_sources'][str(path.resolve())]:raise ValueError('Authored input changed during preservation')
        bindings['authored_epoch'][str(saved)]=sha(saved);report['source_epoch_mappings'][str(path.resolve())]=str(saved)
    try:
        image=out/'authored.pce';image.write_bytes(firmware()[0]);cases=plans();plan=out/'latch.plan';plan.write_text(serialize(cases));bindings['authored_fixtures']={str(p):sha(p)for p in(image,plan)}
        gear=build_gear(args,out,report,bindings,compiler);golden=execute('gear',gear,plan,image,cases,out,report,bindings);literal={'gear':literal_checks(golden[0],cases)}
        probe=build_tool(args,out,report,bindings,compiler)if args.native else args.probe.resolve()if args.probe else None
        if probe:
            actual=execute('interpreted',probe,plan,image,cases,out,report,bindings,'interpreted')
            if actual[0]!=golden[0]:
                at=next(i for i,(a,b)in enumerate(zip(actual[0],golden[0]))if a!=b);raise ValueError(f'Independent latch mismatch at{at}: {actual[0][at]} vs {golden[0][at]}')
            literal['interpreter']=literal_checks(actual[0],cases)
        if args.native:
            from pcerecomp.capture import load_capture
            from pcerecomp.emitter import emit_capture
            from pcerecomp.project import source_identity
            observed,digest=load_capture(out/'interpreted-capture.json');module=out/'native-module';manifest=emit_capture(observed,module,digest)
            if manifest['native_instructions_emitted']!=len(observed['observations'])or manifest['unsupported_observations']or manifest['excluded_observations']:raise ValueError('Every actual identity must translate')
            bindings['generated_module']={str(p):sha(p)for p in module.iterdir()if p.is_file()}
            native=build_tool(args,out,report,bindings,compiler,module);completed=execute('native',native,plan,image,cases,out,report,bindings,'native')
            if completed[0]!=golden[0]:raise ValueError('Native latch records differ')
            if (out/'native.stderr').read_text().strip()!='PCE_VRAM_GUARDS=4':raise ValueError('Four native source/context guard negatives required')
            if {common.capture_identity(o):o['native_hits']for o in completed[1]['observations']}!={common.capture_identity(o):o['interpreted_hits']for o in actual[1]['observations']}:raise ValueError('Native source hit keys differ')
            literal['native']=literal_checks(completed[0],cases);report['tool']=source_identity(tool)
            report['native']=dict(retirements=completed[1]['retired_instructions'],interpreted=0,identities=len(observed['observations']),mpr_contexts=len({tuple(o['mpr'])for o in observed['observations']}),pure_guard_negatives=4)
        report.update(result='pass',cases=len(cases),records=len(golden[0]),literal_checks=literal,retirements_per_entry_speed=len(firmware()[1]))
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass':raise ValueError('Evidence changed')
    print(json.dumps({k:v for k,v in report.items()if k not in('bindings','commands')},indent=2))



def build_tool(args,out,report,bindings,compiler,module=None):
    tool=args.tool_source.resolve();label='native' if module else 'interpreted';q=infrastructure.cmake_quote
    cmake,ninja=(Path(shutil.which(str(v)) or '').resolve() for v in (args.cmake,args.ninja))
    if not cmake.is_file() or not ninja.is_file(): raise ValueError('Require CMake/Ninja')
    bindings['tools'].update({str(p):sha(p) for p in (cmake,ninja)})
    wrapper=out/(label+'-wrapper');wrapper.mkdir();source=ROOT/'tests/vram_latch_oracle_probe.cpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(VramLatchProof LANGUAGES CXX)',*['set('+o+' OFF CACHE BOOL "" FORCE)' for o in ('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],f'add_subdirectory({q(tool)} tool)']
    if module: lines += [f'pce_add_native_module(_module MODULE {q(module/"module.cpp")} MANIFEST {q(module/"module.json")})',f'add_executable(latch-probe {q(source)})','target_compile_definitions(latch-probe PRIVATE PCE_LATCH_NATIVE_ONLY=1)','target_link_libraries(latch-probe PRIVATE ${_module} pce-runtime)']
    else: lines += [f'add_executable(latch-probe {q(source)} {q(tool/"runtime/src/no_module.cpp")})','target_link_libraries(latch-probe PRIVATE pce-runtime)']
    file=wrapper/'CMakeLists.txt';file.write_text('\n'.join(lines)+'\n');bindings.setdefault('tool_build_inputs',{})[str(file)]=sha(file)
    build=out/(label+'-build')
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],label+'-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','latch-probe','--parallel','4'],label+'-build',out,report,bindings,600)
    binary=build/('latch-probe.exe' if os.name=='nt' else 'latch-probe')
    bindings.setdefault('tool_build_artifacts',{}).update({str(p):sha(p) for p in build.rglob('*') if p.is_file() and (p.suffix in ('.obj','.o','.a') or p.name in ('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))})
    bindings.setdefault('tool_binaries',{})[str(binary)]=sha(binary)
    return binary



if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--tool-source',type=Path,default=ROOT);parser.add_argument('--probe',type=Path);parser.add_argument('--native',action='store_true');parser.add_argument('--out',type=Path,required=True);parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake');parser.add_argument('--ninja',default='ninja');parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
