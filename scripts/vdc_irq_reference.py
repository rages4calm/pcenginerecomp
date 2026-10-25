"""Authored timer-underflow/IRQ traces across real queued VDC DMA stalls.

Original pinned Gear and the toolkit run in separate processes. Timer phase is
established using real timer ports plus scheduler clocks; no pending request is
manually completed. All compared records include exact guest master timestamps.
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
from scripts import vdc_queue_reference as queue
infrastructure,common,reference=queue.infrastructure,queue.common,queue.reference
sha=reference.sha


def firmware():
    raw=bytearray([0xEA]*262144)
    raw[0x300:0x30F]=bytes.fromhex('AD 02 00 8D 10 20 58 A9 00 8D 02 14 EA 80 FE')
    handler=bytes.fromhex('48 A9 00 8D 01 0C 8D 03 14 EE 20 20 68 40')
    raw[0x400:0x400+len(handler)]=handler
    for vector,target in ((0x1FFA,0xE400),(0x1FFE,0xE300)):
        raw[vector:vector+2]=target.to_bytes(2,'little')
    return bytes(raw)


def plans():
    return [dict(id=f'irq-{fast}-{control}-{phase}-{mode}',fast=fast,control=control,phase=phase,mode=mode,operations=[('r',fast,control),('z',phase,mode),('i',22),('m',)])for fast in(0,1)for control in range(3)for phase in(18,30,60)for mode in range(3)]


def validate_records(rows,cases):
    widths={'cpu':16,'device':45,'ram':64};wanted=[]
    for case in cases:wanted += ['device']+['cpu','device']*22+['ram']
    if type(rows)is not list or len(rows)!=len(wanted):raise ValueError('Wrong IRQ record count')
    for row,kind in zip(rows,wanted):
        if type(row)is not dict or set(row)!={'kind','values'}or row['kind']!=kind or type(row['values'])is not list or len(row['values'])!=widths[kind]or any(type(n)is not int or not 0<=n<2**64 for n in row['values']):raise ValueError('Invalid IRQ record shape')
    return rows


def literal_checks(rows,cases):
    validate_records(rows,cases);index=checks=0
    for case in cases:
        group=rows[index:index+46];index+=46
        armed=group[0]['values'];first=group[1]['values'];first_device=group[2]['values'];ram=group[-1]['values'];last=group[-2]['values']
        if armed[37:43]!=[1,0,0,case['phase'],0,4 if case['mode']==2 else 0]:raise ValueError('Real timer arming differs')
        if not armed[5]or not armed[14]:raise ValueError('Authored read and DMA must be genuinely pending')
        if first[0]!=(0xE400 if case['mode']==0 else 0xE303):raise ValueError('IRQ masked/unmasked first retirement differs')
        if not first_device[41]&4 or not first_device[44]:raise ValueError('Timer must underflow while access accumulates waits')
        if armed[0]+case['phase']!=3120 or first[7]<=3120:raise ValueError('Expected timer deadline must lie within first instruction')
        if ram[16]!=0x3C or ram[32]!=1:raise ValueError('Blocked read/one acknowledged handler literals differ')
        if last[37]!=0 or last[41]&4:raise ValueError('Handler must stop and acknowledge timer')
        if sum(row['values'][0]==0xE400 for row in group if row['kind']=='cpu')!=1:raise ValueError('Exactly one actual timer IRQ entry required')
        checks+=18
    return checks


def build_gear(args,out,report,bindings,compiler):
    checkout,source=infrastructure.pinned_snapshot(args.gear_source.resolve(),out,bindings)
    cpp,c=reference.compile_sources(checkout,source);cpp.append(ROOT/'tests/geargrafx_vdc_irq_probe.cpp')
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
    wrapper=out/(label+'-wrapper');wrapper.mkdir();probe=ROOT/'tests/vdc_irq_oracle_probe.cpp'
    lines=['cmake_minimum_required(VERSION 3.20)','project(VdcIrqProof LANGUAGES CXX)',*['set('+o+' OFF CACHE BOOL "" FORCE)'for o in('PCE_BUILD_TOOLS','PCE_BUILD_TESTS','PCE_BUILD_DESKTOP','PCE_BUILD_REFERENCE_PROBE','BUILD_TESTING')],f'add_subdirectory({q(tool)} tool)']
    if module:lines +=[f'pce_add_native_module(_module MODULE {q(module/"module.cpp")} MANIFEST {q(module/"module.json")})',f'add_executable(queue-probe {q(probe)})','target_compile_definitions(queue-probe PRIVATE PCE_QUEUE_NATIVE_ONLY=1)','target_link_libraries(queue-probe PRIVATE ${_module} pce-runtime)']
    else:lines +=[f'add_executable(queue-probe {q(probe)} {q(tool/"runtime/src/no_module.cpp")})','target_link_libraries(queue-probe PRIVATE pce-runtime)']
    file=wrapper/'CMakeLists.txt';file.write_text('\n'.join(lines)+'\n');bindings.setdefault('tool_build_inputs',{})[str(file)]=sha(file);build=out/(label+'-build')
    common.evidence([str(cmake),'-S',str(wrapper),'-B',str(build),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler),'-DCMAKE_MAKE_PROGRAM='+str(ninja)],label+'-configure',out,report,bindings)
    common.evidence([str(cmake),'--build',str(build),'--target','queue-probe','--parallel','2'],label+'-build',out,report,bindings,600)
    binary=build/('queue-probe.exe'if os.name=='nt'else'queue-probe');bindings.setdefault('tool_binaries',{})[str(binary)]=sha(binary);return binary



def execute(label,binary,plan,image,cases,out,report,bindings,tier=None):
    command=[str(binary),str(plan),str(image)];capture=out/(label+'-capture.json')
    if tier:command+=['--capture',str(capture)]
    result=common.evidence(command,label,out,report,bindings)
    rows=validate_records(json.loads(result.stdout),cases)
    if not tier:return rows,None
    from pcerecomp.capture import load_capture
    from pcerecomp.project import ABI
    observed,_=load_capture(capture);bindings['raw_outputs'][str(capture)]=sha(capture)
    if observed['runtime_abi']!=ABI or not observed['complete']or observed['retired_instructions']!=22*len(cases)or any(o['interpreted_hits']if tier=='native'else o['native_hits']for o in observed['observations']):raise ValueError('IRQ execution tier differs')
    return rows,observed


def compare(actual,expected,cases):
    if actual!=expected:
        i=next(i for i,(a,b)in enumerate(zip(actual,expected))if a!=b)
        raise ValueError(f'IRQ mismatch case{cases[i//46]["id"]} record{i}: {actual[i]} vs {expected[i]}')


def run(args):
    out=args.out.resolve();tool=args.tool_source.resolve();compiler=Path(shutil.which(str(args.compiler))or'').resolve()
    if out.exists()or not out.is_relative_to(ROOT/'.local')or not compiler.is_file():raise ValueError('Require compiler and NEW private output')
    sys.path.insert(0,str(tool));from pcerecomp import project
    if Path(project.__file__).resolve()!=tool/'pcerecomp/project.py':raise ValueError('Wrong compiler import')
    names=('test_vdc_irq_reference.py','vdc_irq_probe_support.hpp','geargrafx_vdc_irq_probe.cpp','vdc_irq_oracle_probe.cpp','vdc_queue_probe_support.hpp','geargrafx_vdc_queue_probe.cpp','vdc_queue_oracle_probe.cpp','reset_probe_support.hpp')
    files=[Path(__file__),*[ROOT/'tests'/name for name in names],*[ROOT/'scripts'/name for name in('vdc_queue_reference.py','mapper_reference.py','hucard_reference.py','filtered_audio_reference.py','psg_reference.py')]]
    files+=sorted((tool/'runtime').rglob('*.cpp'))+sorted((tool/'runtime').rglob('*.hpp'))+sorted((tool/'pcerecomp').glob('*.py'))+[tool/'CMakeLists.txt',tool/'cmake/PCEConsumer.cmake']
    bindings=dict(tools={str(compiler):sha(compiler)},authored_sources={str(p.resolve()):sha(p)for p in files})
    report=dict(schema=1,result='incomplete',verification_mode='tool-native'if args.native else'gear-only',oracle_commit=reference.COMMIT,commands=[],bindings=bindings,scope='Timer underflow during actual queued VDC read blocked by VRAM DMA; timer IRQ sampled during waits, immediate or masked deferred entry, acknowledge, disable and RTI',configuration=['Real timer reload/control ports followed by full-scheduler phase clocks','Real finite16word DMA and MARR prefetch; no manually completed pending requests','Authored initial IO/RAM MPR mapping and CPU interrupt flags','Both CPU speeds, three VCE speeds, remaining timer phases18/30/60 and unmasked/I-masked/IRQ-masked delivery'],not_checked=['Electrical bus phases','Timer underflow on other instruction retirement phases','IRQ1/IRQ2 priority and mixed-source delivery','Whole game compatibility'])
    report['scope']+='; original Gear only, no toolkit execution comparison'if not args.native else'; toolkit interpreter and actual native execution compared exactly with original Gear'
    out.mkdir(parents=True);epoch=out/'authored-inputs';epoch.mkdir();bindings['authored_epoch']={}
    for i,p in enumerate(files):
        copy=epoch/str(i)/p.name;copy.parent.mkdir();shutil.copyfile(p,copy);bindings['authored_epoch'][str(copy)]=sha(copy)
    try:
        image=out/'authored.pce';image.write_bytes(firmware());cases=plans();plan=out/'irq.plan';plan.write_text(queue.serialize(cases));bindings['authored_fixtures']={str(p):sha(p)for p in(image,plan)}
        gear=build_gear(args,out,report,bindings,compiler);golden=execute('gear',gear,plan,image,cases,out,report,bindings);literals={'gear':literal_checks(golden[0],cases)}
        events=(out/'gear.stderr').read_text().splitlines()
        if len(events)!=len(cases):raise ValueError('One original Gear timer-underflow clock callback per case required')
        for line in events:
            tag,tick,extra,dma=line.split()
            if tag!='UNDERFLOW'or int(tick)!=3120 or int(extra)<=0 or int(dma)<=0:raise ValueError('Original underflow must occur during dynamic wait and active DMA')
        report['original_underflow_events']=len(events)
        if args.native:
            probe=build_tool(args,out,report,bindings,compiler);actual=execute('interpreted',probe,plan,image,cases,out,report,bindings,'interpreted');compare(actual[0],golden[0],cases);literals['interpreter']=literal_checks(actual[0],cases)
            from pcerecomp.capture import load_capture
            from pcerecomp.emitter import emit_capture
            from pcerecomp.project import source_identity
            observed,digest=load_capture(out/'interpreted-capture.json');module=out/'native-module';manifest=emit_capture(observed,module,digest)
            if manifest['unsupported_observations']or manifest['excluded_observations']:raise ValueError('Every IRQ observation must translate')
            bindings['generated_module']={str(p):sha(p)for p in module.iterdir()if p.is_file()}
            binary=build_tool(args,out,report,bindings,compiler,module);native=execute('native',binary,plan,image,cases,out,report,bindings,'native');compare(native[0],golden[0],cases)
            if {common.capture_identity(o):o['native_hits']for o in native[1]['observations']}!={common.capture_identity(o):o['interpreted_hits']for o in actual[1]['observations']}:raise ValueError('Per-source IRQ hits differ')
            if (out/'native.stderr').read_text().strip()!=f'PCE_QUEUE_GUARDS={2*len(cases)}':raise ValueError('Pure pending timer/queue native guard negatives missing')
            literals['native']=literal_checks(native[0],cases);report['tool']=source_identity(tool);report['native']=dict(retirements=native[1]['retired_instructions'],interpreted=0,identities=len(observed['observations']),pure_guard_negatives=2*len(cases))
        report.update(result='pass',cases=len(cases),records=len(golden[0]),literal_checks=literals)
    except Exception as error:report.update(result='fail',error=str(error));raise
    finally:reference.record_preservation(report,bindings);(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    if report['result']!='pass':raise ValueError('Evidence preservation failed')
    print(json.dumps({k:v for k,v in report.items()if k not in('commands','bindings')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gear-source',type=Path,required=True);parser.add_argument('--tool-source',type=Path,default=ROOT);parser.add_argument('--native',action='store_true');parser.add_argument('--out',type=Path,required=True);parser.add_argument('--compiler',default='clang++');parser.add_argument('--cmake',default='cmake');parser.add_argument('--ninja',default='ninja');parser.add_argument('--library',type=Path,action='append',default=[])
    try:run(parser.parse_args())
    except(ValueError,RuntimeError,OSError,KeyError,subprocess.SubprocessError)as error:print(error,file=sys.stderr);raise SystemExit(1)
