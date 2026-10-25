"""Finite original-Gear VDC queue arbitration and unforced CPU stall traces.

Synthetic arbitration matrices call queue service with fixed authored phases;
full-scheduler and actual CPU cases never manually complete pending requests.
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

def firmware():
    ops=[]
    def add(*values):ops.append(bytes(values))
    def reg(index,value):add(3,index);add(0x13,value&255);add(0x23,value>>8)
    def sample(address,slot,mask=False):
        add(0xAD,address&255,address>>8)
        if mask:add(0x29,64)
        add(0x8D,slot,0x20)
    for value,mask in ((255,1),(248,2),(255,4)):add(0xA9,value);add(0x53,mask)
    reg(0,4);reg(2,0xCAFE);add(0x13,0x34);add(0x23,0x12)
    reg(1,4);add(3,2)
    for slot,address in enumerate((2,0x4003,2,3)):sample(address,slot)
    reg(15,0);reg(16,4);reg(17,0x100);reg(18,15);reg(1,0x100)
    sample(0,4,True);add(3,2);sample(2,5);sample(3,6)
    reg(1,0xFFFF);add(3,2);sample(2,7);sample(3,8);sample(2,9)
    # Memory-mapped writes and an independently checked TIA -> TAI stream.
    reg(0,6);add(3,2);add(0xA9,0xEF);add(0x8D,2,0);add(0xA9,0xBE);add(0x8D,3,0x40)
    reg(1,6);add(3,2);sample(2,10);sample(3,11)
    for offset,value in enumerate((0x34,0x12,0x78,0x56)):
        add(0xA9,value);add(0x8D,0x20+offset,0x20)
    reg(0,8);add(3,2);add(0xE3,0x20,0x20,2,0,4,0)
    reg(1,8);add(3,2);add(0xF3,2,0,0x30,0x20,4,0)
    add(0xEA)
    raw=bytearray([0xEA]*262144);code=b''.join(ops)
    raw[0x100:0x100+len(code)]=code;raw[8190:8192]=b'\x00\xE1'
    raw[0x300:0x307]=bytes((0xAD,2,0,0x8D,12,0x20,0xEA))
    return bytes(raw),ops

def write_register(index,value):return [('w',0,index),('w',2,value&255),('w',3,value>>8)]

def plans():
    cases=[]
    # Slot policy and request delay are independently separable. Fixed phase
    # service calls do not claim to be a free-running video schedule.
    for control in range(3):
        for phase_id in ('blank','hsw','background','sprites'):
            for mode in range(4):
                for hclock in range(0,36,3):
                    vstate=0 if phase_id=='blank' else 1
                    hstate=3 if phase_id=='hsw' else 1
                    start,end=(0,1365) if phase_id=='background' else (1365,0)
                    sprite_count=2 if phase_id=='sprites' else 0
                    cr=64 if sprite_count else 0
                    mwr=mode if phase_id=='background' else mode<<2
                    config=('f',hclock,vstate,hstate,0,mwr,cr,sprite_count,start,end,0)
                    cases.append(dict(id=f'slot-{control}-{phase_id}-{mode}-{hclock}',operations=[('r',1,control),config,('j',3)]))
    for control in range(3):
        for request in (1,2,3):
            ops=[('r',1,control),('f',100,0,1,0,0,0,0,1365,0,0),('q',request),('s',)]
            for chunk in (1,1,1,2,1,3,3,3,3,3,3,3,3,3,3):ops.extend((('k',chunk),('s',)))
            ops += [('p',0),('s',)]
            cases.append(dict(id=f'countdown-{control}-{request}',operations=ops))
    # Real scheduler steps; no synthetic phase mutation and no forced settle.
    for control in range(3):
        for request in (1,2):
            ops=[('r',1,control),('q',request),('s',)]
            for _ in range(40):ops.extend((('a',1),('s',)))
            cases.append(dict(id=f'clocked-reset-{control}-{request}',operations=ops))
    # Ordinary programmed display; warm to a stable active line before reads.
    for control in range(3):
        for mode in range(4):
            ops=[('r',1,control)]
            for index,value in ((5,128),(9,mode),(10,0x0202),(11,0x041F),(12,0x0F02),(14,4)):
                ops+=write_register(index,value)
            ops += [('a',2*262*1365+21*1365+120),('q',1),('s',)]
            for _ in range(32):ops.extend((('a',3),('s',)))
            cases.append(dict(id=f'active-background-{control}-{mode}',operations=ops))
    for fast in (0,1):
        for control in range(3):
            # A pending read is present before the generated-source guard
            # negatives and real first instruction. It advances only on clocks.
            cases.append(dict(id=f'actual-cpu-{fast}-{control}',operations=[('r',fast,control),('q',1),('i',len(firmware()[1])),('m',)]))
            cases.append(dict(id=f'actual-both-pending-{fast}-{control}',operations=[('r',fast,control),('x',0xE300),('w',0,2),('q',3),('i',3),('m',)]))
    return cases

def serialize(cases):return '\n'.join(' '.join(map(str,op))for case in cases for op in case['operations'])+'\n'

def slot_literal(op,control):
    _,hclock,vstate,hstate,burst,mode,cr,sprites,start,end,hsync=op
    divider=(4,3,2)[control]
    in_bg=not burst and start<=hclock<end
    if vstate!=1 or burst or (not(cr&64)or not sprites)and not in_bg:
        allowed=(hclock//divider)%2==0
    elif in_bg:
        dot=(hclock-start)//divider-1
        allowed=dot>=0 and (dot%2==0 if mode&3==0 else dot%8 in (2,3)if mode&3 in (1,2)else False)
    elif cr&64:
        count=(hclock-end if hclock>end else 1365-end+hclock)//divider
        allowed=count>=sprites*(4,4,8,16)[(mode>>2)&3]and(hclock//divider)%2==0
    else:allowed=True
    elapsed=(hclock+3-hsync)%1365
    return int(allowed and not(hstate==3 and elapsed<8*divider))

def validate_records(rows,cases):
    wanted=[]
    for case in cases:
        for op in case['operations']:
            if op[0]=='j':wanted.append(('slot',1))
            elif op[0]=='s':wanted.append(('device',37))
            elif op[0]=='p':wanted.append(('byte',2))
            elif op[0]=='m':wanted.append(('ram',64))
            elif op[0]=='i':wanted.extend([('cpu',16),('device',37)]*op[1])
    if type(rows)is not list or len(rows)!=len(wanted):raise ValueError('Queue observation count differs')
    for row,(kind,width)in zip(rows,wanted):
        if type(row)is not dict or set(row)!={'kind','values'}or row['kind']!=kind or type(row['values'])is not list or len(row['values'])!=width or any(type(v)is not int or not 0<=v<2**64 for v in row['values']):raise ValueError('Queue record shape/type differs')
    return rows

def literal_checks(rows,cases):
    validate_records(rows,cases);index=checks=0
    for case in cases:
        control=0;phase=None;countdown=None
        for op in case['operations']:
            if op[0]=='r':control=op[2]
            elif op[0]=='f':phase=op
            elif op[0]=='q'and case['id'].startswith('countdown-'):
                countdown=[int(bool(op[1]&1)),int(bool(op[1]&2)),((21,18,12)if op[1]&2 else(24,24,15))[control],0]
            elif op[0]=='k'and countdown is not None:
                # Independent three-tick service accounting with read priority.
                countdown[3]+=op[1]
                while countdown[3]>=3 and any(countdown[:2]):
                    countdown[3]-=3
                    if countdown[2]>0:
                        countdown[2]=max(0,countdown[2]-3)
                        if countdown[2]:continue
                    if slot_literal(phase,control):
                        countdown[0 if countdown[0]else 1]=0
                if not any(countdown[:2]):countdown[3]=0
            elif op[0]=='j':
                if rows[index]['values']!=[slot_literal(phase,control)]:raise ValueError('Independent arbitration literal differs: '+case['id'])
                index+=1;checks+=1
            elif op[0]=='s':
                values=rows[index]['values']
                if bool(values[9]&64)!=(bool(values[5])or bool(values[6])):raise ValueError('BUSY must describe pending queue')
                if values[10]>65535 or values[11]>65535:raise ValueError('Read buffer/bus are words')
                if countdown is not None:
                    if values[5:9]!=countdown:raise ValueError('Independent delay/priority/carry differs: '+case['id'])
                    checks+=4
                index+=1;checks+=3
            elif op[0]=='p':
                if op[1]==0 and not 0<=rows[index]['values'][1]<=127:raise ValueError('Status byte range')
                index+=1;checks+=1
            elif op[0]=='i':index+=op[1]*2
            elif op[0]=='m':
                # Driven data and retained-high reads are independent literal
                # values; BUSY differs by actual instruction/clock profile.
                ram=rows[index]['values']
                if case['id'].startswith('actual-both-pending'):
                    if ram[12]!=0x75:raise ValueError('Both-pending waiter did not return the prefetched word')
                    checks+=1;index+=1;continue
                if ram[:4]!=[254,202,52,18]or ram[5:7]!=[254,202]or ram[7:10]!=[52,18,0x3C]:
                    raise ValueError('Authored CPU result literals differ: '+str(ram[:10]))
                if ram[10:12]!=[0xEF,0xBE]or ram[48:52]!=[0x34,0x12,0x78,0x56]:
                    raise ValueError('Mapped write/block stream literals differ: '+str(ram[10:12])+str(ram[48:52]))
                checks+=15;index+=1
    if index!=len(rows):raise ValueError('Queue literal accounting differs')
    return checks

def compare_gear(actual,golden,cases):
    """Project only the named MWR3 background read-bus incompatibility.

    Gear renders MWR3 using 4bpp; the toolkit's independently Mesen-qualified
    path uses 2bpp. No CPU, queue, register or timing fields are projected.
    Raw differences are retained, with independent tool read-bus literals.
    """
    differences=[];index=0
    for case in cases:
        for op in case['operations']:
            count=op[1]*2 if op[0]=='i'else int(op[0]in('s','p','m','j'))
            for _ in range(count):
                a,b=actual[index],golden[index]
                mode3_case=case['id']in('active-background-0-3','active-background-1-3','active-background-2-3')
                if mode3_case and a['kind']=='device':
                    control=int(case['id'].split('-')[2]);address=31 if control==0 else 4164
                    expected=((address*73)^(address>>3)^0xA53C)&65535
                    if a['values'][11]!=expected:raise ValueError('Established MWR3 2bpp bus literal changed')
                if a!=b:
                    fields=[i for i,(x,y)in enumerate(zip(a['values'],b['values']))if x!=y]
                    allowed=case['id']in('active-background-0-3','active-background-1-3','active-background-2-3')and a['kind']==b['kind']=='device'and fields==[11]
                    if not allowed:raise ValueError(f'Queue reference mismatch record{index}: {a} vs {b}')
                    differences.append(dict(case=case['id'],record=index,field='vram_bus_latch',tool=a['values'][11],gear=b['values'][11]))
                index+=1
    return differences


def build_gear(args,out,report,bindings,compiler):
    checkout,source=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,source);cpp.append(ROOT/'tests/geargrafx_vdc_queue_probe.cpp')
    deps=checkout/'platforms/shared/dependencies';flags=['-O2','-ffp-contract=off','-ffunction-sections','-fdata-sections','-DGG_DISABLE_DISASSEMBLER','-DGG_DISABLE_VGMRECORDER','-DGG_DISABLE_MMI_THREADS']
    for p in(checkout/'src',ROOT/'tests',deps/'miniz',deps/'libchdr/include',deps/'minivorbis',deps/'json'):flags+=['-I',str(p)]
    objects=out/'objects';objects.mkdir();jobs=[]
    for i,path in enumerate(cpp+c):
        obj=objects/(str(i)+'-'+path.stem+'.o');cmd=[str(compiler),*flags,'-x','c++'if path.suffix=='.cpp'else'c',*(['-std=c++20','-include','cerrno']if path.suffix=='.cpp'else['-std=c11']),'-c',str(path),'-o',str(obj)]
        jobs.append((cmd,obj));report['commands'].append(cmd)
    def compile_one(job):
        cmd,obj=job;r=subprocess.run(cmd,capture_output=True,text=True,timeout=180);obj.with_suffix('.log').write_text(r.stdout+r.stderr);r.check_returncode()
    with ThreadPoolExecutor(max_workers=4)as pool:list(pool.map(compile_one,jobs))
    libs=[p.resolve()for p in args.library]
    if not libs or any(not p.is_file()for p in libs):raise ValueError('Supply explicit existing external libraries')
    bindings['external_libraries']={str(p):sha(p)for p in libs};binary=out/'gear-queue.exe'
    common.evidence([str(compiler),*[str(o)for _,o in jobs],*map(str,libs),'-Wl,--gc-sections','-o',str(binary)],'gear-link',out,report,bindings)
    bindings['gear_objects']={str(o):sha(o)for _,o in jobs};bindings['gear_binary']={str(binary):sha(binary)};return binary

def build_tool(args,out,report,bindings,compiler,module=None):
    tool=args.tool_source.resolve();label='native'if module else'interpreted';q=infrastructure.cmake_quote
    cmake,ninja=(Path(shutil.which(str(v))or'').resolve()for v in(args.cmake,args.ninja))
    bindings['tools'].update({str(p):sha(p)for p in(cmake,ninja)})
    wrapper=out/(label+'-wrapper');wrapper.mkdir();probe=ROOT/'tests/vdc_queue_oracle_probe.cpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(VdcQueueProof LANGUAGES CXX)',*['set('+o+' OFF CACHE BOOL "" FORCE)'for o in('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],f'add_subdirectory({q(tool)} tool)']
    if module:lines +=[f'pce_add_native_module(_module MODULE {q(module/"module.cpp")} MANIFEST {q(module/"module.json")})',f'add_executable(queue-probe {q(probe)})','target_compile_definitions(queue-probe PRIVATE PCE_QUEUE_NATIVE_ONLY=1)','target_link_libraries(queue-probe PRIVATE ${_module} pce-runtime)']
    else:lines +=[f'add_executable(queue-probe {q(probe)} {q(tool/"runtime/src/no_module.cpp")})','target_link_libraries(queue-probe PRIVATE pce-runtime)']
    file=wrapper/'CMakeLists.txt';file.write_text('\n'.join(lines)+'\n');bindings.setdefault('tool_build_inputs',{})[str(file)]=sha(file);build=out/(label+'-build')
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],label+'-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','queue-probe','--parallel','2'],label+'-build',out,report,bindings,600)
    binary=build/('queue-probe.exe'if os.name=='nt'else'queue-probe');bindings.setdefault('tool_binaries',{})[str(binary)]=sha(binary);return binary

def execute(label,binary,plan,image,cases,out,report,bindings,tier=None):
    cmd=[str(binary),str(plan),str(image)];capture=out/(label+'-capture.json')
    if tier:cmd+=['--capture',str(capture)]
    result=common.evidence(cmd,label,out,report,bindings);rows=validate_records(json.loads(result.stdout),cases)
    if not tier:return rows,None
    from pcerecomp.capture import load_capture
    from pcerecomp.project import ABI
    observed,_=load_capture(capture);bindings['raw_outputs'][str(capture)]=sha(capture)
    count=sum(op[1]for case in cases for op in case['operations']if op[0]=='i')
    if observed['runtime_abi']!=ABI or not observed['complete']or observed['retired_instructions']!=count or any(o['interpreted_hits']if tier=='native'else o['native_hits']for o in observed['observations']):raise ValueError('Actual execution tier/capture differs')
    return rows,observed

def run(args):
    compiler=Path(shutil.which(str(args.compiler))or'').resolve();out=args.out.resolve();tool=args.tool_source.resolve()
    if args.native:
        sys.path.insert(0,str(tool));from pcerecomp import project
        if Path(project.__file__).resolve()!=tool/'pcerecomp/project.py':raise ValueError('Wrong compiler import')
    if out.exists()or not out.is_relative_to(ROOT/'.local')or not compiler.is_file():raise ValueError('Require compiler and NEW private output')
    files=[Path(__file__),*[ROOT/'tests'/n for n in('vdc_queue_probe_support.hpp','geargrafx_vdc_queue_probe.cpp','vdc_queue_oracle_probe.cpp','reset_probe_support.hpp')],*[ROOT/'scripts'/n for n in('mapper_reference.py','hucard_reference.py','filtered_audio_reference.py','psg_reference.py')]]
    if args.native:files+=sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'pcerecomp').glob('*.py'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p.resolve()):sha(p)for p in files})
    report=dict(schema=1,result='incomplete',oracle_commit=reference.COMMIT,commands=[],bindings=bindings,configuration=['Original Gear queue/slot/CPU and full core scheduler; no manually settled or completed operations','Explicit synthetic phase fixtures for arbitration matrix/service-only tests; separate real scheduler traces and actual CPU retirement cases','Authored real MARR0 prefetch and 48 full-scheduler clocks establish the initial read buffer; original Gear cold reset FFFF differs from toolkit reset0'],scope='VDC queued read/write delay, partial service phase, BUSY, slot arbitration, normal scheduler progression and actual native CPU wait traces',not_checked=['Physical hardware or electrical bus phases','SuperGrafx priority','Complete guest instruction bus-phase accuracy beyond checked sequences'])
    report['reference_projection']=dict(cases=['active-background-0-3','active-background-1-3','active-background-2-3'],field='device.values[11]: vram_bus_latch',reason='Gear background renderer treats MWR3 as4bpp; established Mesen-qualified toolkit profile is2bpp',tool_literals={'divider4':44520,'divider3_and2':1104},exact_fields='All other records and fields, including all actual CPU states, queue delay/carry, BUSY, memory and timestamps')
    out.mkdir(parents=True);epoch=out/'authored-inputs';epoch.mkdir();bindings['authored_epoch']={}
    for i,p in enumerate(files):
        saved=epoch/str(i)/p.name;saved.parent.mkdir();shutil.copyfile(p,saved);bindings['authored_epoch'][str(saved)]=sha(saved)
    try:
        image=out/'authored.pce';image.write_bytes(firmware()[0]);cases=plans();plan=out/'queue.plan';plan.write_text(serialize(cases));bindings['authored_fixtures']={str(p):sha(p)for p in(image,plan)}
        gear=build_gear(args,out,report,bindings,compiler);golden=execute('gear',gear,plan,image,cases,out,report,bindings);literals={'gear':literal_checks(golden[0],cases)}
        probe=build_tool(args,out,report,bindings,compiler)if args.native else args.probe.resolve()if args.probe else None
        if probe:
            actual=execute('interpreted',probe,plan,image,cases,out,report,bindings,'interpreted')
            report['known_renderer_reference_differences']=compare_gear(actual[0],golden[0],cases)
            literals['interpreter']=literal_checks(actual[0],cases)
        if args.native:
            from pcerecomp.capture import load_capture
            from pcerecomp.emitter import emit_capture
            from pcerecomp.project import source_identity
            observed,digest=load_capture(out/'interpreted-capture.json');module=out/'native-module';manifest=emit_capture(observed,module,digest)
            if manifest['unsupported_observations']or manifest['excluded_observations']:raise ValueError('All captured operations must translate')
            bindings['generated_module']={str(p):sha(p)for p in module.iterdir()if p.is_file()}
            binary=build_tool(args,out,report,bindings,compiler,module);native=execute('native',binary,plan,image,cases,out,report,bindings,'native')
            compare_gear(native[0],golden[0],cases)
            if native[0]!=actual[0]:raise ValueError('Native/interpreter full records differ')
            if {common.capture_identity(o):o['native_hits']for o in native[1]['observations']}!={common.capture_identity(o):o['interpreted_hits']for o in actual[1]['observations']}:raise ValueError('Actual per-key native hits differ')
            if (out/'native.stderr').read_text().strip()!='PCE_QUEUE_GUARDS=24':raise ValueError('Twenty-four pure native guard negatives required')
            literals['native']=literal_checks(native[0],cases);report['tool']=source_identity(tool);report['native']=dict(retirements=native[1]['retired_instructions'],interpreted=0,identities=len(observed['observations']),mpr_contexts=len({tuple(o['mpr'])for o in observed['observations']}),pure_guard_negatives=24)
        report.update(result='pass',cases=len(cases),records=len(golden[0]),literal_checks=literals,actual_cpu_cases=12,retirements_per_main_cpu_case=len(firmware()[1]),retirements_per_both_pending_case=3)
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass':raise ValueError('Evidence preservation failed')
    print(json.dumps({k:v for k,v in report.items()if k not in('bindings','commands')},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--tool-source',type=Path,default=ROOT);parser.add_argument('--probe',type=Path);parser.add_argument('--native',action='store_true');parser.add_argument('--out',type=Path,required=True);parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake');parser.add_argument('--ninja',default='ninja');parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
