"""Finite Arcade Card Duo checks against a separate unchanged Geargrafx core.

Only authored firmware/data are used. Gear media configuration explicitly
selects CD hardware, Super-card RAM and Arcade mapping after media loading;
the original mapper, memory routing, CPU and scheduler execute unchanged.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
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
COMMIT=reference.COMMIT


def firmware():
    """Low-speed guest uses actual LDA/STA/TII operations on both interfaces."""
    instructions=[]
    def emit(*code):instructions.append(bytes(code))
    def store(address,value):emit(0xA9,value);emit(0x8D,address&255,address>>8)
    def port(index,base):
        for reg,value in ((9,0),(2,base&255),(3,(base>>8)&255),(4,base>>16),(5,0),(6,0),(7,1),(8,0),(9,0x11)):
            store(0x1A00+index*16+reg,value)
    emit(0xA9,0xFF);emit(0x53,1);emit(0xA9,0xF8);emit(0x53,2)
    emit(0xA9,0x40);emit(0x53,4);emit(0xA9,0x41);emit(0x53,8)
    port(0,0xFFFFFE)
    for address,value in ((0x4000,0xA5),(0x5FFF,0x5A),(0x1A00,0xC3)):store(address,value)
    port(1,0xFFFFFE)
    for source,dest in ((0x6000,0x2000),(0x7FFF,0x2001),(0x1A10,0x2002)):
        emit(0xAD,source&255,source>>8);emit(0x8D,dest&255,dest>>8)
    for offset,value in enumerate((3,4,5,6)):store(0x2008+offset,value)
    port(0,0xFFFFFF);emit(0x73,8,0x20,0,0x40,4,0)
    port(1,0xFFFFFF);emit(0x73,0,0x60,0x20,0x20,4,0)
    for i,value in enumerate((0x78,0x56,0x34,0x12)):store(0x1AE0+i,value)
    store(0x1AE4,4);store(0x1AE5,15)
    for i in range(4):emit(0xAD,0xE0+i,0x1A);emit(0x8D,0x28+i,0x20)
    count=len(instructions)+6
    image=bytearray([0xEA]*262144)
    program=b''.join(instructions)+b'\x80\xfe'
    if len(program)>7000:raise ValueError('Authored program exceeds fixed ROM bank')
    image[0x100:0x100+len(program)]=program;image[8190:8192]=bytes((0,0xE1))
    return bytes(image),count


def plans():
    arithmetic=[('r',0),('s',),('a',)]
    for port in range(4):
        address=0x1A00+16*port
        for control in range(128):
            for offset in (0,0x8000,0xFFFF):
                for increment in (0,1,0xFFFF):
                    for reg,value in ((9,0),(2,0xFE),(3,0xFF),(4,0xFF),
                                      (5,offset&255),(6,offset>>8),(7,increment&255),(8,increment>>8),(9,control)):
                        arithmetic.append(('w',255,address+reg,value))
                    arithmetic += [('w',0x40+port,0x1FFF,(control*13+offset+increment)&255),
                                   ('q',255,address+0x41),('a',)]
        # Trigger points: read/write unused2 bit, low/high/explicit additions,
        # unconditional negative offset and 24-bit base wrapping.
        for trigger in range(4):
            for sign in (0,8):
                for offset in (0,1,0x7FFF,0x8000,0xFFFF):
                    for reg,value in ((9,0),(2,0xFD),(3,0xFF),(4,0xFF),(5,0),(6,0),(9,(trigger<<5)|sign|4)):
                        arithmetic.append(('w',255,address+reg,value))
                    for reg,value in ((5,offset&255),(6,offset>>8),(10,0xD3)):
                        arithmetic += [('w',255,address+reg,value),('a',)]
                    arithmetic += [('q',255,address+10),('q',255,address+9)]
    shifts=[('r',0xA5),('a',)]
    for initial in (0,0xFFFFFFFF,0x80000001,0x12345678,0x01234567):
        for value in range(256):
            for target in (0x1AE4,0x1AE5):
                for i in range(4):shifts.append(('w',255,0x1AE0+i,(initial>>(8*i))&255))
                shifts.append(('w',255,target,value))
                shifts += [('q',255,0x1AE0+i) for i in range(6)]
                shifts.append(('a',))
    # All interface holes, ID registers and mirror boundaries; writes ignored.
    for offset in range(0x1A80,0x1C00):
        if offset in range(0x1AE0,0x1AE6):continue
        shifts += [('w',255,offset,(offset*19)&255),('q',255,offset)]
    guest=[('r',0),('s',),('i',firmware()[1]),('a',)]
    guest += [('q',0xF8,i) for i in (*range(3),*range(8,12),*range(0x20,0x24),*range(0x28,0x2C))]
    guest += [('k',i) for i in (0,1,2,3,0x1FFFFD,0x1FFFFE,0x1FFFFF)]
    fresh=[('r',0xFF),('s',),('a',)]
    fresh += [('q',255,o) for o in (0x1AFC,0x1AFD,0x1AFE,0x1AFF,0x1AF0,0x1B00,0x1BFF)]
    fresh += [('q',bank,offset) for bank in range(0x40,0x44) for offset in (0,0x1000,0x1FFF)]
    fresh += [('a',),('k',0),('k',0x1FFFFF),('p',0,0x100)]
    return [dict(id=name,operations=operations) for name,operations in
            (('port-arithmetic',arithmetic),('shift-rotate-and-holes',shifts),('translated-guest',guest),('fresh-fill-and-id',fresh))]


def serialize(cases):
    return '\n'.join(' '.join(map(str,op)) for case in cases for op in case['operations'])+'\n'


def fetch_plans():
    operations=[('r',0)]
    for reg,value in ((7,1),(9,3),(0,0xA9),(1,0x61),(0,0xEA),(5,0)):
        operations.append(('w',255,0x1A00+reg,value))
    operations += [('f',),('s',),('i',1),('a',),('k',0),('k',1)]
    return [dict(id='interpreter-only-port-fetch',port_fetch=True,operations=operations)]


def validate_records(records,cases):
    kinds=[]
    for case in cases:
        for op in case['operations']:
            if op[0]=='i':kinds += [('cpu',16)]*op[1]
            elif op[0] in ('s','a','q','p','k'):
                kinds.append({'s':('cpu',16),'a':('arcade',19),'q':('memory',3),'p':('peek',3),'k':('ram',2)}[op[0]])
    if not isinstance(records,list) or len(records)!=len(kinds):raise ValueError('Arcade observation count differs')
    for record,(kind,width) in zip(records,kinds):
        if (type(record)is not dict or set(record)!={'kind','values'} or record['kind']!=kind or
            type(record['values'])is not list or len(record['values'])!=width or
            any(type(v)is not int or not 0<=v<2**64 for v in record['values'])):
            raise ValueError('Arcade observation type/shape differs')
    return records


class LiteralState:
    """Independent sparse reference math, not an execution-tier comparison."""
    def __init__(self,fill):
        self.fill=fill;self.ports=[[0,0,0,0] for _ in range(4)];self.ram={};self.wram={};self.value=0;self.shift=0;self.rotate=0
    def adjusted(self,p):return p[1]-(65536 if p[3]&8 else 0)
    def effective(self,p):return (p[0]+(self.adjusted(p) if p[3]&2 else 0))%2097152
    def advance(self,p):
        if p[3]&1:
            target=0 if p[3]&16 else 1
            p[target]=(p[target]+p[2])%(16777216 if target==0 else 65536)
    def data(self,port,value=None):
        p=self.ports[port];address=self.effective(p)
        observed=self.ram.get(address,self.fill)
        if value is not None:self.ram[address]=value
        self.advance(p);return observed
    def register(self,address,value=None):
        if address<0x1A80:
            p=self.ports[(address//16)%4];reg=address%16
            if reg<2:return self.data((address//16)%4,value)
            if 2<=reg<=8:
                field,byte={2:(0,0),3:(0,1),4:(0,2),5:(1,0),6:(1,1),7:(2,0),8:(2,1)}[reg]
                observed=(p[field]>>(byte*8))&255
                if value is not None:
                    p[field]=(p[field]&~(255<<(byte*8)))|(value<<(byte*8))
                    trigger=(p[3]//32)%4
                    if (reg==5 and trigger==1) or (reg==6 and trigger==2):p[0]=(p[0]+self.adjusted(p))%16777216
                return observed
            if reg==9:
                observed=p[3]
                if value is not None:p[3]=value%128
                return observed
            if reg==10:
                if value is not None and (p[3]//32)%4==3:p[0]=(p[0]+self.adjusted(p))%16777216
                return 0
            return 255
        if 0x1AE0<=address<=0x1AE3:
            byte=address-0x1AE0;observed=(self.value>>(byte*8))&255
            if value is not None:self.value=(self.value&~(255<<(byte*8)))|(value<<(byte*8))
            return observed
        if address in (0x1AE4,0x1AE5):
            observed=self.shift if address==0x1AE4 else self.rotate
            if value is not None:
                amount=value%16
                if address==0x1AE4:self.shift=amount
                else:self.rotate=amount
                if amount:
                    distance=amount if amount<8 else 16-amount
                    if address==0x1AE4:self.value=(self.value<<distance if amount<8 else self.value>>distance)&0xFFFFFFFF
                    elif amount<8:self.value=((self.value<<distance)|(self.value>>(32-distance)))&0xFFFFFFFF
                    else:self.value=((self.value>>distance)|(self.value<<(32-distance)))&0xFFFFFFFF
            return observed
        return {0x1AFC:0,0x1AFD:0,0x1AFE:16,0x1AFF:81}.get(address,255)
    def state(self):return sum(self.ports,[])+[self.value,self.shift,self.rotate]
    def guest(self):
        self.ports[0]=[3,0,1,17];self.ports[1]=[3,0,1,17]
        self.ram={0:4,1:5,2:6,0x1FFFFE:0xA5,0x1FFFFF:3}
        self.wram={0:0xA5,1:0x5A,2:0xC3,8:3,9:4,10:5,11:6,
                    0x20:3,0x21:4,0x22:5,0x23:6,0x28:0xC0,0x29:0xB3,0x2A:0xA2,0x2B:0x11}
        self.value=0x11A2B3C0;self.shift=4;self.rotate=15


def expected_records(records,cases,image):
    validate_records(records,cases);index=checks=0;model=None
    for case in cases:
        for op in case['operations']:
            name=op[0]
            if name=='r':model=LiteralState(op[1]);continue
            if name=='w':
                _,bank,offset,value=op
                if 64<=bank<=67:model.data(bank-64,value)
                elif bank==255:model.register(offset,value)
                else:raise ValueError('Literal write outside authored device')
                continue
            if name=='f':continue
            if name=='i':
                index+=op[1]
                if case.get('port_fetch'):model.ports[0][1]=2
                else:model.guest()
                continue
            if name=='s':index+=1;continue
            if name=='a':wanted=dict(kind='arcade',values=model.state())
            elif name=='k':wanted=dict(kind='ram',values=[op[1],model.ram.get(op[1],model.fill)])
            else:
                _,bank,offset=op
                if 64<=bank<=67:value=model.data(bank-64)
                elif bank==255:value=model.register(offset)
                elif bank==248:value=model.wram.get(offset,model.fill)
                else:value=image[((bank%32)*8192)+offset]
                wanted=dict(kind='peek' if name=='p' else 'memory',values=[bank,offset,value])
            if records[index]!=wanted:raise ValueError(f'Literal Arcade mismatch at {index}: {records[index]} vs {wanted}')
            index+=1;checks+=1
    if index!=len(records):raise ValueError('Literal observation accounting differs')
    return checks


def build_gear(args,out,report,bindings,compiler):
    checkout,source=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,source);cpp.append(ROOT/'tests/geargrafx_arcade_probe.cpp')
    deps=checkout/'platforms/shared/dependencies'
    flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for include in (checkout/'src',ROOT/'tests',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(include)]
    objects=out/'objects';objects.mkdir();jobs=[]
    for index,path in enumerate(cpp+c):
        obj=objects/(str(index)+'-'+path.stem+'.o')
        cmd=[str(compiler),*flags,'-x','c++' if path.suffix=='.cpp' else 'c',
             *(['-std=c++20','-include','cerrno'] if path.suffix=='.cpp' else ['-std=c11']),'-c',str(path),'-o',str(obj)]
        report['commands'].append(cmd);jobs.append((cmd,obj))
    def compile_one(job):
        cmd,obj=job;result=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
        obj.with_suffix('.log').write_text(result.stdout+result.stderr);result.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(compile_one,jobs))
    libraries=[p.resolve()for p in args.library]
    if not libraries or any(not p.is_file()for p in libraries):raise ValueError('Supply existing external libraries explicitly')
    bindings['external_libraries']={str(p):sha(p)for p in libraries};binary=out/'gear-arcade.exe'
    common.evidence([str(compiler),*[str(obj)for _,obj in jobs],*map(str,libraries),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(obj):sha(obj)for _,obj in jobs};bindings['gear_binary']={str(binary):sha(binary)}
    return binary


def build_tool(args,out,report,bindings,compiler,tool,module=None):
    label='native' if module else 'interpreted'
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve()for v in(args.cmake,args.ninja))
    if not cmake.is_file()or not ninja.is_file():raise ValueError('Require CMake/Ninja')
    bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)})
    quote=infrastructure.cmake_quote;wrapper=out/(label+'-wrapper');wrapper.mkdir()
    source=ROOT/'tests/arcade_oracle_probe.cpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(AuthoredArcade LANGUAGES CXX)',
           *['set('+option+' OFF CACHE BOOL "" FORCE)'for option in('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],
           f'add_subdirectory({quote(tool)} tool)']
    if module:lines += [f'pce_add_native_module(_module MODULE {quote(module/"module.cpp")} MANIFEST {quote(module/"module.json")})',
                       f'add_executable(arcade-probe {quote(source)})','target_compile_definitions(arcade-probe PRIVATE PCE_ARCADE_NATIVE_ONLY=1)',
                       'target_link_libraries(arcade-probe PRIVATE ${_module} pce-runtime)']
    else:lines += [f'add_executable(arcade-probe {quote(source)} {quote(tool/"runtime/src/no_module.cpp")})','target_link_libraries(arcade-probe PRIVATE pce-runtime)']
    file=wrapper/'CMakeLists.txt';file.write_text('\n'.join(lines)+'\n');bindings.setdefault('tool_build_inputs',{})[str(file)]=sha(file)
    build=out/(label+'-build')
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
                     '-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],label+'-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','arcade-probe','--parallel','4'],label+'-build',out,report,bindings,600)
    binary=build/('arcade-probe.exe' if os.name=='nt' else 'arcade-probe')
    bindings.setdefault('tool_build_artifacts',{}).update({str(p):sha(p)for p in build.rglob('*') if p.is_file()and
        (p.suffix in('.obj','.o','.a')or p.name in('CMakeCache.txt','build.ninja','rules.ninja','.ninja_log'))})
    bindings.setdefault('tool_binaries',{})[str(binary)]=sha(binary);return binary


def validate_execution(work,cases,native):
    from pcerecomp.project import ABI
    counts=[sum(op[1]for op in case['operations']if op[0]=='i')for case in cases]
    expected=dict(runtime_abi=ABI,native_only=native,interpreter_fallback=False,cases=len(cases),
        native_steps=sum(counts)if native else 0,interpreter_steps=0 if native else sum(counts),
        guard_checks=7*len(cases)if native else 0,restored_source_mutations=len(cases)if native else 0,
        per_case=[[n,0]if native else[0,n]for n in counts])
    if type(work)is not dict or set(work)!=set(expected)or work!=expected:raise ValueError('Execution accounting differs')
    if any(type(work[k])is not type(v)for k,v in expected.items()):raise ValueError('Execution field type differs')
    if any(type(n)is not int for pair in work['per_case']for n in pair):raise ValueError('Execution tier count type differs')
    return work


def execute(label,binary,plan,image,cases,out,report,bindings,native=None):
    command=[str(binary),str(plan),str(image)]
    capture,execution=out/(label+'-capture.json'),out/(label+'-execution.json')
    if native is not None:
        command += ['--capture',str(capture),'--execution-report',str(execution)]
        if native:command += ['--guard-checks','on']
    result=common.evidence(command,label,out,report,bindings)
    records=validate_records(json.loads(result.stdout),cases)
    if native is None:return records,None,None
    bindings['raw_outputs'].update({str(p):sha(p)for p in(capture,execution)})
    work=validate_execution(json.loads(execution.read_text()),cases,native)
    observed=common.validate_capture(json.loads(capture.read_text()),work,native)
    return records,observed,work


def interpreter_port_fetch(gear,probe,image,out,report,bindings):
    cases=fetch_plans();plan=out/'port-fetch.plan';plan.write_text(serialize(cases))
    bindings['authored_fixtures'][str(plan)]=sha(plan)
    expected=execute('gear-port-fetch',gear,plan,image,cases,out,report,bindings)
    checks=expected_records(expected[0],cases,image.read_bytes())
    literal=[0xE002,0x61,0,0,0,4,12,24,*([0]*7),0x40]
    if expected[0][1]!=dict(kind='cpu',values=literal):raise ValueError('Port-sourced LDA instruction literal differs')
    if not probe:return dict(observations=len(expected[0]),literal_checks=checks,gear_cpu=literal)
    capture,work=out/'interpreted-port-fetch-capture.json',out/'interpreted-port-fetch-execution.json'
    result=common.evidence([str(probe),str(plan),str(image),'--capture',str(capture),'--execution-report',str(work)],
                           'interpreted-port-fetch',out,report,bindings)
    actual=validate_records(json.loads(result.stdout),cases)
    if actual!=expected[0]:raise ValueError('Interpreted port-sourced fetch differs from Gear')
    validate_execution(json.loads(work.read_text()),cases,False)
    from pcerecomp.capture import load_capture
    observed,_=load_capture(capture)
    if (observed['complete'] or observed['unreadable_instructions']!=1 or observed['retired_instructions']!=1 or
        observed['dropped_instructions'] or observed['observations']):raise ValueError('Side-effect source must be unreadable, never a native identity')
    bindings['raw_outputs'].update({str(p):sha(p)for p in(capture,work)})
    return dict(observations=len(actual),literal_checks=checks,interpreted_steps=1,unreadable_source_retirements=1,
                native_promotion=False,gear_cpu=literal)


def run(args):
    compiler=Path(shutil.which(str(args.compiler))or'').resolve();tool,out=args.tool_source.resolve(),args.out.resolve()
    if args.native:
        sys.path.insert(0,str(tool))
        from pcerecomp import project
        if Path(project.__file__).resolve()!=tool/'pcerecomp/project.py':raise ValueError('Compiler imported from another toolkit')
    if out.exists()or not out.is_relative_to(ROOT/'.local')or not compiler.is_file():raise ValueError('Require compiler and NEW private output')
    sources=[Path(__file__),ROOT/'tests/geargrafx_arcade_probe.cpp',ROOT/'tests/arcade_oracle_probe.cpp',ROOT/'tests/reset_probe_support.hpp',
             ROOT/'scripts/mapper_reference.py',ROOT/'scripts/hucard_reference.py',ROOT/'scripts/filtered_audio_reference.py',ROOT/'scripts/psg_reference.py',ROOT/'tests/test_arcade_reference.py']
    if args.native:sources+=sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'pcerecomp').glob('*.py'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p.resolve()):sha(p)for p in sources})
    report=dict(schema=1,result='incomplete',oracle_commit=COMMIT,commands=[],bindings=bindings,
        scope='Authored Arcade Duo four-port/register/shifter behavior and ordinary low-speed CPU LDA/STA/TII; configuration-only CD/card-RAM/mapper selection',
        not_checked=['Retail media','Electrical board behavior','Warm reset','Persistence','Host audio','Physical CPU bus phases','Native execution from side-effecting port windows'])
    out.mkdir(parents=True)
    try:
        gear=build_gear(args,out,report,bindings,compiler)
        image_bytes,count=firmware();cases=plans();image,plan=out/'authored-system.pce',out/'arcade.plan'
        image.write_bytes(image_bytes);plan.write_text(serialize(cases));bindings['authored_fixtures']={str(p):sha(p)for p in(image,plan)}
        golden=execute('gear',gear,plan,image,cases,out,report,bindings)
        literal={'gear':expected_records(golden[0],cases,image_bytes)}
        probe=build_tool(args,out,report,bindings,compiler,tool)if args.native else args.probe.resolve()if args.probe else None
        if probe:
            observed=execute('interpreted',probe,plan,image,cases,out,report,bindings,False)
            if observed[0]!=golden[0]:
                first=next(i for i,(a,b)in enumerate(zip(observed[0],golden[0]))if a!=b)
                raise ValueError('Independent Arcade mismatch at '+str(first)+': '+str(observed[0][first])+' vs '+str(golden[0][first]))
            literal['interpreter']=expected_records(observed[0],cases,image_bytes)
        if args.native:
            from pcerecomp.capture import load_capture
            from pcerecomp.emitter import emit_capture
            from pcerecomp.project import source_identity
            capture=out/'actual-capture.json';capture.write_text(json.dumps(observed[1],indent=2)+'\n');bindings['authored_fixtures'][str(capture)]=sha(capture)
            actual,digest=load_capture(capture);module=out/'native-module';manifest=emit_capture(actual,module,digest)
            if manifest['native_instructions_emitted']!=len(actual['observations'])or manifest['unsupported_observations']or manifest['excluded_observations']:raise ValueError('Every actual identity must translate')
            bindings['generated_module']={str(p):sha(p)for p in module.iterdir()if p.is_file()}
            native=build_tool(args,out,report,bindings,compiler,tool,module)
            completed=execute('native',native,plan,image,cases,out,report,bindings,True)
            if completed[0]!=golden[0]or completed[0]!=observed[0]:raise ValueError('Native Arcade records differ')
            if {common.capture_identity(o):o['native_hits']for o in completed[1]['observations']}!={common.capture_identity(o):o['interpreted_hits']for o in observed[1]['observations']}:raise ValueError('Native source hit identities differ')
            literal['native']=expected_records(completed[0],cases,image_bytes)
            report['native']=dict(native_steps=completed[2]['native_steps'],interpreter_steps=0,guard_checks=completed[2]['guard_checks'],
                restored_source_mutations=completed[2]['restored_source_mutations'],identities=len(actual['observations']),mpr_contexts=len({tuple(o['mpr'])for o in actual['observations']}))
            report['tool']=source_identity(tool)
        report['port_fetch']=interpreter_port_fetch(gear,probe,image,out,report,bindings)
        report.update(result='pass',cases=len(cases),observations=len(golden[0]),literal_checks=literal,guest_retirements=count)
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:
        reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass':raise ValueError('Arcade evidence changed')
    print(json.dumps({k:v for k,v in report.items()if k not in('bindings','commands')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--tool-source',type=Path,default=ROOT)
    parser.add_argument('--probe',type=Path);parser.add_argument('--native',action='store_true');parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake');parser.add_argument('--ninja',default='ninja')
    parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
