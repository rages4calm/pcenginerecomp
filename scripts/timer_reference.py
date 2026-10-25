"""Finite timer phase observations against independently compiled Geargrafx.

Device tick edges and actual low/high speed CPU retirements are separate cases.
Both probes explicitly configure synthetic entry speed before execution; CSL/
CSH select that same speed. Existing cross-speed timing differences are excluded.
Only authored HuCards are used; no emulator implementation enters the runtime.
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


def firmware(fast):
    operations=[]
    def emit(*values):operations.append(bytes(values))
    def store(address,value):emit(0xA9,value);emit(0x8D,address&255,address>>8)
    def save(offset):emit(0xAD,0,12);emit(0x8D,offset,32)
    emit(0xD4 if fast else 0x54)
    emit(0xA9,255);emit(0x53,1);emit(0xA9,248);emit(0x53,2)
    save(0);store(0xC00,127);save(1);store(0xC01,0);save(2)
    store(0xC00,0);store(0xC01,1)
    for _ in range(512 if fast else 128):emit(0xEA)
    save(3);store(0xC01,0);save(4)
    for _ in range(20):emit(0xEA)
    save(5);store(0xC01,1);emit(0xEA);save(6)
    count=len(operations)+6
    rom=bytearray([0xEA]*262144);program=b''.join(operations)+b'\x80\xFE'
    if len(program)>7000:raise ValueError('Authored timer ROM bound')
    rom[256:256+len(program)]=program;rom[8190:8192]=bytes((0,0xE1))
    return bytes(rom),count


def plans():
    initial=[('r',0),('s',),('q',0xC00),('t',9000),('q',0xFFF)]
    for value in (0,2,0xFE):initial += [('w',0xC01,value),('q',0xC00),('s',)]
    reload=[]
    for value in range(256):reload += [('r',0),('w',0xC00,value),('q',0xC01),('s',)]
    edges=[]
    for value in (0,1,127):
        edges += [('r',0),('w',0xC00,value),('w',0xC01,1),('s',)]
        for ticks in (3056,1,14,1,1,3071,3072,15360):edges += [('t',ticks),('q',0xC00),('s',)]
        edges += [('w',0x1402,7),('s',),('w',0x1403,255),('s',),('w',0xC01,0),('s',),('t',20000),('q',0xC00),('s',)]
        for val in (0,2,0xFE):edges += [('w',0xC01,val),('w',0xC00,0),('q',0xC00),('s',)]
        edges += [('w',0xC01,1),('t',3057),('w',0xC01,1),('w',0xC00,127),('s',),('q',0xC00),('t',15),('s',),('q',0xC00)]
    cases=[dict(id='reset-disabled',operations=initial),dict(id='reload-only-all-bytes',operations=reload),dict(id='phase-boundaries-and-controls',operations=edges)]
    for fast in (0,1):
        guest=[('r',fast),('c',),('i',firmware(fast)[1])]+[('k',i)for i in range(7)]
        cases.append(dict(id='guest-'+str(fast),guest=True,operations=guest))
    return cases


def serialize(cases):return '\n'.join(' '.join(map(str,op))for case in cases for op in case['operations'])+'\n'


class Timer:
    def __init__(self):self.enabled=False;self.reload=self.counter=self.phase=self.mask=0;self.pending=False
    def write(self,address,value):
        if address==0x1402:self.mask=value&7
        elif address==0x1403:self.pending=False
        elif address&1:
            enabled=bool(value&1)
            if enabled!=self.enabled:
                self.enabled=enabled;self.phase=3072
                if enabled:self.counter=self.reload
        else:self.reload=value&127
    def advance(self,ticks):
        if not self.enabled:return
        if ticks<self.phase:self.phase-=ticks;return
        periods=1+(ticks-self.phase)//3072;self.phase=3072-(ticks-self.phase)%3072
        if periods<=self.counter:self.counter-=periods
        else:
            self.pending=True;self.counter=self.reload-(periods-self.counter-1)%(self.reload+1)
    def read(self):return 127 if self.counter==0 and self.phase<=15 else self.counter
    def state(self):return [int(self.enabled),self.reload,self.counter,int(self.pending),self.mask,self.phase]


def validate_records(records,cases):
    wanted=[]
    for case in cases:
        for op in case['operations']:
            if op[0]=='i':wanted += [('cpu',16)]*op[1]
            elif op[0] in ('s','c','q','k'):wanted.append({'s':('timer',6),'c':('cpu',16),'q':('read',2),'k':('ram',2)}[op[0]])
    if type(records)is not list or len(records)!=len(wanted):raise ValueError('Timer record count differs')
    for row,(kind,width)in zip(records,wanted):
        if type(row)is not dict or set(row)!={'kind','values'}or row['kind']!=kind or type(row['values'])is not list or len(row['values'])!=width or any(type(v)is not int or not 0<=v<2**64 for v in row['values']):raise ValueError('Timer record type/shape differs')
    return records


def literal_checks(records,cases):
    validate_records(records,cases);index=checks=0;timer=None
    for case in cases:
        for op in case['operations']:
            name=op[0]
            if name=='r':timer=Timer()
            elif name=='w':timer.write(*op[1:])
            elif name=='t':timer.advance(op[1])
            elif name=='i':index+=op[1]
            elif name=='c':index+=1
            else:
                if name=='s':wanted=dict(kind='timer',values=timer.state())
                elif name=='q':wanted=dict(kind='read',values=[op[1],timer.read()])
                # The reset I/O latch retains bit7 on the first timer read.
                # Later timer writes clear it; the timer counter is still $7F.
                elif name=='k':wanted=dict(kind='ram',values=[op[1],255 if op[1]==0 else 127 if op[1]<3 else 0])
                else:raise ValueError('Unknown authored operation')
                if records[index]!=wanted:raise ValueError(f'Timer literal mismatch at {index}: {records[index]} vs {wanted}')
                index+=1;checks+=1
    return checks


def build_gear(args,out,report,bindings,compiler):
    checkout,source=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,source);cpp.append(ROOT/'tests/geargrafx_timer_probe.cpp')
    deps=checkout/'platforms/shared/dependencies';flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for path in (checkout/'src',ROOT/'tests',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(path)]
    objects=out/'objects';objects.mkdir();jobs=[]
    for index,path in enumerate(cpp+c):
        obj=objects/(str(index)+'-'+path.stem+'.o');cmd=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((cmd,obj));report['commands'].append(cmd)
    def compile_one(job):
        cmd,obj=job;r=subprocess.run(cmd,capture_output=True,text=True,timeout=180);obj.with_suffix('.log').write_text(r.stdout+r.stderr);r.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(compile_one,jobs))
    libs=[p.resolve()for p in args.library]
    if not libs or any(not p.is_file()for p in libs):raise ValueError('Supply explicit existing external libraries')
    bindings['external_libraries']={str(p):sha(p)for p in libs};binary=out/'gear-timer.exe'
    common.evidence([str(compiler),*[str(o)for _,o in jobs],*map(str,libs),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(o):sha(o)for _,o in jobs};bindings['gear_binary']={str(binary):sha(binary)};return binary


def build_tool(args,out,report,bindings,compiler,module=None):
    tool=args.tool_source.resolve();label='native'if module else'interpreted';q=infrastructure.cmake_quote
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve()for v in(args.cmake,args.ninja))
    if not cmake.is_file()or not ninja.is_file():raise ValueError('Require CMake/Ninja')
    bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)})
    wrapper=out/(label+'-wrapper');wrapper.mkdir();source=ROOT/'tests/timer_oracle_probe.cpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(TimerProof LANGUAGES CXX)',*['set('+o+' OFF CACHE BOOL "" FORCE)'for o in('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],f'add_subdirectory({q(tool)} tool)']
    if module:lines += [f'pce_add_native_module(_module MODULE {q(module/"module.cpp")} MANIFEST {q(module/"module.json")})',f'add_executable(timer-probe {q(source)})','target_compile_definitions(timer-probe PRIVATE PCE_TIMER_NATIVE_ONLY=1)','target_link_libraries(timer-probe PRIVATE ${_module} pce-runtime)']
    else:lines += [f'add_executable(timer-probe {q(source)} {q(tool/"runtime/src/no_module.cpp")})','target_link_libraries(timer-probe PRIVATE pce-runtime)']
    file=wrapper/'CMakeLists.txt';file.write_text('\n'.join(lines)+'\n');bindings.setdefault('tool_build_inputs',{})[str(file)]=sha(file)
    build=out/(label+'-build')
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],label+'-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','timer-probe','--parallel','4'],label+'-build',out,report,bindings,600)
    binary=build/('timer-probe.exe'if os.name=='nt'else'timer-probe')
    bindings.setdefault('tool_build_artifacts',{}).update({str(p):sha(p)for p in build.rglob('*')if p.is_file()and(p.suffix in('.obj','.o','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))})
    bindings.setdefault('tool_binaries',{})[str(binary)]=sha(binary);return binary


def execute(label,binary,plan,images,cases,out,report,bindings,tier=None):
    command=[str(binary),str(plan),*map(str,images)];capture=out/(label+'-capture.json')
    if tier is not None:command += ['--capture',str(capture)]
    r=common.evidence(command,label,out,report,bindings);records=validate_records(json.loads(r.stdout),cases)
    if tier is None:return records,None
    from pcerecomp.capture import load_capture
    from pcerecomp.project import ABI
    observed,_=load_capture(capture);bindings['raw_outputs'][str(capture)]=sha(capture)
    count=sum(op[1]for case in cases for op in case['operations']if op[0]=='i')
    if observed['runtime_abi']!=ABI or not observed['complete']or observed['retired_instructions']!=count or any(o['interpreted_hits']if tier=='native'else o['native_hits']for o in observed['observations']):raise ValueError('Actual timer capture tier/count differs')
    return records,observed


def run(args):
    compiler=Path(shutil.which(str(args.compiler))or'').resolve();out=args.out.resolve();tool=args.tool_source.resolve()
    if args.native:
        sys.path.insert(0,str(tool));from pcerecomp import project
        if Path(project.__file__).resolve()!=tool/'pcerecomp/project.py':raise ValueError('Compiler imported from wrong source')
    if out.exists()or not out.is_relative_to(ROOT/'.local')or not compiler.is_file():raise ValueError('Require compiler and NEW private output')
    files=[Path(__file__),ROOT/'tests/geargrafx_timer_probe.cpp',ROOT/'tests/timer_oracle_probe.cpp',ROOT/'tests/test_timer_reference.py',ROOT/'tests/reset_probe_support.hpp',ROOT/'scripts/mapper_reference.py',ROOT/'scripts/hucard_reference.py',ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/psg_reference.py']
    if args.native:files+=sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'pcerecomp').glob('*.py'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p.resolve()):sha(p)for p in files})
    report=dict(schema=1,result='incomplete',oracle_commit=reference.COMMIT,commands=[],bindings=bindings,scope='Authored disabled/reset timer phase and literal device edges; explicit synthetic CPU entry speed, same-speed CSL/CSH, ordinary native timer reads/writes',not_checked=['Retail software','Electrical bus phase accuracy','Timer frequency hardware measurement','General IRQ priority redesign','Cross-speed CSL/CSH timing; existing documented Gear difference','Authentic high-speed reset startup'])
    out.mkdir(parents=True)
    try:
        gear=build_gear(args,out,report,bindings,compiler);cases=plans();images=[out/'low.pce',out/'high.pce'];plan=out/'timer.plan'
        for fast,image in enumerate(images):image.write_bytes(firmware(fast)[0])
        plan.write_text(serialize(cases));bindings['authored_fixtures']={str(p):sha(p)for p in(*images,plan)}
        golden=execute('gear',gear,plan,images,cases,out,report,bindings);literal={'gear':literal_checks(golden[0],cases)}
        probe=build_tool(args,out,report,bindings,compiler)if args.native else args.probe.resolve()if args.probe else None
        if probe:
            actual=execute('interpreted',probe,plan,images,cases,out,report,bindings,'interpreted')
            if actual[0]!=golden[0]:
                index=next(i for i,(a,b)in enumerate(zip(actual[0],golden[0]))if a!=b);raise ValueError(f'Independent timer mismatch at {index}: {actual[0][index]} vs {golden[0][index]}')
            literal['interpreter']=literal_checks(actual[0],cases)
        if args.native:
            from pcerecomp.capture import load_capture
            from pcerecomp.emitter import emit_capture
            from pcerecomp.project import source_identity
            capture=out/'interpreted-capture.json';observed,digest=load_capture(capture);module=out/'native-module';manifest=emit_capture(observed,module,digest)
            if manifest['native_instructions_emitted']!=len(observed['observations'])or manifest['unsupported_observations']or manifest['excluded_observations']:raise ValueError('All actual identities must translate')
            bindings['generated_module']={str(p):sha(p)for p in module.iterdir()if p.is_file()}
            binary=build_tool(args,out,report,bindings,compiler,module);completed=execute('native',binary,plan,images,cases,out,report,bindings,'native')
            if completed[0]!=golden[0]:raise ValueError('Native timer records differ')
            if {common.capture_identity(o):o['native_hits']for o in completed[1]['observations']}!={common.capture_identity(o):o['interpreted_hits']for o in actual[1]['observations']}:raise ValueError('Native timer source hit keys differ')
            literal['native']=literal_checks(completed[0],cases);report['tool']=source_identity(tool)
            report['native']=dict(retirements=completed[1]['retired_instructions'],interpreted=0,identities=len(observed['observations']),mpr_contexts=len({tuple(o['mpr'])for o in observed['observations']}))
        report.update(result='pass',cases=len(cases),observations=len(golden[0]),literal_checks=literal,guest_retirements=[firmware(f)[1]for f in(0,1)])
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass':raise ValueError('Timer evidence changed')
    print(json.dumps({k:v for k,v in report.items()if k not in('bindings','commands')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gear-source',type=Path,required=True);p.add_argument('--tool-source',type=Path,default=ROOT);p.add_argument('--probe',type=Path);p.add_argument('--native',action='store_true');p.add_argument('--out',type=Path,required=True);p.add_argument('--compiler',default='clang++');p.add_argument('--cmake',default='cmake');p.add_argument('--ninja',default='ninja');p.add_argument('--library',type=Path,action='append',default=[])
    try:run(p.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as e:print(e,file=sys.stderr);raise SystemExit(1)
